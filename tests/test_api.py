"""Real Hermes API mounting/auth, temporary profiles and a loopback GitLab."""
import contextlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi.testclient import TestClient
import yaml


class DesktopAPI(unittest.TestCase):
    def test_authenticated_mapping_and_repository_flow(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.dict(os.environ, {"HERMES_HOME": directory,
                "GATEWAY_MULTIPLEX_PROFILES": "", "GITLAB_URL": "", "GITLAB_TOKEN": ""}))
            for name in ("seed_profile_skills", "_notify_multiplexer", "_maybe_register_gateway_service"):
                stack.enter_context(patch("hermes_cli.profiles." + name))
            for name in ("_cleanup_gateway_service", "_maybe_unregister_gateway_service", "_stop_profile_backends"):
                stack.enter_context(patch("hermes_cli.profiles." + name))
            stack.enter_context(patch("hermes_cli.profiles._check_gateway_running", return_value=False))
            stack.enter_context(patch("hermes_cli.profiles._get_wrapper_dir", return_value=root / "bin"))
            calls = []

            class GitLab(BaseHTTPRequestHandler):
                def do_GET(self):
                    calls.append((self.path, self.headers.get("PRIVATE-TOKEN")))
                    row = {"id": 42, "path_with_namespace": "team/payments"}
                    data = [row] if self.path.startswith("/api/v4/projects?") else row
                    if self.path.startswith("/api/v4/projects/404"):
                        self.send_response(404)
                    else:
                        self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), GitLab)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.server_close)
            stack.callback(server.shutdown)
            url = f"http://127.0.0.1:{server.server_port}"
            (root / ".env").write_text("GITLAB_TOKEN=test-bot-pat\n")
            config = {"plugins": {"enabled": ["hermes-gitlab"]}, "gateway": {"multiplex_profiles": True},
                      "model": {"default": "gpt-5.6-terra", "provider": "openai-codex"},
                      "platforms": {"gitlab": {"extra": {"url": url, "allowed_users": [7]}}}}
            config_path = root / "config.yaml"
            config_path.write_text(yaml.safe_dump(config))
            personal = root / "profiles" / "personal"
            personal.mkdir(parents=True)
            (personal / "config.yaml").write_text("{}")
            (personal / "profile.yaml").write_text("description: Personal assistant\ndisplay_name: My assistant\n")
            # Native root login fallback must work without duplicating OAuth tokens.
            auth_path = root / "auth.json"
            auth_path.write_text(json.dumps({"version": 1, "providers": {}, "credential_pool": {
                "openai-codex": [{"id": "test-login", "access_token": "fixture-access", "refresh_token": "fixture-refresh"}]}}))
            auth_before = auth_path.read_bytes()
            (root / "plugins").mkdir()
            (root / "plugins" / "hermes-gitlab").symlink_to(Path(__file__).parents[1], target_is_directory=True)

            # Exercise native discovery, import, namespace mounting, token middleware,
            # and the live enabled-plugin gate, not a test-only FastAPI router.
            host = importlib.import_module("hermes_cli.web_server")
            restart = stack.enter_context(patch.object(host, "_spawn_gateway_restart",
                return_value=(SimpleNamespace(pid=12345), False)))
            client = TestClient(host.app)
            stack.callback(client.close)
            base = "/api/plugins/hermes-gitlab"
            self.assertEqual(client.get(base + "/projects").status_code, 401)
            self.assertEqual(client.get(base + "/events").status_code, 401)
            self.assertEqual(client.get(base + "/sessions").status_code, 401)
            self.assertEqual(client.get(base + "/activity?year=2026&month=9").status_code, 401)
            self.assertEqual(client.put(base + "/projects/commerce", json={}).status_code, 401)
            self.assertEqual(client.request("DELETE", base + "/projects/commerce", json={}).status_code, 401)
            self.assertEqual(client.post(base + "/gateway/restart").status_code, 401)
            client.headers["Authorization"] = "Bearer " + host._SESSION_TOKEN
            self.assertEqual(client.get(base + "/subscription").status_code, 404)
            response = client.get(base + "/projects")
            self.assertEqual(response.status_code, 200, response.text)
            state = response.json()
            self.assertEqual(state["projects"], [], "Unmarked personal profiles are not GitLab projects")
            # The native plugin scope must not treat the project path as an existing profile selector.
            config["gateway"]["profile_routes"] = [{"name": "hermes-gitlab-repo-42", "platform": "gitlab",
                                                   "chat_id": "repo:42", "profile": "missing"}]
            config["platforms"]["gitlab"]["extra"]["projects"] = ["42"]
            config_path.write_text(yaml.safe_dump(config))
            state = client.get(base + "/projects").json()
            response = client.request("DELETE", base + "/projects/missing", json={
                "revision": state["revision"], "confirmation": "missing"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["profile_delete_required"])
            self.assertFalse((root / "profiles" / "missing").exists())
            self.assertEqual(yaml.safe_load(config_path.read_text())["platforms"]["gitlab"]["extra"]["projects"], [])
            state = client.get(base + "/projects").json()
            self.assertEqual(state["projects"], [])
            response = client.request("DELETE", base + "/projects/personal", json={
                "revision": state["revision"], "confirmation": "personal"})
            self.assertEqual(response.status_code, 409)
            response = client.put(base + "/projects/personal", json={"repositories": [], "revision": state["revision"]})
            self.assertEqual(response.status_code, 409, "New project must not silently adopt an unrelated profile")
            self.assertTrue(personal.is_dir())
            self.assertTrue(state["connection_configured"])
            self.assertEqual(state["transport"], "polling")
            self.assertEqual(state["max_workers"], 5)
            (root / ".env").write_text("GITLAB_TOKEN=test-bot-pat\nGITLAB_MAX_WORKERS=4\n")
            self.assertEqual(client.get(base + "/projects").json()["max_workers"], 4)
            from hermes_cli.config import OPTIONAL_ENV_VARS, _inject_platform_plugin_env_vars
            from hermes_cli.web_server_messaging import _discover_platform_env_vars
            _inject_platform_plugin_env_vars()
            self.assertEqual(OPTIONAL_ENV_VARS["GITLAB_MAX_WORKERS"]["prompt"], "Concurrent workers")
            self.assertFalse(OPTIONAL_ENV_VARS["GITLAB_MAX_WORKERS"]["password"])
            self.assertIn("GITLAB_MAX_WORKERS", _discover_platform_env_vars("gitlab"))
            (root / ".env").write_text("GITLAB_TOKEN=test-bot-pat\n")
            self.assertEqual(state["open_count"], 0)
            self.assertEqual(client.get(base + "/events").json(), {"events": [], "next_page": None, "open_count": 0})
            self.assertEqual(client.get(base + "/sessions").json(),
                             {"sessions": [], "next_page": None, "session_count": 0, "cost_usd": 0.0,
                              "cost_status": None, "input_tokens": 0, "output_tokens": 0})
            self.assertNotIn("test-bot-pat", response.text)
            # A Desktop backend may have been launched in another profile. A
            # missing default PAT must not fall back to that process's credentials.
            (root / ".env").write_text("")
            with patch.dict(os.environ, {"GITLAB_TOKEN": "other-profile-token"}):
                self.assertFalse(client.get(base + "/projects").json()["connection_configured"])
                self.assertEqual(client.get(base + "/repositories").status_code, 409)
            # Neither URL nor PAT may be borrowed from the launch profile.
            before = config_path.read_bytes()
            config["platforms"]["gitlab"]["extra"].pop("url")
            config_path.write_text(yaml.safe_dump(config))
            with patch.dict(os.environ, {"GITLAB_URL": url, "GITLAB_TOKEN": "other-profile-token"}):
                request_count = len(calls)
                self.assertFalse(client.get(base + "/projects").json()["connection_configured"])
                self.assertEqual(client.get(base + "/repositories").status_code, 409)
                self.assertEqual(len(calls), request_count)
                from agent.secret_scope import current_secret_scope, set_secret_scope, reset_secret_scope
                from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
                api = importlib.import_module("hermes_dashboard_plugin_hermes-gitlab")
                other_scope = {"GITLAB_TOKEN": "other-profile-token"}
                scope_token = set_secret_scope(other_scope)
                home_token = set_hermes_home_override(personal)
                try:
                    with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                        with api.root_scope():
                            self.assertEqual(get_hermes_home(), root)
                            self.assertEqual(current_secret_scope()["GITLAB_TOKEN"], "")
                            self.assertEqual(current_secret_scope()["GITLAB_URL"], "")
                            raise RuntimeError("fixture failure")
                    self.assertIs(current_secret_scope(), other_scope)
                    self.assertEqual(get_hermes_home(), personal)
                    self.assertEqual(os.environ["GITLAB_TOKEN"], "other-profile-token")
                finally:
                    reset_secret_scope(scope_token)
                    reset_hermes_home_override(home_token)
            config["platforms"]["gitlab"]["extra"]["url"] = url
            config_path.write_bytes(before)
            (root / ".env").write_text("GITLAB_TOKEN=test-bot-pat\n")
            response = client.get(base + "/repositories?q=pay&page=1")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["repositories"][0]["name"], "team/payments")
            self.assertEqual(calls[-1][1], "test-bot-pat")
            body = {"repositories": ["42"], "revision": state["revision"], "description": "Commerce knowledge"}
            response = client.put(base + "/projects/commerce", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["created"])
            self.assertTrue(response.json()["restart_started"])
            self.assertEqual(response.json()["model_setup"],
                             {"model": "gpt-6-sol", "provider": "openai-codex"})
            restart.assert_called_once_with("default")
            profile = root / "profiles" / "commerce"
            self.assertTrue((profile / "config.yaml").exists())
            self.assertEqual(yaml.safe_load((profile / "config.yaml").read_text())["model"],
                             {"default": "gpt-6-sol", "provider": "openai-codex"})
            self.assertNotIn("test-bot-pat", (profile / ".env").read_text())
            from hermes_constants import set_hermes_home_override, reset_hermes_home_override
            from hermes_cli.auth import read_credential_pool
            home = set_hermes_home_override(profile)
            try:
                self.assertEqual(read_credential_pool("openai-codex")[0]["id"], "test-login")
            finally:
                reset_hermes_home_override(home)
            self.assertEqual(auth_path.read_bytes(), auth_before)
            self.assertFalse((profile / "auth.json").exists())
            self.assertNotIn("fixture-access", response.text)
            self.assertNotIn("fixture-refresh", response.text)
            self.assertEqual(client.put(base + "/projects/commerce", json=body).status_code, 409)
            state = client.get(base + "/projects").json()
            self.assertEqual([p["profile"] for p in state["projects"]], ["commerce"])
            self.assertEqual(state["projects"][0]["profile_type"], "project")
            self.assertIs(yaml.safe_load((profile / "profile.yaml").read_text())["hermes_gitlab_project"], True)
            self.assertEqual(state["projects"][0]["repositories"][0]["name"], "team/payments")
            self.assertEqual(state["projects"][0]["description"], "Commerce knowledge")
            self.assertIsNone(state["projects"][0]["last_event"])
            inbox = root / "gitlab"
            inbox.mkdir()
            database = sqlite3.connect(inbox / "state.sqlite3")
            with database:
                database.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                database.execute("""CREATE TABLE inbox (
                    id INTEGER PRIMARY KEY, payload TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)""")
                mention = {"id": 101, "project": {"id": 42, "path_with_namespace": "team/payments"},
                           "author": {"id": 7, "username": "alice"}, "action_name": "mentioned",
                           "target_type": "Issue", "target": {"iid": 3, "title": "Fix login"},
                           "body": "@hermes-bot please help", "created_at": "2026-09-16T10:12:00Z"}
                assigned = {"id": 102, "project": {"id": 42, "path_with_namespace": "team/payments"},
                            "author": {"id": 7, "username": "mei"}, "action_name": "assigned",
                            "target_type": "Issue", "target": {"iid": 8, "title": "Export invoices"},
                            "body": "assigned", "created_at": "2026-09-16T09:00:00Z"}
                command = {"id": 103, "project": {"id": 42, "path_with_namespace": "team/payments"},
                           "author": {"id": 7, "username": "alice"}, "action_name": "mentioned",
                           "target_type": "Issue", "target": {"iid": 3, "title": "Fix login"},
                           "body": "@hermes-bot /status", "created_at": "2026-09-16T08:00:00Z"}
                database.execute("INSERT INTO inbox VALUES (101, ?, 1, 1, NULL)", (json.dumps(mention),))
                database.execute("INSERT INTO inbox VALUES (102, ?, 0, 0, NULL)", (json.dumps(assigned),))
                database.execute("INSERT INTO inbox VALUES (103, ?, 0, 2, 'context or dispatch failed')",
                                 (json.dumps(command),))
                database.execute("INSERT INTO meta VALUES ('delivery:todo:101', ?)", (json.dumps({
                    "card": "42:issues:3", "discussion": "abc", "conversation": "42:issues:3",
                    "profile": "commerce"}),))
            database.close()
            listed = client.get(base + "/events").json()
            self.assertEqual([event["id"] for event in listed["events"]], ["103", "102", "101"])
            self.assertEqual(listed["open_count"], 2)
            self.assertEqual(listed["events"][0]["status"], "retrying")
            self.assertEqual(listed["events"][0]["kind"], "/status")
            self.assertEqual(listed["events"][0]["command"], "/status")
            self.assertEqual(listed["events"][1]["status"], "pending")
            self.assertEqual(listed["events"][1]["kind"], "assignment")
            self.assertEqual(listed["events"][2]["status"], "delivered")
            self.assertEqual(listed["events"][2]["profile"], "commerce")
            self.assertEqual(listed["events"][2]["discussion"], "abc")
            self.assertNotIn("test-bot-pat", json.dumps(listed))
            self.assertEqual(len(client.get(base + "/events?status=open").json()["events"]), 2)
            self.assertEqual(client.get(base + "/events?q=invoices").json()["events"][0]["id"], "102")
            self.assertEqual(client.get(base + "/events?profile=personal").json()["events"], [])
            self.assertEqual(client.get(base + "/events?profile=missing").status_code, 404)
            state_db = sqlite3.connect(profile / "state.db")
            with state_db:
                state_db.execute("DROP TABLE IF EXISTS sessions")
                state_db.execute("""CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, source TEXT, title TEXT, chat_id TEXT, origin_json TEXT,
                    profile_name TEXT, model TEXT, actual_cost_usd REAL, estimated_cost_usd REAL,
                    cost_status TEXT, input_tokens INTEGER, output_tokens INTEGER, message_count INTEGER,
                    started_at REAL, last_activity_at REAL, ended_at REAL, archived INTEGER, hidden INTEGER)""")
                origin = json.dumps({"platform": "gitlab", "chat_id": "42:issues:3", "user_name": "alice",
                                     "parent_chat_id": "repo:42", "profile": "commerce"})
                state_db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("sess-paid", "gitlab", "Fix login rounding", "42:issues:3", origin, "commerce",
                     "gpt-5.6-terra", 0.12, 0.15, None, 1000, 200, 4,
                     datetime(2026, 8, 30, tzinfo=timezone.utc).timestamp(),
                     datetime(2026, 9, 16, 11, tzinfo=timezone.utc).timestamp(), None, 0, 0))
                state_db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("sess-included", "gitlab", "Export invoices", "42:issues:8",
                     origin.replace("issues:3", "issues:8"), "commerce", "gpt-5.6-terra", 0.0, 0.0, "included",
                     500, 40, 2, 1789481000.0, 1789481100.0, None, 0, 0))
                state_db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("sess-desktop", "desktop", "Local notes", None, None, "commerce", "gpt-5.6-terra",
                     1.5, 1.5, None, 10, 10, 1, 1789483000.0, 1789483000.0, None, 0, 0))
                state_db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("sess-hidden", "gitlab", "Hidden", "42:issues:9", origin, "commerce", "gpt-5.6-terra",
                     9.0, 9.0, None, 10, 10, 1, 1789484000.0, 1789484000.0, None, 0, 1))
                state_db.execute("CREATE TABLE messages (session_id TEXT, role TEXT, timestamp REAL)")
                day_aug = datetime(2026, 8, 31, 10, tzinfo=timezone.utc).timestamp()
                day_15 = datetime(2026, 9, 15, 14, tzinfo=timezone.utc).timestamp()
                day_16 = datetime(2026, 9, 16, 10, tzinfo=timezone.utc).timestamp()
                late_15 = datetime(2026, 9, 15, 23, tzinfo=timezone.utc).timestamp()
                state_db.executemany("INSERT INTO messages VALUES (?,?,?)", [
                    ("sess-paid", "assistant", day_aug),
                    ("sess-paid", "assistant", day_15),
                    ("sess-paid", "assistant", day_15),  # copied message after compaction
                    ("sess-paid", "assistant", day_16),
                    ("sess-included", "assistant", late_15),
                    ("sess-desktop", "assistant", day_16),
                    ("sess-hidden", "assistant", day_16),
                ])
            state_db.close()
            listed_sessions = client.get(base + "/sessions").json()
            self.assertEqual([session["id"] for session in listed_sessions["sessions"]], ["sess-paid", "sess-included"])
            self.assertEqual(listed_sessions["session_count"], 2)
            self.assertEqual((listed_sessions["input_tokens"], listed_sessions["output_tokens"]), (1500, 240))
            self.assertAlmostEqual(listed_sessions["cost_usd"], 0.12185, places=5)
            self.assertEqual(listed_sessions["cost_status"], "estimated")
            self.assertEqual(listed_sessions["sessions"][0]["cost_usd"], 0.12)
            self.assertEqual(listed_sessions["sessions"][0]["profile"], "commerce")
            self.assertEqual(listed_sessions["sessions"][0]["repository"]["id"], "42")
            self.assertEqual(listed_sessions["sessions"][0]["repository"]["name"], "team/payments")
            self.assertEqual(listed_sessions["sessions"][0]["card"], "42:issues:3")
            self.assertEqual(listed_sessions["sessions"][1]["cost_status"], "included")
            self.assertAlmostEqual(listed_sessions["sessions"][1]["cost_usd"], 0.00185, places=5)
            self.assertEqual(client.get(base + "/sessions?q=invoices").json()["sessions"][0]["id"], "sess-included")
            self.assertEqual(client.get(base + "/sessions?profile=personal").json()["sessions"], [])
            self.assertEqual(client.get(base + "/sessions?profile=missing").status_code, 404)
            activity = client.get(base + "/activity?year=2026&month=9").json()
            self.assertEqual([(day["date"], day["responses"]) for day in activity["days"]],
                             [("2026-09-15", 2), ("2026-09-16", 1)])
            self.assertAlmostEqual(activity["days"][0]["cost_usd"], 0.04185, places=5)
            self.assertAlmostEqual(activity["days"][1]["cost_usd"], 0.04, places=5)
            local_days = client.get(base + "/activity?year=2026&month=9&timezone=Asia/Jakarta").json()["days"]
            self.assertEqual([(day["date"], day["responses"]) for day in local_days],
                             [("2026-09-15", 1), ("2026-09-16", 2)])
            self.assertAlmostEqual(local_days[1]["cost_usd"], 0.04185, places=5)
            self.assertEqual(client.get(base + "/activity?year=2026&month=8").json()["days"],
                             [{"date": "2026-08-31", "responses": 1, "cost_usd": 0.04}])
            annual = client.get(base + "/activity?year=2026").json()["days"]
            self.assertEqual([(day["date"], day["responses"]) for day in annual],
                             [("2026-08-31", 1), ("2026-09-15", 2), ("2026-09-16", 1)])
            self.assertEqual(client.get(base + "/activity?year=2026&month=13").status_code, 422)
            self.assertEqual(client.get(base + "/activity?year=2026&month=9&timezone=Not/AZone").status_code, 422)
            state = client.get(base + "/projects").json()
            self.assertEqual(state["session_count"], 2)
            self.assertEqual(state["projects"][0]["last_session"]["id"], "sess-paid")
            self.assertEqual(state["projects"][0]["last_session"]["cost_usd"], 0.12)
            self.assertAlmostEqual(state["projects"][0]["cost_usd"], 0.12185, places=5)
            self.assertEqual((state["projects"][0]["input_tokens"], state["projects"][0]["output_tokens"]), (1500, 240))
            self.assertEqual(state["projects"][0]["cost_status"], "estimated")
            self.assertEqual(state["open_count"], 2)
            self.assertEqual(state["projects"][0]["last_event"]["id"], "103")
            self.assertEqual(state["projects"][0]["last_event"]["status"], "retrying")
            response = client.put(base + "/projects/finance", json={**body, "revision": state["revision"]})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertFalse((root / "profiles" / "finance").exists())
            response = client.put(base + "/projects/bad-access", json={**body, "repositories": ["404"], "revision": state["revision"]})
            self.assertEqual(response.status_code, 502)
            self.assertFalse((root / "profiles" / "bad-access").exists())
            self.assertEqual(restart.call_count, 1, "Failed saves must not restart the gateway")
            # A restart failure must not turn a successful registration into a failed save.
            # Existing per-project model settings must also survive a registration edit.
            (profile / "config.yaml").write_text("model:\n  default: local-model\n  provider: custom\n")
            metadata = yaml.safe_load((profile / "profile.yaml").read_text())
            metadata.pop("hermes_gitlab_project")
            (profile / "profile.yaml").write_text(yaml.safe_dump(metadata))
            self.assertEqual([p["profile"] for p in client.get(base + "/projects").json()["projects"]], ["commerce"],
                             "Managed legacy registrations remain visible before their next save")
            restart.side_effect = RuntimeError("Sensitive process detail must not reach the page")
            response = client.put(base + "/projects/commerce", json={"repositories": [], "revision": state["revision"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["restart_started"])
            self.assertNotIn("Sensitive process", response.text)
            self.assertEqual(response.json()["model_setup"], {"model": "local-model", "provider": "custom"})
            self.assertTrue((profile / "config.yaml").exists())
            self.assertEqual(client.get(base + "/projects").json()["projects"][0]["repositories"], [])
            restart.side_effect = None
            self.assertTrue(client.post(base + "/gateway/restart").json()["restart_started"])
            started = time.monotonic()
            def after_cooldown(profile):
                self.assertEqual(profile, "default")
                self.assertGreaterEqual(time.monotonic() - started, 0.05)
                return SimpleNamespace(pid=12345), False
            with patch.object(host, "_LAST_GATEWAY_RESTART", (started, SimpleNamespace(pid=1), ())), \
                    patch.object(host, "GATEWAY_RESTART_COOLDOWN_SECONDS", 0.05):
                restart.side_effect = after_cooldown
                self.assertTrue(client.post(base + "/gateway/restart").json()["restart_started"])
            restart.side_effect = None
            with patch("hermes_cli.web_routers.actions.get_action_status", return_value={
                    "running": False, "exit_code": 1, "pid": 12345, "lines": ["private log"]}):
                self.assertEqual(client.get(base + "/gateway/restart/status?pid=12345").json(), {"status": "failed"})
                self.assertEqual(client.get(base + "/gateway/restart/status?pid=54321").json(), {"status": "unknown"})
            state = client.get(base + "/projects").json()
            response = client.put(base + "/projects/commerce", json={**body, "revision": state["revision"]})
            self.assertEqual(response.status_code, 200, response.text)
            state = client.get(base + "/projects").json()
            delete_body = {"confirmation": "commerce", "revision": state["revision"]}
            before = config_path.read_bytes()
            for name, data in (("default", {**delete_body, "confirmation": "default"}),
                               ("commerce", {**delete_body, "confirmation": "wrong"}),
                               ("commerce", {**delete_body, "revision": "0" * 64})):
                response = client.request("DELETE", base + "/projects/" + name, json=data)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(config_path.read_bytes(), before)
                self.assertTrue(profile.is_dir())
            request_count = len(calls)
            response = client.request("DELETE", base + "/projects/commerce", json=delete_body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"profile": "commerce", "profile_delete_required": True,
                                              "restart_required": True})
            self.assertEqual(len(calls), request_count, "Deleting a local project must not mutate GitLab")
            self.assertTrue(profile.is_dir(), "Native Desktop must retire profile processes before deletion")
            self.assertEqual(client.get(base + "/projects").json()["projects"][0]["repositories"], [])
            # Same native endpoint used by Desktop's deleteProfile SDK. Only the
            # temporary profile is removed; process/service effects are mocked above.
            response = client.delete("/api/profiles/commerce")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(profile.exists())
            self.assertEqual(client.get(base + "/projects").json()["projects"], [])
            saved = yaml.safe_load(config_path.read_text())
            saved.pop("model")
            config_path.write_text(yaml.safe_dump(saved))
            state = client.get(base + "/projects").json()
            response = client.put(base + "/projects/no-model", json={"repositories": [], "revision": state["revision"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["model_setup"]["model"], "gpt-6-sol",
                             "Projects use the installed egg snapshot, not later default settings")
            (root / "profiles" / "project-egg" / "config.yaml").write_text("{}")
            state = client.get(base + "/projects").json()
            self.assertNotIn("project-egg", [p["profile"] for p in state["projects"]])
            response = client.put(base + "/projects/empty-model", json={"repositories": [], "revision": state["revision"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["model_setup"]["model"], "")
            self.assertTrue(response.json()["restart_started"], "Model setup and restart are separate outcomes")
            saved = yaml.safe_load(config_path.read_text())
            saved["plugins"]["disabled"] = ["hermes-gitlab"]
            config_path.write_text(yaml.safe_dump(saved))
            self.assertEqual(client.get(base + "/projects").status_code, 404)
            self.assertEqual(client.request("DELETE", base + "/projects/commerce", json=delete_body).status_code, 404)


if __name__ == "__main__":
    unittest.main()
