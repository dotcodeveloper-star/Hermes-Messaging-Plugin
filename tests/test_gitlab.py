"""Exercise the outbound transport against a real local fake GitLab API."""
import asyncio
import copy
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestServer
from gateway.config import GatewayConfig, PlatformConfig
from gateway.platforms.event import ProcessingOutcome
from gateway.session import SessionStore, build_session_key
from hermes_cli.plugins import PluginManager
from hermes_cli.plugins_manifest import parse_manifest_file


class GitLabFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        path = Path(__file__).parents[1] / "adapter.py"
        spec = importlib.util.spec_from_file_location("gitlab_adapter", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.tmp.name,
                                         **{env: "" for env, _, _ in self.module.ENV}}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        manifest = parse_manifest_file(path.with_name("plugin.yaml"), path.parent, "user", "")
        self.assertIsNotNone(manifest)
        manager = PluginManager()
        manager._load_plugin(manifest)
        self.assertTrue(manager._plugins["hermes-gitlab"].enabled,
                        manager._plugins["hermes-gitlab"].error)
        self.posts, self.requests, self.todos, self.events = [], [], [], []
        self.discussions = []
        self.issue_notes = None
        self.posted_discussions = {}
        self.closing_issues, self.related_issues = [], []
        self.fail_context = self.fail_send = self.fail_list = False
        self.issue_assigned = True
        self.fail_list_page = None
        self.sort_todos = True
        self.page_size = 100
        self.delivery_count = 0

        def discussion_notes(discussion_id, create=False):
            if discussion_id in self.posted_discussions:
                return self.posted_discussions[discussion_id]
            for item in self.discussions:
                if item.get("id") == discussion_id:
                    self.posted_discussions[discussion_id] = list(item.get("notes") or [])
                    return self.posted_discussions[discussion_id]
            if create:
                self.posted_discussions[discussion_id] = []
                return self.posted_discussions[discussion_id]
            return None

        def apply_note_edit(note_id, body):
            for notes in list(self.posted_discussions.values()) + [item.get("notes") or [] for item in self.discussions]:
                for note in notes:
                    if str(note.get("id")) == str(note_id):
                        note["body"] = body
                        return

        async def api(request):
            self.assertEqual(request.headers.get("PRIVATE-TOKEN"), "test-pat")
            self.requests.append((request.method, request.path, dict(request.query)))
            if request.path == "/api/v4/user":
                return web.json_response({"id": 99, "username": "hermes-bot"})
            if request.path == "/api/v4/todos":
                if self.fail_list or (request.query["state"], request.query["page"]) == self.fail_list_page:
                    return web.json_response({"error": "test-pat must not appear in logs"}, status=503)
                todos = [todo for todo in self.todos
                         if todo.get("state") == request.query["state"]
                         and ("project_id" not in request.query or
                              str(todo.get("project", {}).get("id")) == request.query["project_id"])]
                if self.sort_todos:
                    todos.sort(key=lambda todo: int(todo["id"]) if str(todo["id"]).isdigit() else 0, reverse=True)
                page = int(request.query["page"])
                chunk = todos[(page - 1) * self.page_size:page * self.page_size]
                return web.json_response(chunk, headers={
                    "X-Next-Page": str(page + 1) if page * self.page_size < len(todos) else ""})
            if request.method == "PUT":
                payload = await request.json()
                self.posts.append((request.path, payload))
                note_id = request.path.rsplit("/", 1)[-1]
                if not note_id.isdigit() or note_id.startswith("0"):
                    return web.json_response({"error": "bad note"}, status=400)
                apply_note_edit(note_id, payload.get("body"))
                return web.json_response({"id": int(note_id)})
            if request.method == "POST":
                if self.fail_send:
                    return web.json_response({"error": "test-pat secret response body"}, status=503)
                payload = await request.json()
                self.posts.append((request.path, payload))
                self.delivery_count += 1
                # GitLab replies complete other pending requests on this card too.
                for todo in self.todos:
                    resource = "issues" if todo.get("target_type") == "Issue" else "merge_requests"
                    if request.path.startswith(f"/api/v4/projects/{todo['project']['id']}/"
                                               f"{resource}/{todo['target']['iid']}/"):
                        todo["state"] = "done"
                note = {"id": 500 + self.delivery_count, "body": payload.get("body"), "system": False,
                        "author": {"id": 99, "username": "hermes-bot"}}
                if request.path.endswith("/discussions"):
                    self.posted_discussions["c" * 40] = [note]
                    return web.json_response({"id": "c" * 40, "notes": [note]}, status=201)
                discussion_notes(request.path[:-len("/notes")].rsplit("/", 1)[-1], create=True).append(note)
                return web.json_response(note, status=201)
            if self.fail_context:
                return web.json_response({"error": "test-pat secret response body"}, status=503)
            if request.path.endswith(("/closes_issues", "/related_issues")):
                rows = self.closing_issues if request.path.endswith("/closes_issues") else self.related_issues
                page = int(request.query.get("page", 1))
                return web.json_response(rows[(page - 1) * self.page_size:page * self.page_size], headers={
                    "X-Next-Page": str(page + 1) if page * self.page_size < len(rows) else ""})
            if request.path.endswith("/discussions"):
                page = int(request.query.get("page", 1))
                chunk = self.discussions[(page - 1) * self.page_size:page * self.page_size]
                return web.json_response(chunk, headers={
                    "X-Next-Page": str(page + 1) if page * self.page_size < len(self.discussions) else ""})
            if "/discussions/" in request.path and not request.path.endswith("/notes"):
                discussion_id = request.path.rsplit("/", 1)[-1]
                notes = discussion_notes(discussion_id)
                if notes is None:
                    return web.json_response({"error": "missing discussion"}, status=404)
                return web.json_response({"id": discussion_id, "notes": notes})
            if request.path.endswith("/notes"):
                return web.json_response(self.issue_notes if self.issue_notes is not None else [
                    {"id": 7, "body": "Earlier context", "system": False,
                     "author": {"username": "alice"}},
                    {"id": 6, "body": "system context", "system": True,
                     "author": {"username": "alice"}},
                ])
            return web.json_response({"title": "Fix login", "description": "Login fails",
                                      "assignees": [{"id": 99}] if self.issue_assigned else [],
                                      "web_url": str(self.api.make_url("/group/repo/-/issues/3"))})

        api_app = web.Application()
        api_app.router.add_route("*", "/api/v4/{tail:.*}", api)
        self.api = TestServer(api_app)
        self.addAsyncCleanup(self.api.close)
        await self.api.start_server()
        self.config = PlatformConfig(extra={
            "url": str(self.api.make_url("/")), "token": "test-pat",
            "projects": "42", "allowed_users": "7",
        })
        self.adapter = await self.new_adapter()

    async def new_adapter(self):
        adapter = self.module.GitLabAdapter(self.config)
        self.addAsyncCleanup(adapter.disconnect)
        self.assertTrue(await adapter.connect())
        # Deterministic polls in most tests; one test exercises the actual background loop.
        adapter._poll_task.cancel()
        await asyncio.gather(adapter._poll_task, return_exceptions=True)
        adapter._poll_task = None

        async def capture(event):
            self.events.append(event)
            event._heartbeat_execution_started = True  # Stand-in for the native agent execution boundary.
            event._gateway_accepted = True
            await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

        adapter.handle_message = capture
        return adapter

    def todo(self, todo_id=101, **overrides):
        return {"id": todo_id, "project": {"id": 42},
                "author": {"id": 7, "username": "alice"}, "action_name": "mentioned",
                "target_type": "Issue", "target": {"iid": 3},
                "body": "@hermes-bot please help", "state": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(), **overrides}

    def row(self, todo_id=101):
        return self.adapter._db.execute(
            "SELECT completed, attempts, last_error FROM inbox WHERE id = ?", (todo_id,)).fetchone()

    async def finish_native(self):
        tasks = list(self.adapter._background_tasks)
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    def native_handler(self, handler):
        self.adapter.handle_message = self.module.BasePlatformAdapter.handle_message.__get__(self.adapter)
        self.adapter.set_message_handler(handler)

    def session_store(self):
        store = SessionStore(Path(self.tmp.name) / "sessions", GatewayConfig())
        self.addCleanup(store.close_all_db_handles)
        self.adapter.set_session_store(store)
        return store

    def command_todo(self, todo_id, body, note_id=900, **overrides):
        note = {"id": note_id, "body": body, "author": {"id": 7}, "system": False}
        self.discussions = [{"id": "commands", "notes": [note]}]
        return self.todo(todo_id, body=body, target_url=f"https://gitlab.example/#note_{note_id}", **overrides)

    async def test_mattermost_handoff_uses_the_existing_issue_session(self):
        store = self.session_store()
        existing = store.get_or_create_session(self.adapter._card_source(
            "42:issues:3", {"id": 7, "username": "alice"}))
        store.append_to_transcript(existing.session_id, {"role": "user", "content": "Earlier GitLab decision"})
        handoff = {
            "issue": "42:issues:3", "profile": "default",
            "origin_channel": "a" * 26, "origin_root": "b" * 26,
            "origin_post": "c" * 26, "origin_user": "d" * 26,
            "origin_url": "https://mattermost.example/pl/" + "b" * 26,
            "issue_url": "https://gitlab.example/group/repo/-/issues/3",
            "request": "Lanjutkan pekerjaan ini",
        }
        identity = self.module.enqueue_handoff(self.adapter.state_path, handoff)
        self.assertEqual(identity, self.module.enqueue_handoff(self.adapter.state_path, handoff))
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].source.chat_id, "42:issues:3")
        self.assertTrue(self.events[0].source.role_authorized)
        self.assertEqual(store.get_or_create_session(self.events[0].source).session_id, existing.session_id)
        self.assertEqual(self.events[0].message_id, identity)
        self.assertIn("Lanjutkan pekerjaan ini", self.events[0].text)
        self.assertIn(handoff["origin_url"], self.events[0].text)
        self.assertEqual(len([post for path, post in self.posts
                              if path == "/api/v4/projects/42/issues/3/notes"
                              and "[RM1](" in post.get("body", "")]), 1)
        self.assertEqual(self.adapter._db.execute(
            "SELECT completed FROM handoffs WHERE id = ?", (identity,)).fetchone(), (1,))
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)

    async def test_handoff_waits_when_issue_assignment_is_removed(self):
        handoff = {
            "issue": "42:issues:3", "profile": "default",
            "origin_channel": "a" * 26, "origin_root": "b" * 26,
            "origin_post": "c" * 26, "origin_user": "d" * 26,
            "origin_url": "https://mattermost.example/pl/" + "b" * 26,
            "issue_url": "https://gitlab.example/group/repo/-/issues/3",
            "request": "Lanjutkan pekerjaan ini",
        }
        identity = self.module.enqueue_handoff(self.adapter.state_path, handoff)
        self.issue_assigned = False
        await self.adapter._poll_once()
        self.assertEqual(self.events, [])
        self.assertEqual(self.adapter._db.execute(
            "SELECT completed FROM handoffs WHERE id = ?", (identity,)).fetchone(), (0,))
        self.issue_assigned = True
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)

    async def test_handoff_refreshes_ci_and_review_discussion_on_next_mention(self):
        handoff = {
            "issue": "42:issues:3", "profile": "default",
            "origin_channel": "a" * 26, "origin_root": "b" * 26,
            "origin_post": "c" * 26, "origin_user": "d" * 26,
            "origin_url": "https://mattermost.example/pl/" + "b" * 26,
            "issue_url": "https://gitlab.example/group/repo/-/issues/3",
            "request": "Cek kelanjutan pekerjaan",
        }
        self.issue_notes = [{"id": 7, "body": "CI pending; review belum ada", "system": False,
                             "author": {"username": "alice"}}]
        self.module.enqueue_handoff(self.adapter.state_path, handoff)
        await self.adapter._poll_once()
        self.assertIn("CI pending", self.events[-1].text)
        self.issue_notes = [{"id": 8, "body": "CI gagal; review meminta perbaikan", "system": False,
                             "author": {"username": "alice"}}]
        handoff["origin_post"] = "e" * 26
        self.module.enqueue_handoff(self.adapter.state_path, handoff)
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 2)
        self.assertIn("CI gagal; review meminta perbaikan", self.events[-1].text)
        self.assertIn("Verify current issue assignment and live MR, CI, review", self.events[-1].text)

    async def test_handoff_report_retries_mattermost_without_reposting_gitlab(self):
        mm_posts = []

        async def mattermost_post(request):
            self.assertEqual(request.headers.get("Authorization"), "Bearer mm-pat")
            mm_posts.append(await request.json())
            if len(mm_posts) == 1:
                return web.json_response({"error": "temporary"}, status=503)
            return web.json_response({"id": "e" * 26}, status=201)

        app = web.Application()
        app.router.add_post("/api/v4/posts", mattermost_post)
        async def mattermost_root(request):
            return web.json_response({"id": "b" * 26, "channel_id": "a" * 26, "root_id": ""})

        app.router.add_get("/api/v4/posts/{post_id}", mattermost_root)
        mm = TestServer(app)
        self.addAsyncCleanup(mm.close)
        await mm.start_server()
        origin = str(mm.make_url("/pl/" + "b" * 26))
        handoff = {
            "issue": "42:issues:3", "profile": "default",
            "origin_channel": "a" * 26, "origin_root": "b" * 26,
            "origin_post": "c" * 26, "origin_user": "d" * 26,
            "origin_url": origin, "request": "Lanjutkan pekerjaan ini",
            "issue_url": str(self.api.make_url("/group/repo/-/issues/3")),
        }
        identity = self.module.enqueue_handoff(self.adapter.state_path, handoff)
        results = []

        async def capture(event):
            self.events.append(event)
            result = await self.adapter.send("42:issues:3", "Selesai dan sudah diuji.",
                                             reply_to=identity,
                                             metadata={"notify": True, "hermes_profile": "default"})
            results.append(result.success)
            event._heartbeat_execution_started = True
            event._gateway_accepted = True
            await self.adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

        self.adapter.handle_message = capture
        with patch.dict(os.environ, {"MATTERMOST_URL": str(mm.make_url("/")),
                                     "MATTERMOST_TOKEN": "mm-pat"}):
            await self.adapter._poll_once()
            self.assertEqual(len(mm_posts), 1)
            await self.adapter.disconnect()
            self.adapter = await self.new_adapter()
            await self.adapter._poll_once()
        self.assertEqual(results, [True])
        self.assertEqual(len(self.events), 1)
        self.assertEqual(len([post for path, post in self.posts
                              if post.get("body", "").startswith("Selesai")]), 1)
        self.assertEqual(len(mm_posts), 2)
        self.assertEqual(mm_posts[-1]["root_id"], "b" * 26)
        self.assertIn("[RM1](", mm_posts[-1]["message"])
        self.assertIn("[RG](", mm_posts[-1]["message"])

    async def test_commands_bypass_busy_card_and_execute_only_once(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(event):
            self.events.append(event)
            if event.get_command():
                return "Native status"
            started.set()
            await release.wait()
            return "Answer"

        self.native_handler(handler)
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        await asyncio.wait_for(started.wait(), 5)
        self.todos.append(self.command_todo(102, "@hermes-bot /status"))
        await self.adapter._poll_once()
        self.assertEqual([e.get_command() for e in self.events], [None, "status"])
        self.assertTrue(self.adapter._active_sessions)
        self.assertEqual(self.row(102)[0], 1)
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/issues/3/discussions/commands/notes")
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 2)
        # /stop must not cause the durable inbox to immediately restart cancelled work.
        self.todos.append(self.command_todo(103, "@hermes-bot /stop", 901))
        await self.adapter._poll_once()
        await self.finish_native()
        await self.adapter._poll_once()
        self.assertEqual([e.get_command() for e in self.events], [None, "status", "stop"])
        self.assertEqual(self.row()[0], 1)
        self.assertFalse(self.adapter._active_sessions)

    async def test_approval_matches_live_prompt_and_cannot_approve_another_request(self):
        from tools import approval
        from tools.approval_gateway_wait import _ApprovalEntry
        self.related_issues = [{"project_id": 42, "iid": 3}]
        # Establish delivery from a linked MR, while its issue is the session identity.
        self.todos = [self.command_todo(101, "@hermes-bot implement", 7,
                                      target_type="MergeRequest", target={"iid": 8})]
        await self.adapter._poll_once()
        event = self.events[0]
        key = self.adapter._event_session_key(event)
        first = _ApprovalEntry({"command": "test only", "allow_session": True})
        second = _ApprovalEntry({"command": "another test"})
        with approval._lock:
            approval._gateway_queues[key] = [first]
        self.addCleanup(approval.unregister_gateway_notify, key)
        self.assertTrue(self.adapter.supports_exec_approval_buttons())
        sent = await self.adapter.send_exec_approval(event.source.chat_id, "test only", key)
        self.assertTrue(sent.success)
        self.assertIn("@hermes-bot /approve", self.posts[-1][1]["body"])
        # Existing in-flight work must not hold the control reply in the inbox.
        self.adapter._inflight["todo:busy"] = key
        self.todos = [self.command_todo(102, "@hermes-bot /approve session",
                                      target_type="MergeRequest", target={"iid": 8})]
        await self.adapter._poll_once()
        self.assertEqual(first.result, "session")
        self.assertTrue(first.event.is_set())
        self.assertEqual(self.row(102)[0], 1)
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/merge_requests/8/discussions/commands/notes")
        with approval._lock:
            approval._gateway_queues[key] = [second]
        # Same note with another to-do ID, plus a fresh reply to the expired prompt.
        self.todos += [self.command_todo(103, "@hermes-bot /approve session", target_type="MergeRequest", target={"iid": 8}),
                       self.command_todo(104, "@hermes-bot /approve", 901, target_type="MergeRequest", target={"iid": 8})]
        self.discussions[0]["notes"].append({"id": 900, "body": "@hermes-bot /approve session", "author": {"id": 7}})
        await self.adapter._poll_once()
        self.assertIsNone(second.result)
        self.assertFalse(second.event.is_set())
        self.assertIn("kedaluwarsa", self.posts[-1][1]["body"])
        self.adapter._inflight.clear()
        await self.adapter.disconnect()
        self.adapter = await self.new_adapter()
        await self.adapter._poll_once()
        self.assertFalse(second.event.is_set())  # Receipts survive a gateway restart.
        self.assertEqual(self.row(103)[0], 1)

    async def test_command_trust_boundaries_and_no_retry_after_delivery_failure(self):
        calls = []

        async def handler(event):
            calls.append(event.get_command())
            return "Reply"

        self.native_handler(handler)
        for number, body in enumerate(("@hermes-bot /status", "@hermes-bot /yolo"), 101):
            self.todos = [self.command_todo(number, body, 900 + number)]
            self.fail_send = True
            with patch.object(self.adapter, "_send_with_retry", AsyncMock(return_value=self.module.SendResult(success=False))):
                await self.adapter._poll_once()
                await self.finish_native()
                await self.adapter._poll_once()
            self.assertEqual(self.row(number)[0], 1)
        self.assertEqual(calls, ["status"])
        self.fail_send = False
        # A changed author's note, a description mention, and quoted/prose commands
        # can never become gateway control traffic.
        self.todos = [self.command_todo(103, "@hermes-bot /approve")]
        self.discussions[0]["notes"][0]["author"]["id"] = 8
        await self.adapter._poll_once()
        self.assertEqual(calls, ["status"])
        for number, body in enumerate(("@hermes-bot please run /status", "@hermes-bot\n```\n/approve\n```"), 104):
            self.todos = [self.todo(number, body=body)]
            await self.adapter._poll_once()
            await self.finish_native()
        self.assertEqual(calls, ["status", None, None])

    async def test_native_approval_wait_wakes_only_after_authorized_comment(self):
        from tools import approval
        from tools.approval_gateway_wait import _await_gateway_decision
        from gateway.run_turn_runner import _renders_exec_approval_buttons
        self.assertTrue(_renders_exec_approval_buttons(type(self.adapter)))
        loop, prompted = asyncio.get_running_loop(), asyncio.Event()
        decision = []

        async def handler(event):
            key = self.adapter._event_session_key(event)

            async def show(data):
                result = await self.adapter.send_exec_approval(event.source.chat_id, data["command"], key)
                self.assertTrue(result.success)
                prompted.set()

            def notify(data):
                asyncio.run_coroutine_threadsafe(show(data), loop).result(timeout=5)

            with patch("tools.approval_context._get_approval_timeout", return_value=5):
                result = await asyncio.to_thread(_await_gateway_decision, key, notify,
                                                {"command": "test-only approval; no process is executed", "allow_session": False})
            decision.append(result)
            event._heartbeat_execution_started = True
            return "Finished"

        self.native_handler(handler)
        self.todos = [self.command_todo(101, "@hermes-bot implement", 7)]
        await self.adapter._poll_once()
        await asyncio.wait_for(prompted.wait(), 5)
        self.assertTrue(self.adapter._active_sessions)
        # Native authorization denial cannot resolve the live native wait.
        runner = SimpleNamespace(_startup_restore_in_progress=False,
                                 _profile_name_for_source=lambda *args, **kwargs: None,
                                 _hm_admit_event=AsyncMock(return_value=None))
        self.adapter.gateway_runner = runner
        self.todos.append(self.command_todo(102, "@hermes-bot /approve"))
        await self.adapter._poll_once()
        self.assertEqual(decision, [])
        runner._hm_admit_event = AsyncMock(side_effect=lambda event: (event, event.source, False))
        self.todos.append(self.command_todo(103, "@hermes-bot /approve session", 901))
        await self.adapter._poll_once()
        self.assertEqual(decision, [])
        self.assertIn("hanya jika ditawarkan", self.posts[-1][1]["body"])
        # Denial with a reason resolves the actual blocking wait, without model execution.
        self.todos.append(self.command_todo(104, "@hermes-bot /deny Jangan jalankan", 902))
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(decision[0]["choice"], "deny")
        self.assertEqual(decision[0]["reason"], "Jangan jalankan")
        self.assertTrue(decision[0]["resolved"])
        self.assertEqual(self.row(104)[0], 1)

    async def test_card_conversation_survives_different_threads_users_and_restart(self):
        store = self.session_store()
        self.adapter.allowed_users = {"*"}
        self.discussions = [{"id": "a", "notes": [{"id": 7}]}, {"id": "b", "notes": [{"id": 9}]}]
        sessions, histories = [], []

        async def handler(event):
            entry = store.get_or_create_session(event.source)
            sessions.append(entry.session_id)
            histories.append(store.load_transcript(entry.session_id))
            store.append_to_transcript(entry.session_id, {"role": "user", "content": event.text})
            store.append_to_transcript(entry.session_id, {"role": "assistant", "content": "Answer"})
            return "Answer"

        for index, anchor in enumerate((7, 9, None)):
            if index == 2:
                await self.adapter.disconnect()
                store.close_all_db_handles()
                self.adapter = await self.new_adapter()
                store = self.session_store()
            self.native_handler(handler)
            self.todos = [self.todo(101 + index, target_url=f"https://gitlab.example/#note_{anchor}" if anchor else "",
                                    body=f"@hermes-bot request {index}",
                                    author={"id": 7 + index % 2, "username": "alice"})]
            await self.adapter._poll_once()
            await self.finish_native()
        self.assertEqual(len(set(sessions)), 1)
        self.assertEqual([len(history) for history in histories], [0, 2, 4])
        self.assertEqual([post[0] for post in self.posts], [
            "/api/v4/projects/42/issues/3/discussions/a/notes",
            "/api/v4/projects/42/issues/3/discussions/b/notes",
            "/api/v4/projects/42/issues/3/discussions"])

    async def test_linked_mr_serializes_with_issue_but_replies_on_mr(self):
        store = self.session_store()
        self.related_issues = [{"project_id": 42, "iid": 3}]
        self.discussions = [{"id": "mr-thread", "notes": [{"id": 7}]}]
        sessions, histories = [], []
        release = asyncio.Event()

        async def handler(event):
            self.events.append(event)
            entry = store.get_or_create_session(event.source)
            sessions.append(entry.session_id)
            histories.append(store.load_transcript(entry.session_id))
            store.append_to_transcript(entry.session_id, {"role": "user", "content": event.text})
            await release.wait()
            return "Answer"

        self.native_handler(handler)
        self.todos = [self.todo(), self.todo(102, target_type="MergeRequest", target={"iid": 8},
                                            target_url="https://gitlab.example/#note_7")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)  # The related MR waits for the issue turn.
        release.set()
        await self.finish_native()
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(sessions[0], sessions[1])
        self.assertEqual(len(histories[1]), 1)
        self.assertIn("merge_requests #8", self.events[1].text)
        self.assertIn("worktree: workspace/42/.worktrees/42-issues-3\n", self.events[1].text)
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/merge_requests/8/discussions/mr-thread/notes")
        # A replay carries the to-do ID; a later issue turn cannot redirect its delivery.
        mr_event = self.events[1]
        self.todos = [self.todo(103)]
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertTrue((await self.adapter.send(mr_event.source.chat_id, "Resumed answer",
                                                reply_to=mr_event.message_id,
                                                metadata={"thread_id": mr_event.source.thread_id})).success)
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/merge_requests/8/discussions/mr-thread/notes")

    async def test_adopts_existing_discussion_session_and_late_mr_link(self):
        store = self.session_store()
        legacy = self.adapter.build_source("42:issues:3", chat_type="group", thread_id="discussion:old", user_id="7")
        original = store.get_or_create_session(legacy)
        store.append_to_transcript(original.session_id, {"role": "user", "content": "Remember the original decision"})
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        continued = store.get_or_create_session(self.events[-1].source)
        self.assertEqual(continued.session_id, original.session_id)
        self.assertIn("original decision", store.load_transcript(continued.session_id)[0]["content"])
        self.todos = [self.todo(102, target_type="MergeRequest", target={"iid": 8})]
        await self.adapter._poll_once()
        mr = store.get_or_create_session(self.events[-1].source)
        store.append_to_transcript(mr.session_id, {"role": "user", "content": "MR came first"})
        self.related_issues = [{"project_id": 42, "iid": 4}]
        self.todos = [self.todo(103, target_type="MergeRequest", target={"iid": 8})]
        await self.adapter._poll_once()
        linked = store.get_or_create_session(self.events[-1].source)
        self.assertEqual(linked.session_id, mr.session_id)
        self.todos = [self.todo(104, target={"iid": 4})]
        await self.adapter._poll_once()
        self.assertEqual(store.get_or_create_session(self.events[-1].source).session_id, mr.session_id)

    async def test_mr_relation_selection_is_paginated_and_never_guesses_between_issues(self):
        self.page_size = 1
        mr = dict(target_type="MergeRequest", target={"iid": 8})
        self.related_issues = [{"project_id": 42, "iid": 3}, {"project_id": 42, "iid": 4}]
        self.todos = [self.todo(101, **mr)]
        await self.adapter._poll_once()
        self.assertEqual(self.events[-1].source.chat_id, "42:merge_requests:8")
        self.closing_issues = [{"project_id": 42, "iid": 4}]
        self.todos = [self.todo(102, **mr)]
        await self.adapter._poll_once()
        self.assertEqual(self.events[-1].source.chat_id, "42:issues:4")
        self.closing_issues = [{"project_id": 999, "iid": 4}]
        self.todos = [self.todo(103, **mr)]
        await self.adapter._poll_once()
        self.assertEqual(self.events[-1].source.chat_id, "42:merge_requests:8")

    async def test_cross_repo_links_share_only_within_the_same_profile(self):
        from gateway.profile_routing import parse_profile_routes
        GatewayRunner = (await asyncio.to_thread(importlib.import_module, "gateway.run")).GatewayRunner
        for name in ("commerce", "isolated"):
            profile = Path(self.tmp.name) / "profiles" / name
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("{}")
        runner = object.__new__(GatewayRunner)
        rules = [{"name": f"hermes-gitlab-repo-{repo}", "platform": "gitlab",
                  "chat_id": f"repo:{repo}", "profile": profile}
                 for repo, profile in ((42, "commerce"), (43, "commerce"), (44, "isolated"))]
        runner.config = GatewayConfig(multiplex_profiles=True, profile_routes=parse_profile_routes(rules))
        self.adapter.gateway_runner = runner
        self.adapter.config.extra["require_profile_route"] = True
        self.adapter.projects = {"42", "43", "44"}
        self.adapter._started_at.update({repo: self.adapter._started_at["42"] for repo in ("43", "44")})
        store = SessionStore(Path(self.tmp.name) / "sessions", runner.config)
        self.addCleanup(store.close_all_db_handles)
        self.adapter.set_session_store(store)
        isolated = self.adapter._card_source("44:issues:3", {"id": 7})
        private_entry = store.get_or_create_session(isolated)
        store.append_to_transcript(private_entry.session_id, {"role": "user", "content": "Private project knowledge"})
        sessions = []
        async def handler(event):
            self.events.append(event)
            event._heartbeat_execution_started = True
            entry = store.get_or_create_session(event.source)
            sessions.append(entry.session_id)
            self.assertNotEqual(entry.session_id, private_entry.session_id)
            return "Reply in the originating repository"
        self.native_handler(handler)
        for index, related_repo in enumerate((43, 44)):
            self.related_issues = [{"project_id": related_repo, "iid": 3}]
            self.todos = [self.todo(101 + index, target_type="MergeRequest", target={"iid": 8})]
            await self.adapter._poll_once()
            await self.finish_native()
        self.assertEqual([event.source.chat_id for event in self.events], ["43:issues:3", "42:merge_requests:8"])
        self.assertIn("clone: workspace/42\n", self.events[0].text)
        self.assertIn("worktree: workspace/42/.worktrees/43-issues-3\n", self.events[0].text)
        self.assertIn('owned_repository_ids: ["42", "43"]\n', self.events[0].text)
        self.assertNotEqual(*sessions)
        self.assertTrue(all("/projects/42/merge_requests/8/discussions" in post[0] for post in self.posts))
        # Restored event routing must reject the wrong profile or an unregistered destination.
        event = self.events[0]
        self.assertFalse((await self.adapter.send(event.source.chat_id, "No leak", reply_to=event.message_id,
                                                 metadata={"thread_id": "3", "hermes_profile": "isolated"})).success)
        self.adapter.projects.remove("42")
        self.assertFalse((await self.adapter.send(event.source.chat_id, "No leak", reply_to=event.message_id,
                                                 metadata={"thread_id": "3", "hermes_profile": "commerce"})).success)
    async def test_mentions_fetch_context_and_reply_to_correct_card(self):
        self.todos = [self.todo(), self.todo(102, target_type="MergeRequest", target={"iid": 8})]
        await self.adapter._poll_once()
        self.assertEqual([event.source.chat_id for event in self.events],
                         ["42:issues:3", "42:merge_requests:8"])
        event = self.events[0]
        self.assertEqual(event.source.user_id, "7")
        self.assertIn("Login fails", event.text)
        self.assertIn("Earlier context", event.text)
        self.assertNotIn("system context", event.text)
        self.assertFalse(event.allow_gateway_control)
        self.assertIsNone(event.auto_skill)
        self.assertIn("clone: workspace/42\n", event.text)
        self.assertIn("conversation: 42:issues:3\n", event.text)
        self.assertIn("worktree: workspace/42/.worktrees/42-issues-3\n", event.text)
        self.assertIn("worktree: workspace/42/.worktrees/42-merge_requests-8\n", self.events[1].text)
        for event in self.events:
            self.assertTrue((await self.adapter.send(event.source.chat_id, "Try this fix")).success)
        self.assertEqual([post[0] for post in self.posts],
                         ["/api/v4/projects/42/issues/3/discussions", "/api/v4/projects/42/merge_requests/8/discussions"])

    def test_gitlab_tools_follow_profile_capabilities(self):
        from gateway.run import GatewayRunner

        runner = GatewayRunner.__new__(GatewayRunner)
        runner._delivery_adapter_for = lambda source: self.adapter
        self.adapter.config.extra["toolsets"] = ["web"]  # Legacy connector setting must not mask the profile menu.
        config = {"platform_toolsets": {"gitlab": ["file"]}}
        with patch("hermes_cli.config.load_config", return_value={"platform_toolsets": {"cli": ["terminal", "browser"]}}):
            self.assertEqual(runner._resolve_enabled_toolsets_for_source(config, None, "gitlab"),
                             ["browser", "terminal"])

    async def test_native_replies_follow_triggering_discussion_including_later_pages(self):
        self.discussions = [{"id": "a" * 40, "notes": [{"id": 7, "system": False}]},
                            {"id": "b" * 40, "notes": [{"id": 9, "system": False}]}]
        self.page_size = 1
        self.todos = [self.todo(target_url="https://gitlab.example/team/repo/-/issues/3#note_9"),
                      self.todo(102, target_type="MergeRequest", target={"iid": 8},
                                target_url="https://gitlab.example/team/repo/-/merge_requests/8#note_7")]
        async def handler(event):
            self.events.append(event)
            return "Reply in the original discussion"
        self.native_handler(handler)
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertCountEqual([post[0] for post in self.posts], [
            "/api/v4/projects/42/issues/3/discussions/" + "b" * 40 + "/notes",
            "/api/v4/projects/42/merge_requests/8/discussions/" + "a" * 40 + "/notes"])
        self.assertEqual(self.events[0].source.parent_chat_id, "repo:42")

    async def test_missing_discussion_never_falls_back_to_an_unrelated_comment(self):
        self.todos = [self.todo(target_url="https://gitlab.example/team/repo/-/issues/3#note_999")]
        with self.assertLogs("gitlab_adapter", level="WARNING"):
            await self.adapter._poll_once()
        self.assertEqual(self.events, [])
        self.assertEqual(self.posts, [])
        self.assertEqual(self.row()[0], 0)

    async def test_legacy_reply_recovery_and_missing_event_destination_fail_closed(self):
        self.discussions = [{"id": "old", "notes": [{"id": 7}]}]
        self.todos = [self.todo(target_url="https://gitlab.example/#note_7")]
        await self.adapter._poll_once()
        with self.adapter._db:
            self.adapter._db.execute("DELETE FROM meta WHERE key LIKE 'delivery:%'")
        result = await self.adapter.send("42:issues:3", "Resumed old reply", reply_to="todo:101",
                                         metadata={"thread_id": "discussion:old"})
        self.assertTrue(result.success)
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/issues/3/discussions/old/notes")
        self.assertFalse((await self.adapter.send("42:issues:4", "Wrong card", reply_to="todo:101")).success)
        self.assertFalse((await self.adapter.send("42:issues:3", "Unknown event", reply_to="todo:999")).success)

    async def test_setup_notices_are_hidden_but_answers_and_failures_are_delivered(self):
        home = ("📬 No home channel is set for Gitlab. A home channel is where Hermes delivers cron job results "
                "and cross-platform messages.\n\nType /sethome to make this chat your home channel, or ignore to skip.")
        compression = ("ℹ Codex gpt-5.6-terra caps context at 272K, so auto-compaction was raised to 85% (from 50%) "
                       "to use more of the window before summarizing. Opt back out: hermes config set "
                       "compression.codex_gpt55_autoraise false")
        for text in (home, compression):
            self.assertTrue((await self.adapter.send("42:issues:3", text)).success)
        self.assertEqual(self.posts, [])
        # The final answer may quote a notice when the user asks about it.
        self.assertTrue((await self.adapter.send("42:issues:3", home, metadata={"notify": True})).success)
        self.assertTrue((await self.adapter.send("42:issues:3", "Model unavailable; please retry.")).success)
        self.assertEqual(len(self.posts), 2)
        self.assertTrue(self.posts[0][0].endswith("/discussions"))
        self.assertTrue(self.posts[1][0].endswith("/discussions/" + "c" * 40 + "/notes"))
        # Unanchored follow-ups keep using the same bot discussion after a restart.
        await self.adapter.disconnect()
        self.adapter = await self.new_adapter()
        await self.adapter.send("42:issues:3", "Follow-up")
        self.assertTrue(self.posts[-1][0].endswith("/discussions/" + "c" * 40 + "/notes"))

    async def test_concurrent_unanchored_replies_create_only_one_bot_discussion(self):
        await asyncio.gather(self.adapter.send("42:issues:3", "First reply"),
                             self.adapter.send("42:issues:3", "Second reply"))
        self.assertEqual(sum(path.endswith("/discussions") for path, _ in self.posts), 1)
        self.assertEqual(len(self.posts), 2)

    async def test_working_status_edits_last_matching_note_instead_of_stacking(self):
        working = "⏳ Working — {} min — iteration {}, waiting for provider response"
        first = await self.adapter.send("42:issues:3", working.format(3, 1))
        self.assertTrue(first.success)
        self.assertTrue(self.posts[-1][0].endswith("/discussions"))
        second = await self.adapter.send("42:issues:3", working.format(6, 32))
        self.assertTrue(second.success)
        self.assertEqual(second.message_id, first.message_id)
        self.assertEqual(self.posts[-1][0], f"/api/v4/projects/42/issues/3/notes/{first.message_id}")
        self.assertEqual(self.posts[-1][1]["body"], working.format(6, 32))
        self.assertTrue((await self.adapter.send("42:issues:3", "Done.")).success)
        self.assertTrue(self.posts[-1][0].endswith("/discussions/" + "c" * 40 + "/notes"))
        later = await self.adapter.send("42:issues:3", working.format(9, 40))
        self.assertTrue(later.success)
        self.assertTrue(self.posts[-1][0].endswith("/discussions/" + "c" * 40 + "/notes"))
        self.assertNotEqual(later.message_id, first.message_id)

        self.discussions = [{"id": "status", "notes": [
            {"id": 7, "body": "@hermes-bot please help", "system": False, "author": {"id": 7}},
            {"id": 8, "body": working.format(3, 1), "system": False,
             "author": {"id": 99, "username": "hermes-bot"}},
        ]}]
        threaded = await self.adapter.send("42:issues:3", working.format(12, 32),
                                           metadata={"thread_id": "discussion:status"})
        self.assertTrue(threaded.success)
        self.assertEqual(threaded.message_id, "8")
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/issues/3/notes/8")
        self.discussions = [{"id": "foreign", "notes": [
            {"id": 9, "body": working.format(3, 1), "system": False, "author": {"id": 7}},
        ]}]
        foreign = await self.adapter.send("42:issues:3", working.format(15, 41),
                                          metadata={"thread_id": "discussion:foreign"})
        self.assertTrue(foreign.success)
        self.assertTrue(self.posts[-1][0].endswith("/discussions/foreign/notes"))

    async def test_session_wait_updates_one_status_note_then_keeps_the_answer(self):
        card = "42:issues:3"
        statuses = [
            "⏳ Another Hermes process is using this session; waiting for it to finish before starting your turn...",
            "⏳ Still waiting for the other Hermes process on this session (15s)...",
            "⏳ Still waiting for the other Hermes process on this session (31s)...",
            "Session is free; loading the latest transcript...",
        ]
        first = await self.adapter.send(card, statuses[0])
        self.assertTrue(first.success)
        for status in statuses[1:]:
            updated = await self.adapter.send(card, status)
            self.assertTrue(updated.success)
            self.assertEqual(updated.message_id, first.message_id)
            self.assertEqual(self.posts[-1],
                             (f"/api/v4/projects/42/issues/3/notes/{first.message_id}", {"body": status}))
        self.assertEqual(len(self.posted_discussions["c" * 40]), 1)
        self.assertEqual(self.posted_discussions["c" * 40][0]["body"], statuses[-1])

        answer = await self.adapter.send(card, "The issue is fixed.", metadata={"notify": True})
        self.assertTrue(answer.success)
        self.assertNotEqual(answer.message_id, first.message_id)
        self.assertEqual(len(self.posted_discussions["c" * 40]), 2)
        next_turn = await self.adapter.send(card, statuses[0])
        self.assertTrue(next_turn.success)
        self.assertNotEqual(next_turn.message_id, first.message_id)
        self.assertNotEqual(next_turn.message_id, answer.message_id)

    async def test_edit_message_updates_existing_note(self):
        result = await self.adapter.edit_message(
            "42:issues:3", "8", "⏳ Working — 12 min — iteration 32, waiting for provider response")
        self.assertTrue(result.success)
        self.assertEqual(result.message_id, "8")
        self.assertEqual(self.posts[-1][0], "/api/v4/projects/42/issues/3/notes/8")
        self.assertEqual(self.posts[-1][1]["body"],
                         "⏳ Working — 12 min — iteration 32, waiting for provider response")
        self.assertFalse((await self.adapter.edit_message("42:issues:3", "bad", "updated")).success)
        self.assertFalse((await self.adapter.edit_message("43:issues:3", "8", "updated")).success)
        await self.adapter.disconnect()
        self.assertFalse((await self.adapter.edit_message("42:issues:3", "8", "updated")).success)

    async def test_real_native_first_contact_notice_is_suppressed(self):
        runner = await self.native_runner()
        runner.session_store = object()
        runner._async_session_store = SimpleNamespace(_store=runner.session_store,
                                                      has_any_sessions=AsyncMock(return_value=True))
        runner._adapter_for_source = lambda source: self.adapter
        source = self.adapter.build_source("42:issues:3", chat_type="group", thread_id="3", user_id="7")
        await runner._hmwa_first_contact_notes(source, [], [])
        self.assertEqual(self.posts, [])

    async def test_invalid_or_system_discussion_cannot_be_used_as_reply_target(self):
        for discussion in ({"id": "../bad", "notes": [{"id": 7}]},
                           {"id": "a" * 40, "notes": [{"id": 7, "system": True}]}):
            self.discussions = [discussion]
            with self.assertRaises(ValueError):
                await self.adapter._discussion_for_todo(self.todo(target_url="https://example/#note_7"),
                                                         "projects/42/issues/3")
        self.assertFalse((await self.adapter.send("42:issues:3", "Reply", metadata={"thread_id": "discussion:../bad"})).success)
        self.assertEqual(self.posts, [])

    async def test_issue_assignment_and_direct_mentions(self):
        self.todos = [self.todo(action_name="assigned", body="Fix login"),
                      self.todo(102, action_name="directly_addressed"),
                      self.todo(103, action_name="assigned", target_type="MergeRequest")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 2)
        self.assertIn("assigned", self.events[0].text)
        self.assertEqual(self.events[0].source.chat_id, "42:issues:3")

    async def test_bot_self_assignment_starts_issue_session(self):
        bot = {"id": 99, "username": "hermes-bot"}
        self.todos = [self.todo(action_name="assigned", author=bot, body="Fix login"),
                      self.todo(102, author=bot),
                      self.todo(103, action_name="assigned", author=bot,
                                target_type="MergeRequest")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)
        self.assertIn("assigned", self.events[0].text)
        self.assertEqual(self.events[0].user_id, "99")
        self.assertEqual(self.events[0].source.chat_id, "42:issues:3")

    async def test_unauthorized_own_and_unmentioned_events_are_ignored(self):
        self.todos = [self.todo(i, **change) for i, change in enumerate((
            {"author": {"id": 99, "username": "hermes-bot"}}, {"author": {"id": 8}},
            {"project": {"id": 43}}, {"body": "@hermes-bot-extra hello"},
            {"body": "ordinary comment"}, {"action_name": "marked"},
            {"target_type": "Epic"}), 101)]
        await self.adapter._poll_once()
        self.assertEqual(self.events, [])
        self.assertTrue(all(path in {"/api/v4/user", "/api/v4/todos"} for _, path, _ in self.requests))

    async def test_allow_all_users_still_restricts_repositories_and_ignores_the_bot(self):
        await self.adapter.disconnect()
        self.config.extra["allowed_users"] = "*"
        self.adapter = await self.new_adapter()
        self.todos = [self.todo(author={"id": 8, "username": "bob"}),
                      self.todo(102, author={"id": 9}, action_name="assigned"),
                      self.todo(103, author={"id": 99}),
                      self.todo(104, author={}), self.todo(105, author={"id": "invalid"})]
        self.assertIsNone(self.adapter._trigger(self.todo(project={"id": 43}, author={"id": 8})))
        await self.adapter._poll_once()
        self.assertEqual([event.source.user_id for event in self.events], ["8", "9"])
        self.assertEqual(self.adapter.projects, {"42"})
        from gateway.authz_mixin import GatewayAuthorizationMixin
        auth = GatewayAuthorizationMixin()
        auth._adapter_for_source = lambda source: self.adapter
        auth._delivery_adapter_for = lambda source: self.adapter
        auth._adapter_profile_for_source = lambda source: None
        auth._pairing_store_for = lambda source: None
        # The real gateway accepts both YAML and environment wildcard grants.
        for value in ("", "*"):
            with patch.dict(os.environ, {"GITLAB_ALLOWED_USERS": value}):
                self.assertTrue(auth._principal_authorized(self.events[0].source, allow_adapter_delegation=False))
        # YAML and environment inputs support the same explicit wildcard.
        self.config.extra["allowed_users"] = ["*"]
        self.assertEqual(self.module.GitLabAdapter(self.config).allowed_users, {"*"})
        with self.assertRaises(ValueError):
            self.module.ids("*")  # Repository IDs must never accept a wildcard.

    async def test_restart_dedupe_and_saved_failed_context_retry(self):
        self.todos = [self.todo()]
        self.fail_context = True
        with self.assertLogs("gitlab_adapter", level="WARNING") as logs:
            await self.adapter._poll_once()
        self.assertNotIn("test-pat", " ".join(logs.output))
        self.assertEqual(self.row()[:2], (0, 1))
        path = self.adapter.state_path
        await self.adapter.disconnect()
        self.todos = []  # Saved inbox survives even if the API no longer lists the request.
        self.fail_context = False
        self.adapter = await self.new_adapter()
        await asyncio.gather(self.adapter._poll_once(), self.adapter._poll_once())
        self.assertEqual(self.adapter.state_path, path)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.row()[:2], (1, 2))
        await self.adapter.disconnect()
        self.adapter = await self.new_adapter()
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)

    async def test_first_boot_imports_old_pending_but_skips_old_done(self):
        old = "2000-01-01T00:00:00Z"
        self.todos = [self.todo(created_at=old), self.todo(102, state="done", created_at=old),
                      self.todo(103, state="done")]
        await self.adapter._poll_once()
        self.assertEqual([event.message_id for event in self.events], ["todo:101", "todo:103"])
        self.assertIsNone(self.row(102))
        # The old pending request stays durable after GitLab completes it.
        self.todos[0]["state"] = "done"
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 2)

    async def test_pending_and_done_pagination_collect_every_page(self):
        self.page_size = 1
        self.todos = [self.todo(101), self.todo(102), self.todo(103, state="done"), self.todo(104, state="done")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 4)
        pages = {(q["state"], q["page"]) for _, p, q in self.requests if p.endswith("/todos")}
        self.assertEqual(pages, {("pending", "1"), ("pending", "2"), ("done", "1"), ("done", "2")})

    async def test_global_poll_request_count_does_not_grow_with_projects(self):
        self.adapter.projects = {str(i) for i in range(1, 101)}
        self.adapter._started_at.update({p: self.adapter._started_at["42"] for p in self.adapter.projects})
        self.todos = [self.todo(101, project={"id": 1}), self.todo(102, project={"id": 100}, state="done"),
                      self.todo(103, project={"id": 999}), self.todo(104, author={"id": 8})]
        await self.adapter._poll_once()
        listings = [q for _, p, q in self.requests if p.endswith("/todos")]
        self.assertEqual(len(listings), 2)
        self.assertTrue(all("project_id" not in q for q in listings))
        self.assertEqual([e.source.parent_chat_id for e in self.events], ["repo:1", "repo:100"])
        self.assertIsNone(self.row(103))
        self.assertIsNone(self.row(104))

    async def test_done_checkpoint_overlaps_persists_and_reconciles_late_items(self):
        self.page_size = 2
        self.todos = [self.todo(i, state="done") for i in (100, 200, 300, 400, 500, 600)]
        await self.adapter._poll_once()
        self.todos += [self.todo(i, state="done") for i in (700, 800, 900)]
        await self.adapter._poll_once()
        await self.adapter.disconnect()
        self.adapter = await self.new_adapter()
        # Late completion within the overlap, plus one older than the overlap.
        self.todos += [self.todo(750, state="done"), self.todo(50, state="done")]
        self.requests.clear()
        await self.adapter._poll_once()
        self.assertEqual(self.row(750)[0], 1)
        self.assertIsNone(self.row(50))
        self.assertEqual([q["page"] for _, p, q in self.requests
                          if p.endswith("/todos") and q["state"] == "done"], ["1", "2", "3"])
        # Pending work must still be found even when its ID is much older.
        self.todos.append(self.todo(25, created_at="2000-01-01T00:00:00Z"))
        await self.adapter._poll_once()
        self.assertEqual(self.row(25)[0], 1)
        with patch.object(self.module.time, "time", return_value=self.module.time.time() + 3601):
            await self.adapter._poll_once()
        self.assertEqual(self.row(50)[0], 1)
        self.assertEqual(len(self.events), 12)  # No replay of completed inbox entries.

    async def test_failed_page_does_not_advance_done_checkpoint(self):
        self.page_size = 1
        self.todos = [self.todo(100, state="done")]
        await self.adapter._poll_once()
        checkpoint = self.adapter._db.execute("SELECT value FROM meta WHERE key = 'poll:done'").fetchone()
        self.todos += [self.todo(i, state="done") for i in (200, 300, 400)]
        self.fail_list_page = ("done", "2")
        await self.adapter._poll_once()
        self.assertEqual(self.row(400)[0], 1)  # Saved work can run despite the listing failure.
        self.assertIsNone(self.row(200))
        self.assertEqual(self.adapter._db.execute("SELECT value FROM meta WHERE key = 'poll:done'").fetchone(), checkpoint)
        await self.adapter.disconnect()
        self.adapter = await self.new_adapter()
        self.fail_list_page = None
        await self.adapter._poll_once()
        self.assertEqual([e.message_id for e in self.events], ["todo:100", "todo:400", "todo:200", "todo:300"])

    async def test_unsorted_done_page_disables_early_stop(self):
        self.page_size = 2
        self.todos = [self.todo(i, state="done") for i in (100, 200, 300, 400)]
        await self.adapter._poll_once()
        self.todos.append(self.todo(500, state="done"))
        await self.adapter._poll_once()
        self.sort_todos = False
        self.todos = [self.todo(i, state="done") for i in (100, 200, 300, 400, 500, 600)]
        await self.adapter._poll_once()
        self.assertEqual(self.row(600)[0], 1)

    async def test_full_native_pipeline_keeps_busy_card_requests_separate(self):
        entered, release = asyncio.Event(), asyncio.Event()
        handled = []

        async def agent_handler(event):
            handled.append(event.message_id)
            entered.set()
            await release.wait()
            return f"Response to {event.message_id}"

        self.native_handler(agent_handler)
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        await asyncio.wait_for(entered.wait(), 5)
        self.todos.append(self.todo(102))
        await self.adapter._poll_once()
        self.assertEqual(handled, ["todo:101"])
        self.assertEqual(self.row(102), (0, 0, None))
        release.set()
        await self.finish_native()
        self.assertEqual(self.todos[1]["state"], "done")
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(handled, ["todo:101", "todo:102"])
        self.assertEqual([post[1]["body"] for post in self.posts],
                         ["Response to todo:101", "Response to todo:102"])
        self.assertEqual(self.row(102)[0], 1)
        self.assertEqual(self.adapter._pending_messages, {})

    async def test_done_todo_created_while_agent_runs_is_not_lost(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(event):
            entered.set()
            await release.wait()
            return "Reply"

        self.native_handler(handler)
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        await asyncio.wait_for(entered.wait(), 5)
        self.todos.append(self.todo(102))  # Not polled before the first response completes it.
        release.set()
        await self.finish_native()
        self.assertEqual(self.todos[1]["state"], "done")
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.row(102)[0], 1)

    async def test_native_delivery_failure_is_retried(self):
        async def handler(event):
            return "Reply"

        self.native_handler(handler)
        self.todos = [self.todo()]
        self.fail_send = True
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(self.row()[0], 0)
        self.assertEqual(self.row()[2], "processing or delivery failed")
        self.fail_send = False
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(self.row()[:2], (1, 2))
        self.assertEqual(len(self.posts), 1)

    async def test_failed_admission_and_listing_outage_can_be_retried(self):
        async def decline(event):
            pass

        capture = self.adapter.handle_message
        self.adapter.handle_message = decline
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        self.assertEqual(self.row()[0], 0)
        self.assertFalse(self.adapter._inflight)
        self.adapter.handle_message = capture
        self.fail_list = True
        await self.adapter._poll_once()
        self.assertEqual(self.row()[0], 1)

    async def test_inflight_request_is_retried_after_shutdown(self):
        started = asyncio.Event()

        async def waiting_handler(event):
            started.set()
            await asyncio.Event().wait()

        self.native_handler(waiting_handler)
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        await asyncio.wait_for(started.wait(), 5)
        self.assertEqual(self.row()[0], 0)
        await self.adapter.disconnect()
        self.adapter = await self.new_adapter()
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.row()[0], 1)

    async def native_runner(self):
        from gateway.config import GatewayConfig
        GatewayRunner = (await asyncio.to_thread(importlib.import_module, "gateway.run")).GatewayRunner
        runner = object.__new__(GatewayRunner)
        runner.config = GatewayConfig()
        runner._profile_name_for_source = lambda *args, **kwargs: None
        self.adapter.gateway_runner = runner
        self.native_handler(runner._handle_message)
        return runner

    async def test_native_startup_restore_keeps_request_out_of_replay_queue(self):
        runner = await self.native_runner()
        runner._startup_restore_in_progress = True
        runner._queue_startup_restore_event = Mock()
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        self.assertEqual(self.row(), (0, 0, None))
        runner._queue_startup_restore_event.assert_not_called()
        self.assertEqual(self.adapter._background_tasks, set())
        self.assertEqual(self.posts, [])
        runner._startup_restore_in_progress = False
        # Native admission can also refuse silently; an early None must remain retryable.
        runner._hm_admit_event = AsyncMock(return_value=None)
        await self.adapter._poll_once()
        await self.finish_native()
        self.assertEqual(self.row()[0], 0)
        self.assertEqual(self.row()[2], "gateway did not execute request")
        runner._hm_admit_event.assert_awaited_once()

    async def test_actual_native_maintenance_and_capacity_notices_do_not_complete_request(self):
        runner = await self.native_runner()

        async def admit(event):
            return event, event.source, False

        # Keep the actual _handle_message and _claim_active_session_slot guards, while
        # removing unrelated authorization, model selection, and command dependencies.
        runner._hm_admit_event = admit
        runner._hm_estop_gate = lambda *args: None
        runner._session_key_for_source = lambda source: build_session_key(source)
        runner._hm_pending_reply_intercepts = AsyncMock(return_value=None)
        runner._hm_evict_idle_stale_agent = lambda key: None
        runner._is_session_running = lambda key: False
        runner._hm_dispatch_idle_commands = AsyncMock(return_value=(False, None))
        runner._is_telegram_topic_root_lobby = lambda source: False
        runner._get_max_concurrent_sessions = lambda: 1
        runner._running_agent_count = lambda: 1
        self.todos = [self.todo()]
        for draining in (True, False):
            runner._external_drain_active = draining
            await self.adapter._poll_once()
            await self.finish_native()
            self.assertEqual(self.row()[0], 0)
            self.assertEqual(self.row()[2], "gateway did not execute request")
            self.assertFalse(self.adapter._inflight)
        self.assertEqual(len(self.posts), 2)
        self.assertIn("maintenance", self.posts[0][1]["body"])
        self.assertIn("session", self.posts[1][1]["body"].lower())

        # Enter the real native execution boundary, with a fake failing model. A model
        # error returned AFTER execution is handled; the user can mention the bot again.
        entry = SimpleNamespace(session_id="test-session")
        runner._hmwa_resolve_session = AsyncMock(side_effect=lambda event, source: (source, entry, "test-key"))
        prepared = runner._PreparedTurn([], "", "test request", None, None, None)
        runner._hmwa_prepare_turn = AsyncMock(return_value=(prepared, None))
        runner.hooks = SimpleNamespace(emit=AsyncMock())
        runner._run_agent = AsyncMock(side_effect=RuntimeError("fake model offline"))
        runner._hmwa_agent_error_reply = AsyncMock(return_value="The model failed; mention the bot again to retry.")
        runner._clear_session_env = lambda tokens: None

        async def execute(event):
            return await runner._handle_message_with_agent(event, event.source, "test-key", 1)

        self.adapter.set_message_handler(execute)
        await self.adapter._poll_once()
        await self.finish_native()
        runner._run_agent.assert_awaited_once()
        self.assertEqual(self.row()[0], 1)
        self.assertIn("model failed", self.posts[-1][1]["body"])

    async def test_new_project_has_own_history_cutoff(self):
        self.page_size = 1
        self.todos = [self.todo(i, project={"id": 999}, state="done") for i in (1000, 2000, 3000)]
        await self.adapter._poll_once()
        self.todos.append(self.todo(4000, project={"id": 999}, state="done"))
        await self.adapter._poll_once()
        created_before_project_added = datetime.now(timezone.utc).isoformat()
        await self.adapter.disconnect()
        self.config.extra["projects"] = "42,43"
        self.adapter = await self.new_adapter()
        self.todos += [self.todo(101, project={"id": 43}),
                      self.todo(102, project={"id": 43}, state="done", created_at=created_before_project_added),
                      self.todo(103, project={"id": 43}, state="done")]
        await self.adapter._poll_once()
        self.assertEqual([event.message_id for event in self.events], ["todo:101", "todo:103"])

    async def test_card_session_is_shared_and_quick_actions_remain_text(self):
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        source = self.events[0].source
        other = copy.copy(source)
        other.user_id = "8"
        self.assertEqual(build_session_key(source), build_session_key(other))
        self.assertTrue((await self.adapter.send("42:issues:3", "Suggested command:\n  /close")).success)
        self.assertEqual(self.posts[-1][1]["body"], "Suggested command:\n  \\/close")
        self.assertFalse((await self.adapter.send("43:issues:3", "reply")).success)
        self.assertFalse((await self.adapter.send("42:issues:3", " ")).success)

    async def test_worker_cap_queues_later_cards_and_still_runs_commands(self):
        release = asyncio.Event()
        started = []

        async def handler(event):
            if event.get_command():
                return "Native status"
            started.append(event.message_id)
            await release.wait()
            return "Answer"

        self.native_handler(handler)
        self.assertEqual(self.adapter.max_workers, 5)
        self.todos = [self.todo(300 + n, target={"iid": n}) for n in range(1, 7)]
        await self.adapter._poll_once()
        for _ in range(50):
            if len(started) >= 5:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(started, [f"todo:{300 + n}" for n in range(1, 6)])
        self.assertEqual(self.row(306), (0, 0, None))
        release.set()
        for _ in range(50):
            if "todo:306" in started:
                break
            await asyncio.sleep(0.02)
        self.assertIn("todo:306", started)
        await self.finish_native()

        release = asyncio.Event()
        started.clear()
        self.adapter.max_workers = 1
        self.todos = [self.todo(401, target={"iid": 11})]
        await self.adapter._poll_once()
        for _ in range(50):
            if started:
                break
            await asyncio.sleep(0.02)
        self.todos += [self.todo(402, target={"iid": 12}),
                       self.command_todo(403, "@hermes-bot /status", target={"iid": 13})]
        await self.adapter._poll_once()
        self.assertEqual(started, ["todo:401"])
        self.assertEqual(self.row(402), (0, 0, None))
        self.assertEqual(self.row(403)[0], 1)
        release.set()
        for _ in range(50):
            if "todo:402" in started:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(started, ["todo:401", "todo:402"])
        await self.finish_native()

    async def test_configuration_and_disconnected_send_fail_cleanly(self):
        for override in ({"url": "http://gitlab.example"}, {"url": "https://bot:pat@gitlab.example"},
                         {"projects": "42,not-an-id"}, {"allowed_users": ""}, {"token": ""},
                         {"poll_interval": 0}, {"poll_interval": float("nan")},
                         {"max_workers": 0}, {"max_workers": 65}, {"max_workers": True},
                         {"max_workers": "many"}):
            with self.assertRaises(ValueError):
                self.module.GitLabAdapter(PlatformConfig(extra={**self.config.extra, **override}))
        self.assertEqual(self.adapter.poll_interval, 30)
        self.assertEqual(self.adapter.max_workers, 5)
        self.assertEqual(self.module.worker_count("5"), 5)
        self.assertEqual(self.module.GitLabAdapter(PlatformConfig(
            extra={**self.config.extra, "max_workers": 1})).max_workers, 1)
        with patch.dict(os.environ, {"GITLAB_MAX_WORKERS": "4"}):
            self.assertEqual(self.module.GitLabAdapter(PlatformConfig(
                extra={**self.config.extra, "max_workers": 1})).max_workers, 4)
        await self.adapter.disconnect()
        self.assertFalse((await self.adapter.send("42:issues:3", "reply")).success)

    async def test_second_connection_with_same_state_fails_then_releases_lock(self):
        other = self.module.GitLabAdapter(self.config)
        self.addAsyncCleanup(other.disconnect)
        with self.assertLogs("gitlab_adapter", level="ERROR"):
            self.assertFalse(await other.connect())
        self.assertIsNone(other._client)
        await self.adapter.disconnect()
        self.assertTrue(await other.connect())

    async def test_background_poll_starts_on_connect(self):
        await self.adapter.disconnect()
        self.todos = [self.todo()]
        self.adapter = self.module.GitLabAdapter(self.config)
        self.addAsyncCleanup(self.adapter.disconnect)
        finished = asyncio.Event()

        async def handler(event):
            finished.set()
            return "Automatic poll reply"

        self.adapter.set_message_handler(handler)
        self.assertTrue(await self.adapter.connect())
        await asyncio.wait_for(finished.wait(), 5)
        await self.finish_native()
        self.assertEqual(self.posts[0][1]["body"], "Automatic poll reply")

    async def test_multiplex_routes_and_rejects_missing_catchall_or_unavailable_routes(self):
        from gateway.config import GatewayConfig
        from gateway.profile_routing import parse_profile_routes
        GatewayRunner = (await asyncio.to_thread(importlib.import_module, "gateway.run")).GatewayRunner

        profile = Path(self.tmp.name) / "profiles" / "commerce"
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text("{}")
        runner = object.__new__(GatewayRunner)
        exact = {"name": "hermes-gitlab-repo-42", "platform": "gitlab",
                 "chat_id": "repo:42", "profile": "commerce"}
        runner.config = GatewayConfig(multiplex_profiles=True, profile_routes=parse_profile_routes([exact]))
        self.adapter.gateway_runner = runner
        self.adapter.config.extra["require_profile_route"] = True
        self.todos = [self.todo()]
        await self.adapter._poll_once()
        source = self.events[0].source
        self.assertEqual(source.profile, "commerce")
        self.assertEqual(source.parent_chat_id, "repo:42")
        self.assertTrue(build_session_key(source, profile=source.profile).startswith("agent:commerce:"))
        self.todos = [self.todo(102)]
        for rules in ([], [{"platform": "gitlab", "profile": "commerce"}],
                      [{**exact, "profile": "absent"}], [{**exact, "profile": "default"}]):
            runner.config.profile_routes = parse_profile_routes(rules)
            await self.adapter._poll_once()
            self.assertEqual(self.row(102)[0], 0)
            self.assertEqual(len(self.events), 1)
        runner.config.profile_routes = parse_profile_routes([exact])
        await self.adapter._poll_once()
        self.assertEqual(self.row(102)[0], 1)

    async def test_managed_project_list_overrides_environment_and_can_be_empty(self):
        from gateway.config import GatewayConfig, Platform
        from gateway.config_env import _enable_plugin_platform
        from gateway.platform_registry import platform_registry

        config = GatewayConfig(platforms={Platform("gitlab"): PlatformConfig(extra={
            **self.config.extra, "require_profile_route": True,
        })})
        with patch.dict(os.environ, {"GITLAB_PROJECTS": "999", "GITLAB_TOKEN": "test-pat"}):
            _enable_plugin_platform(config, platform_registry.get("gitlab"))
            managed = self.module.GitLabAdapter(config.platforms[Platform("gitlab")])
            self.assertEqual(managed.projects, {"42"})
            config.platforms[Platform("gitlab")].extra["projects"] = []
            managed = self.module.GitLabAdapter(config.platforms[Platform("gitlab")])
        self.assertEqual(managed.projects, set())

    async def test_malformed_inputs_do_not_dispatch(self):
        for payload in ([], {"project": []}, self.todo(target="bad"),
                        self.todo(body=[]), self.todo(target={"iid": "../1"}), self.todo(id="oops")):
            with self.assertRaises(ValueError):
                self.adapter._trigger(payload)
        self.assertIsNone(self.adapter._trigger({}))
        self.todos = [self.todo(id="oops"), self.todo()]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)

    def balancer(self, verdict="complex"):
        self.adapter.balancer = self.module.balancer_config({
            "tiers": {"trivial": {"reasoning": "low", "description": "typo or one-line fix"},
                      "standard": {"reasoning": "medium"},
                      "complex": {"model": "gpt-6-sol-pro", "provider": "openai-codex",
                                  "reasoning": "high", "description": "design or multi-file change"}},
            "default_tier": "standard"})
        judge = AsyncMock(return_value=SimpleNamespace(parsed={"tier": verdict}))
        self.module.PLUGIN_LLM = SimpleNamespace(acomplete_structured=judge)
        self.addCleanup(setattr, self.module, "PLUGIN_LLM", None)
        reasoning, states = [], {}
        self.adapter.gateway_runner = SimpleNamespace(
            _startup_restore_in_progress=False, _profile_name_for_source=lambda *args, **kwargs: None,
            _set_session_reasoning_override=lambda key, value: reasoning.append((key, value)),
            _peek_session_state=states.get)
        return judge, reasoning, states

    async def test_model_balancer_judges_assignment_and_pins_the_card_model(self):
        store = self.session_store()
        self.assertIsNone(self.adapter.balancer)
        judge, reasoning, states = self.balancer("complex")
        self.todos = [self.todo(action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)
        key = self.adapter._event_session_key(self.events[0])
        self.assertEqual(store.get_model_override(key), {"model": "gpt-6-sol-pro", "provider": "openai-codex"})
        self.assertEqual(reasoning, [(key, {"enabled": True, "effort": "high"})])
        kwargs = judge.await_args.kwargs
        self.assertEqual(kwargs["task"], "hermes_gitlab_complexity")
        self.assertEqual(kwargs["json_schema"]["properties"]["tier"]["enum"], ["trivial", "standard", "complex"])
        self.assertIn("typo or one-line fix", kwargs["instructions"])
        self.assertTrue(kwargs["input"][0]["text"].startswith("Title: "))
        self.assertEqual(self.row()[0], 1)
        # A long follow-up is judged again, but only its reasoning effort changes.
        states[key] = SimpleNamespace(conversation=SimpleNamespace(
            reasoning_override=reasoning[-1][1], model_override=dict(store.get_model_override(key))))
        judge.return_value = SimpleNamespace(parsed={"tier": "trivial"})
        self.todos = [self.todo(102, body="@hermes-bot " + "tolong cek stack trace ini " * 12)]
        await self.adapter._poll_once()
        self.assertEqual(judge.await_count, 2)
        self.assertIn("latest request", judge.await_args.kwargs["instructions"])
        self.assertEqual(store.get_model_override(key), {"model": "gpt-6-sol-pro", "provider": "openai-codex"})
        self.assertEqual(states[key].conversation.model_override, {"model": "gpt-6-sol-pro", "provider": "openai-codex"})
        self.assertEqual(reasoning[-1], (key, {"enabled": True, "effort": "low"}))
        # A short follow-up keeps the current effort without a judge call.
        self.todos = [self.todo(103, body="@hermes-bot ok, lanjut")]
        await self.adapter._poll_once()
        self.assertEqual(judge.await_count, 2)
        self.assertEqual(len(reasoning), 2)
        # A later assignment re-judges the model once and forces the gateway to rehydrate it.
        states[key].conversation.reasoning_override = reasoning[-1][1]
        judge.return_value = SimpleNamespace(parsed={"tier": "standard"})
        self.todos = [self.todo(104, action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertIsNone(store.get_model_override(key))
        self.assertIsNone(states[key].conversation.model_override)
        self.assertEqual(reasoning[-1], (key, {"enabled": True, "effort": "medium"}))
        self.assertEqual(len(self.events), 4)
        # A cleared override (/new) is not a human choice: the next assignment pins again.
        judge.return_value = SimpleNamespace(parsed={"tier": "complex"})
        self.todos = [self.todo(105, action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(store.get_model_override(key), {"model": "gpt-6-sol-pro", "provider": "openai-codex"})
        store.set_model_override(key, None)
        states[key].conversation.reasoning_override = None
        self.todos = [self.todo(106, action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(store.get_model_override(key), {"model": "gpt-6-sol-pro", "provider": "openai-codex"})
        self.assertEqual(len(self.events), 6)

    async def test_model_balancer_leaves_human_model_and_reasoning_choices_alone(self):
        store = self.session_store()
        judge, reasoning, states = self.balancer("complex")
        source = self.adapter._card_source("42:issues:3", {"id": 7, "username": "alice"})
        store.get_or_create_session(source)
        key = self.adapter._source_session_key(source)
        store.set_model_override(key, {"model": "human-pick", "provider": "openai-codex"})
        states[key] = SimpleNamespace(conversation=SimpleNamespace(
            reasoning_override={"enabled": True, "effort": "low"}, model_override=None))
        self.todos = [self.todo(action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(judge.await_count, 1)
        self.assertEqual(store.get_model_override(key), {"model": "human-pick", "provider": "openai-codex"})
        self.assertEqual(reasoning, [])

    async def test_model_balancer_failure_keeps_the_card_on_its_current_model(self):
        store = self.session_store()
        judge, reasoning, _ = self.balancer()
        judge.side_effect = TimeoutError("judge timeout")
        self.todos = [self.todo(action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 1)
        self.assertIsNone(store.get_model_override(self.adapter._event_session_key(self.events[0])))
        self.assertEqual(reasoning, [])
        self.assertEqual(self.row()[0], 1)
        # An unusable verdict falls back to default_tier.
        judge.side_effect = None
        judge.return_value = SimpleNamespace(parsed={"tier": "bogus"})
        self.todos = [self.todo(102, action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(reasoning, [(self.adapter._event_session_key(self.events[1]),
                                      {"enabled": True, "effort": "medium"})])
        # Without the host LLM facade the balancer stays inert.
        self.module.PLUGIN_LLM = None
        self.todos = [self.todo(103, action_name="assigned", body="")]
        await self.adapter._poll_once()
        self.assertEqual(len(self.events), 3)
        self.assertEqual(judge.await_count, 2)

    def test_model_balancer_config_validation(self):
        config = self.module.balancer_config
        self.assertIsNone(config(None))
        self.assertIsNone(config({"enabled": False, "tiers": {"a": {}}}))
        good = config({"tiers": {"fast": {"reasoning": "LOW"}, "deep": {"model": " m ", "provider": "p"}},
                       "default_tier": "fast", "judge_timeout": 5, "follow_up_min_chars": 0})
        self.assertEqual(good, {"tiers": {"fast": {"reasoning": "low"}, "deep": {"model": "m", "provider": "p"}},
                                "default_tier": "fast", "judge_timeout": 5.0, "follow_up_min_chars": 0})
        self.assertIsNone(config({"tiers": {"a": None}})["default_tier"])
        for bad in ("x", {"tiers": {}}, {"tiers": {"Bad Name": {}}}, {"tiers": {"a": "fast"}},
                    {"tiers": {"a": {"reasoning": "huge"}}}, {"tiers": {"a": {"model": ""}}},
                    {"tiers": {"a": {"provider": "p"}}}, {"tiers": {"a": {}}, "default_tier": "b"},
                    {"tiers": {"a": {}}, "judge_timeout": 0}, {"tiers": {"a": {}}, "follow_up_min_chars": -1}):
            with self.assertRaises(ValueError):
                config(bad)


if __name__ == "__main__":
    unittest.main()
