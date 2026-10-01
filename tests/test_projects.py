import argparse
import contextlib
import io
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import os
import json
import re
import shutil
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml
from hermes_cli.plugins import PluginManager
from hermes_cli.plugins_manifest import parse_manifest_file


class ProjectSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.tmp.name, "GATEWAY_MULTIPLEX_PROFILES": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        plugin = Path(__file__).parents[1]
        manager = PluginManager()
        manifest = parse_manifest_file(plugin / "plugin.yaml", plugin, "user", "")
        self.config_path = self.root / "config.yaml"
        self.config_path.write_text(yaml.safe_dump({
            "gateway": {"multiplex_profiles": True, "profile_routes": [
                {"platform": "telegram", "chat_id": "123", "profile": "personal"}]},
            "model": {"default": "example-model"},
            "platforms": {"gitlab": {"extra": {"toolsets": ["web"]}}},
        }))
        # Exercise native creation; avoid skill-sync subprocesses and live service notifications.
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("hermes_cli.profiles.seed_profile_skills", return_value={}))
        self.stack.enter_context(patch("hermes_cli.profiles._notify_multiplexer"))
        self.stack.enter_context(patch("hermes_cli.profiles._maybe_register_gateway_service"))
        manager._load_plugin(manifest)
        self.assertIn("gitlab", manager._cli_commands, "Plugin has no project setup command")
        self.command = manager._cli_commands["gitlab"]

    def run_command(self, *argv):
        parser = argparse.ArgumentParser()
        self.command["setup_fn"](parser)
        args = parser.parse_args(argv)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.command["handler_fn"](args)
        return output.getvalue()

    def test_removed_global_skills_are_archived_once(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        profile = self.root / "profiles/global-project"
        skills = profile / "skills"
        names = ("codev-handoff", "gitlab-cli", "gitlab-workflow", "mattermost-onboarding")
        for name in names:
            path = skills / name
            path.mkdir()
            (path / "SKILL.md").write_text(name)
        cli.migrate_shared_skills(profile)
        for name in names:
            self.assertFalse((skills / name).exists())
            self.assertEqual(next(profile.glob(f"backups/gitlab-skills/*/{name}/SKILL.md")).read_text(), name)
        cli.migrate_shared_skills(profile)
        self.assertEqual(len(list(profile.glob("backups/gitlab-skills/*"))), 1)

    def test_status_reads_the_issue_sessions_latest_history_without_a_turn(self):
        from hermes_state import SessionDB
        self.run_command("add-project", "commerce", "--repos", "42")
        with patch.dict(os.environ, {"HERMES_SESSION_PROFILE": "commerce"}):
            self.assertIn("no session yet", self.run_command("status", "--issue", "42:issues:3"))
        key = "agent:commerce:gitlab:group:42:issues:3:3"
        with contextlib.closing(SessionDB(db_path=self.root / "profiles/commerce/state.db")) as db:
            db.create_session("old", "gitlab", session_key=key)
            db.append_message("old", "user", "Kerjakan issue #3", timestamp=1000)
            db.create_session("new", "gitlab", session_key=key)
            db.append_message("new", "user", "Lanjutkan migrasi", timestamp=2000)
            db.append_message("new", "assistant", tool_calls=[{"id": "t", "type": "function", "function": {
                "name": "terminal", "arguments": "{}"}}], timestamp=2001)
            db.append_message("new", "tool", "TOKEN=secret-output", tool_call_id="t", timestamp=2002)
            db.append_message("new", "assistant", "Migrasi selesai, MR !7 dibuka.", timestamp=2003)
            db.create_session("other", "gitlab", session_key=key.replace(":3:3", ":4:4"))
            db.append_message("other", "assistant", "Issue lain", timestamp=3000)
        with patch.dict(os.environ, {"HERMES_SESSION_PROFILE": "commerce"}):
            output = self.run_command("status", "--issue", "42:issues:3")
            self.assertIn("@session:commerce/new", output)
            self.assertIn("[tools: terminal]", output)
            self.assertIn("Migrasi selesai, MR !7 dibuka.", output)
            self.assertNotIn("secret-output", output)
            self.assertNotIn("Issue lain", output)
            self.assertNotIn("Lanjutkan migrasi", self.run_command("status", "--issue", "42:issues:3",
                                                                   "--limit", "2"))
            # The gateway routing index wins: /resume or /new can point the card at another session.
            with contextlib.closing(SessionDB(db_path=self.root / "state.db")) as db:
                db.save_gateway_routing_entry(key, json.dumps({"session_key": key, "session_id": "old"}),
                                              scope=str(self.root.resolve() / "sessions"))
            output = self.run_command("status", "--issue", "42:issues:3")
            self.assertIn("@session:commerce/old", output)
            self.assertIn("Kerjakan issue #3", output)
        with patch.dict(os.environ, {"HERMES_SESSION_PROFILE": "personal"}):
            with self.assertRaisesRegex(SystemExit, "not routed to this"):
                self.run_command("status", "--issue", "42:issues:3")

    def test_continue_queues_only_a_verified_assigned_mattermost_request(self):
        self.run_command("add-project", "commerce", "--repos", "42")
        state = {"assigned": True, "message": "@hermes-bot lanjutkan pekerjaan ini"}

        class Server(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/mattermost/api/v4/posts/" + "c" * 26:
                    row = {"id": "c" * 26, "channel_id": "a" * 26,
                           "root_id": "b" * 26, "user_id": "d" * 26,
                           "message": state["message"]}
                    self.send_response(200)
                elif self.path == "/mattermost/api/v4/users/me":
                    row = {"id": "e" * 26, "username": "hermes-bot"}
                    self.send_response(200)
                elif self.path == "/mattermost/api/v4/channels/" + "a" * 26:
                    row = {"id": "a" * 26, "type": "O"}
                    self.send_response(200)
                elif self.path == "/gitlab/api/v4/user":
                    row = {"id": 99, "username": "hermes-bot"}
                    self.send_response(200)
                elif self.path == "/gitlab/api/v4/projects/42/issues/3":
                    row = {"assignees": [{"id": 99}] if state["assigned"] else [],
                           "web_url": self.server.gitlab_url + "/group/repo/-/issues/3"}
                    self.send_response(200)
                else:
                    row = {"error": "not found"}
                    self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(row).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        server.gitlab_url = f"http://127.0.0.1:{server.server_port}/gitlab"
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = yaml.safe_load(self.config_path.read_text())
        config["platforms"]["gitlab"]["extra"].update({"url": server.gitlab_url, "token": "gl-pat"})
        config["platforms"]["mattermost"] = {"extra": {
            "url": f"http://127.0.0.1:{server.server_port}/mattermost", "token": "mm-pat"}}
        self.config_path.write_text(yaml.safe_dump(config))
        context = {"HERMES_SESSION_PLATFORM": "mattermost", "HERMES_SESSION_CHAT_TYPE": "channel",
                   "HERMES_SESSION_CHAT_ID": "a" * 26, "HERMES_SESSION_THREAD_ID": "b" * 26,
                   "HERMES_SESSION_MESSAGE_ID": "c" * 26, "HERMES_SESSION_USER_ID": "d" * 26,
                   "HERMES_SESSION_PROFILE": "commerce"}
        with patch.dict(os.environ, context):
            self.assertIn("queued", self.run_command("continue", "--issue", "42:issues:3"))
            state["message"] = ("@hermes-bot lanjutkan " + server.gitlab_url +
                                "/group/repo/-/issues/3.")
            self.assertIn("queued", self.run_command("continue", "--issue", "42:issues:3"))
            state["message"] = ("@hermes-bot lanjutkan " + server.gitlab_url +
                                "/group/repo/-/issues/4")
            with self.assertRaisesRegex(SystemExit, "does not match"):
                self.run_command("continue", "--issue", "42:issues:3")
            state["message"] += " " + server.gitlab_url + "/group/repo/-/issues/3"
            with self.assertRaisesRegex(SystemExit, "Ambiguous"):
                self.run_command("continue", "--issue", "42:issues:3")
            state["message"] = "@hermes-bot lanjutkan pekerjaan ini"
            state["assigned"] = False
            with self.assertRaisesRegex(SystemExit, "not assigned"):
                self.run_command("continue", "--issue", "42:issues:3")
        path = self.root / "gitlab" / (hashlib.sha256((server.gitlab_url + "\n99").encode()).hexdigest() + ".sqlite3")
        with sqlite3.connect(path) as db:
            rows = db.execute("SELECT payload FROM handoffs").fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(payload["issue"], "42:issues:3")
        self.assertEqual(payload["origin_url"],
                         f"http://127.0.0.1:{server.server_port}/mattermost/_redirect/pl/" + "b" * 26)
        self.assertEqual(payload["origin_chat_type"], "channel")
        self.assertNotIn("origin_session_key", payload)

        # A turn the gateway started by relaying a GitLab report has no mentioning post. It may
        # continue an assigned issue once per relayed report, carrying --request as its text.
        key = "agent:commerce:mattermost:channel:" + "a" * 26 + ":" + "b" * 26
        relay_payload = {"issue": "42:issues:5", "profile": "commerce", "origin_channel": "a" * 26,
                         "origin_root": "b" * 26, "origin_post": "c" * 26, "origin_user": "d" * 26,
                         "origin_url": f"http://127.0.0.1:{server.server_port}/mattermost/_redirect/pl/" + "b" * 26,
                         "issue_url": server.gitlab_url + "/group/repo/-/issues/5", "origin_chat_type": "channel"}
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS relays (
                id TEXT PRIMARY KEY, session_key TEXT NOT NULL, issue TEXT NOT NULL, payload TEXT NOT NULL,
                relay_post TEXT NOT NULL, body_hash TEXT NOT NULL, chain INTEGER NOT NULL DEFAULT 0,
                injected_at TEXT NOT NULL)""")
            db.execute("INSERT INTO relays VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       ("handoff:parent", key, "42:issues:5", json.dumps(relay_payload), "f" * 26, "hash", 1,
                        "2026-09-30T00:00:00+00:00"))
        state["assigned"] = True
        relayed = {**context, "HERMES_SESSION_MESSAGE_ID": "", "HERMES_SESSION_KEY": key}
        with patch.dict(os.environ, relayed):
            with self.assertRaisesRegex(SystemExit, "needs --request"):
                self.run_command("continue", "--issue", "42:issues:3")
            self.assertIn("queued", self.run_command("continue", "--issue", "42:issues:3",
                                                     "--request", "Blocker #5 beres, lanjutkan."))
            self.assertIn("queued", self.run_command("continue", "--issue", "42:issues:3",
                                                     "--request", "Blocker #5 beres, lanjutkan."))
        with patch.dict(os.environ, {**relayed, "HERMES_SESSION_KEY": key + ":" + "9" * 26}):
            with self.assertRaisesRegex(SystemExit, "No relayed GitLab report"):
                self.run_command("continue", "--issue", "42:issues:3", "--request", "lanjut")
        with patch.dict(os.environ, {**relayed, "HERMES_SESSION_THREAD_ID": "9" * 26}):
            with self.assertRaisesRegex(SystemExit, "does not belong to this Mattermost thread"):
                self.run_command("continue", "--issue", "42:issues:3", "--request", "lanjut")
        with sqlite3.connect(path) as db:
            rows = db.execute("SELECT payload FROM handoffs ORDER BY rowid").fetchall()
        self.assertEqual(len(rows), 2)
        payload = json.loads(rows[1][0])
        self.assertEqual((payload["issue"], payload["relay_of"], payload["chain"], payload["origin_post"]),
                         ("42:issues:3", "handoff:parent", 2, "f" * 26))
        self.assertEqual((payload["origin_session_key"], payload["origin_user"], payload["request"]),
                         (key, "d" * 26, "Blocker #5 beres, lanjutkan."))

    def test_create_reuse_and_list_project_preserves_knowledge_and_config(self):
        self.run_command("add-project", "commerce", "--repos", "101,102", "--description", "Commerce services")
        profile = self.root / "profiles" / "commerce"
        self.assertTrue((profile / "config.yaml").is_file())
        self.assertEqual(yaml.safe_load((profile / "config.yaml").read_text())["model"],
                         {"default": "gpt-6-sol", "provider": "openai-codex"})
        self.assertTrue((profile / ".env").is_file())
        self.assertEqual(yaml.safe_load((profile / "profile.yaml").read_text())["description"], "Commerce services")
        memory = profile / "memories" / "MEMORY.md"
        memory.parent.mkdir(exist_ok=True)
        memory.write_text("Commerce knowledge")
        first = self.config_path.read_bytes()
        self.run_command("add-project", "commerce", "--repos", "101,102")
        self.assertEqual(self.config_path.read_bytes(), first)
        self.run_command("add-project", "commerce", "--repos", "103")
        self.assertEqual(memory.read_text(), "Commerce knowledge")
        config = yaml.safe_load(self.config_path.read_text())
        routes = config["gateway"]["profile_routes"]
        self.assertEqual(routes[0]["platform"], "telegram")
        self.assertEqual({r["chat_id"] for r in routes[1:]}, {"repo:101", "repo:102", "repo:103"})
        self.assertEqual(config["platforms"]["gitlab"]["extra"]["projects"], ["101", "102", "103"])
        self.assertTrue(config["platforms"]["gitlab"]["extra"]["require_profile_route"])
        self.assertEqual(config["platforms"]["gitlab"]["extra"]["toolsets"], ["web"])
        self.assertIn("commerce", self.run_command("projects"))
        self.assertIn("103", self.run_command("projects"))

    def test_project_terminal_starts_at_profile_root_and_preserves_custom_cwd(self):
        from tools.terminal_scope import build_profile_terminal_scope

        egg = self.root / "profiles" / "project-egg"
        self.assertEqual(Path(build_profile_terminal_scope(egg)["TERMINAL_CWD"]).resolve(), egg.resolve())
        self.run_command("add-project", "commerce", "--repos", "101")
        profile = self.root / "profiles" / "commerce"
        self.assertEqual(Path(build_profile_terminal_scope(profile)["TERMINAL_CWD"]).resolve(), profile.resolve())
        self.assertTrue((profile / "SOUL.md").is_file())
        self.assertTrue((profile / "memories").is_dir())
        config = yaml.safe_load((profile / "config.yaml").read_text())
        for cwd in (".", str(profile / "workspace")):
            config["terminal"]["cwd"] = cwd
            (profile / "config.yaml").write_text(yaml.safe_dump(config))
            self.run_command("sync-knowledge")
            self.assertEqual(Path(build_profile_terminal_scope(profile)["TERMINAL_CWD"]).resolve(), profile.resolve())
        config["terminal"]["cwd"] = str(profile / "workspace" / "custom")
        (profile / "config.yaml").write_text(yaml.safe_dump(config))
        self.run_command("sync-knowledge")
        self.assertEqual(build_profile_terminal_scope(profile)["TERMINAL_CWD"], config["terminal"]["cwd"])

    def test_sync_knowledge_updates_bundled_skills_with_backups_only_on_explicit_sync(self):
        from agent.skill_utils import _external_dirs_cache_clear
        from tools.skills_tool import skill_view

        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        bundle = Path(__file__).parents[1] / "templates/global-project/skills"
        profiles = [self.root / "profiles" / name for name in ("project-egg", "commerce")]
        shared = self.root / "profiles/global-project"
        shared_skill = shared / "skills/close-worktree/SKILL.md"
        shared_skill.write_text("Shared custom instructions")
        cli.ensure_template()
        self.assertEqual(shared_skill.read_text(), "Shared custom instructions")
        for profile in profiles:
            shutil.copytree(bundle, profile / "skills", dirs_exist_ok=True)
            (profile / "skills/close-worktree/SKILL.md").write_text("Local custom instructions")
            (profile / "skills/close-worktree/SKILL.md").chmod(0o640)
            (profile / "skills/close-worktree/scripts").mkdir(exist_ok=True)
            (profile / "skills/close-worktree/scripts/worktree.py").write_text("# old helper")
            (profile / "skills/tunnel-preview/SKILL.md").unlink()
            (profile / "skills/custom").mkdir()
            (profile / "skills/custom/SKILL.md").write_text("Keep custom skill")
            (profile / "memories/INDEX.md").write_text("Keep learned knowledge")
            config = yaml.safe_load((profile / "config.yaml").read_text())
            config["skills"] = {"external_dirs": "../other-skills", "disabled": ["example"]}
            (profile / "config.yaml").write_text(yaml.safe_dump(config))
        cli.refresh_project_knowledge(self.root)
        self.assertEqual((profiles[1] / "skills/close-worktree/SKILL.md").read_text(), "Local custom instructions")
        output = self.run_command("sync-knowledge")
        shared_backup = list(shared.glob("backups/gitlab-skills/*/close-worktree/SKILL.md"))
        self.assertEqual(len(shared_backup), 1)
        self.assertEqual(shared_backup[0].read_text(), "Shared custom instructions")
        for profile in profiles:
            for relative in ("close-worktree/SKILL.md", "tunnel-preview/SKILL.md"):
                self.assertFalse((profile / "skills" / relative).exists())
                self.assertEqual((shared / "skills" / relative).read_bytes(), (bundle / relative).read_bytes())
            self.assertFalse((profile / "skills/close-worktree/scripts/worktree.py").exists())
            self.assertEqual(yaml.safe_load((profile / "config.yaml").read_text())["skills"], {
                "external_dirs": ["../other-skills", "../global-project/skills"], "disabled": ["example"]})
            self.assertEqual((profile / "skills/custom/SKILL.md").read_text(), "Keep custom skill")
            self.assertEqual((profile / "memories/INDEX.md").read_text(), "Keep learned knowledge")
            backups = list((profile / "backups/gitlab-skills").glob("*/close-worktree/SKILL.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "Local custom instructions")
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o640)
            self.assertEqual((backups[0].parent / "scripts/worktree.py").read_text(), "# old helper")
            self.assertIn(str(backups[0].parent.parent), output)
            with patch.dict(os.environ, {"HERMES_HOME": str(profile)}):
                _external_dirs_cache_clear()
                for name in ("tunnel-preview", "close-worktree", "mattermost-access", "codev-workflow", "caveman", "ponytail",
                             "superpowers/brainstorming", "superpowers:writing-plans", "superpowers/test-driven-development"):
                    viewed = json.loads(skill_view(name))
                    relative = name.replace(":", "/")
                    self.assertEqual(Path(viewed["_source_path"]).resolve(),
                                     (shared / "skills" / relative / "SKILL.md").resolve())
                    self.assertFalse((profile / "skills" / relative).exists())
        before = {p: p.stat().st_mtime_ns for profile in [*profiles, shared] for p in profile.rglob("*") if p.is_file()}
        backup_dirs_before = set(profiles[1].glob("backups/gitlab-skills/*"))
        self.run_command("sync-knowledge")
        for path, mtime in before.items():
            self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(set(profiles[1].glob("backups/gitlab-skills/*")), backup_dirs_before)
        self.run_command("add-project", "finance", "--repos", "102")
        self.assertFalse((self.root / "profiles/finance/skills/close-worktree").exists())
        self.assertFalse((self.root / "profiles/personal/skills").exists())

    def test_sync_renames_workflow_without_losing_retired_skill_customizations(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        profiles = [self.root / "profiles" / name for name in
                    ("global-project", "project-egg", "commerce")]
        for profile in profiles:
            old = profile / "skills/codev-gitlab"
            old.mkdir(exist_ok=True)
            (old / "SKILL.md").write_text("Old customized workflow")
            (old / "notes.md").write_text("Keep supporting files")
            old_dm = profile / "skills/mattermost-dm"
            old_dm.mkdir(exist_ok=True)
            (old_dm / "SKILL.md").write_text("Old customized DM skill")
            if profile.name != "global-project":
                with (profile / "SOUL.md").open("a") as soul:
                    soul.write("\nread `skills/codev-gitlab/SKILL.md` and follow its rules.\n"
                               "Use `mattermost-dm` for personal messages.\n")
        shared_config = (profiles[0] / "config.yaml").read_bytes()
        cli.ensure_template()
        self.assertFalse((profiles[0] / "skills/codev-gitlab").exists())
        self.run_command("sync-knowledge")
        for profile in profiles:
            self.assertFalse((profile / "skills/codev-gitlab").exists())
            self.assertFalse((profile / "skills/mattermost-dm").exists())
            backup = list(profile.glob("backups/gitlab-skills/*/codev-gitlab/SKILL.md"))
            self.assertEqual(len(backup), 1)
            self.assertEqual(backup[0].read_text(), "Old customized workflow")
            self.assertEqual((backup[0].parent / "notes.md").read_text(), "Keep supporting files")
            old_dm_backup = list(profile.glob("backups/gitlab-skills/*/mattermost-dm/SKILL.md"))
            self.assertEqual(len(old_dm_backup), 1)
            self.assertEqual(old_dm_backup[0].read_text(), "Old customized DM skill")
            if profile.name != "global-project":
                soul = (profile / "SOUL.md").read_text()
                self.assertNotIn("codev-gitlab", soul)
                self.assertNotIn("mattermost-dm", soul)
                self.assertIn("mattermost-access", soul)
                self.assertNotIn("load `gitlab-workflow` with `skill_view`", soul)
        self.assertEqual((profiles[0] / "config.yaml").read_bytes(), shared_config)
        self.assertFalse((profiles[0] / "skills/close-worktree/scripts/worktree.py").exists())
        self.run_command("sync-knowledge")
        self.assertTrue(all(len(list(p.glob("backups/gitlab-skills/*/codev-gitlab/SKILL.md"))) == 1
                            for p in profiles))

    def test_shared_skill_migration_preserves_legacy_files_on_failure(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        profile = self.root / "profiles/commerce"
        legacy = profile / "skills/codev-gitlab"
        legacy.mkdir()
        (legacy / "SKILL.md").write_text("Legacy custom skill")
        (legacy / "notes.md").write_text("Custom supporting file")
        outside = self.root / "outside"
        outside.mkdir()
        backup_dir = profile / "backups/gitlab-skills"
        if backup_dir.exists():
            backup_dir.rename(backup_dir.with_name("gitlab-skills-preexisting"))
        backup_dir.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            cli.migrate_shared_skills(profile)
        self.assertEqual(list(outside.iterdir()), [])
        backup_dir.unlink()
        with patch.object(Path, "rename", side_effect=OSError("Archive unavailable")):
            with self.assertRaisesRegex(OSError, "Archive unavailable"):
                cli.migrate_shared_skills(profile)
        self.assertEqual((legacy / "SKILL.md").read_text(), "Legacy custom skill")
        cli.migrate_shared_skills(profile)
        self.assertFalse(legacy.exists())
        self.assertEqual(next(profile.glob("backups/gitlab-skills/*/codev-gitlab/notes.md")).read_text(),
                         "Custom supporting file")

    def test_skill_sync_rejects_symlinks_and_stops_when_backup_fails(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        profile = self.root / "profiles/global-project"
        target = profile / "skills/close-worktree/SKILL.md"
        target.write_text("Keep local edits")
        outside = self.root / "outside"
        outside.mkdir()
        for relative in ("skills", "skills/close-worktree", "skills/close-worktree/SKILL.md", "backups"):
            with self.subTest(relative=relative):
                path = profile / relative
                saved = path.with_name(path.name + ".saved")
                existed = path.exists()
                if existed:
                    path.rename(saved)
                path.symlink_to(outside)
                try:
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        cli.sync_project_skills(profile)
                    self.assertEqual(list(outside.iterdir()), [])
                finally:
                    path.unlink()
                    if existed:
                        saved.rename(path)
        with patch.object(cli.shutil, "copy2", side_effect=OSError("Backup unavailable")):
            with self.assertRaisesRegex(OSError, "Backup unavailable"):
                cli.sync_project_skills(profile)
        self.assertEqual(target.read_text(), "Keep local edits")

    def test_repository_knowledge_tracks_mapping_and_preserves_custom_content(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        config = yaml.safe_load(self.config_path.read_text())
        config["platforms"]["gitlab"]["extra"].update(url="https://gitlab.example/team", token="never-copy-this")
        self.config_path.write_text(yaml.safe_dump(config))
        cli.add_project(self.root, "commerce", ["101", "102"], None, repository_info={
            "101": {"name": "team/shop", "url": "https://gitlab.example/team/team/shop"}})
        profile = self.root / "profiles" / "commerce"
        inventory = profile / "PROJECT.yaml"
        self.assertTrue(inventory.is_file(), "Mapped repositories must be discoverable outside GitLab events")
        data = yaml.safe_load(inventory.read_text())
        self.assertEqual(data["profile"], "commerce")
        self.assertEqual(data["gitlab_url"], "https://gitlab.example/team")
        self.assertEqual(data["repositories"][0], {"id": "101", "name": "team/shop",
            "url": "https://gitlab.example/team/team/shop", "clone_path": "workspace/101"})
        self.assertEqual(data["repositories"][1]["id"], "102")
        self.assertNotIn("never-copy-this", inventory.read_text())
        (profile / "SOUL.md").write_text("Our custom instructions\n")
        (profile / "memories" / "INDEX.md").write_text("Our verified project notes\n")
        self.run_command("add-project", "finance", "--repos", "103")
        cli.add_project(self.root, "commerce", ["102"], None, replace=True)
        self.assertEqual([r["id"] for r in yaml.safe_load(inventory.read_text())["repositories"]], ["102"])
        self.assertTrue((profile / "SOUL.md").read_text().startswith("Our custom instructions\n"))
        self.assertEqual((profile / "SOUL.md").read_text(), "Our custom instructions\n")
        self.assertEqual((profile / "memories" / "INDEX.md").read_text(), "Our verified project notes\n")
        revision = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        cli.remove_project_registration(self.root, "commerce", revision=revision, confirmation="commerce")
        self.assertEqual(yaml.safe_load(inventory.read_text())["repositories"], [])

    def test_plugin_reload_backfills_legacy_profiles_and_clears_disabled_mappings(self):
        self.run_command("add-project", "commerce", "--repos", "101,102")
        profile = self.root / "profiles" / "commerce"
        (profile / "SOUL.md").write_text("Custom personality\n")
        (profile / "profile.yaml").write_text("description: Legacy\n")
        (profile / "PROJECT.yaml").unlink(missing_ok=True)
        config = yaml.safe_load(self.config_path.read_text())
        config["gateway"]["profile_routes"][-1]["enabled"] = False
        self.config_path.write_text(yaml.safe_dump(config))
        plugin = Path(__file__).parents[1]
        manifest = parse_manifest_file(plugin / "plugin.yaml", plugin, "user", "")
        PluginManager()._load_plugin(manifest)
        inventory = profile / "PROJECT.yaml"
        self.assertTrue(inventory.is_file(), "Plugin reload must upgrade existing profiles")
        self.assertEqual([r["id"] for r in yaml.safe_load(inventory.read_text())["repositories"]], ["101"])
        soul = (profile / "SOUL.md").read_text()
        self.assertTrue(soul.startswith("Custom personality\n"))
        self.assertEqual(soul, "Custom personality\n")
        self.run_command("sync-knowledge")
        self.assertEqual((profile / "SOUL.md").read_text(),
                         (plugin / "templates/project-egg/SOUL.md").read_text())
        self.assertEqual(next(profile.glob("backups/gitlab-soul/*/SOUL.md")).read_text(), soul)
        self.assertFalse((self.root / "profiles" / "personal" / "PROJECT.yaml").exists())

    def test_sync_replaces_project_souls_with_backups_and_preserves_knowledge(self):
        from agent.skill_utils import _external_dirs_cache_clear
        from tools.skills_tool import skill_view

        self.run_command("add-project", "commerce", "--repos", "101")
        bundle = Path(__file__).parents[1] / "templates"
        start, end = "<!-- hermes-gitlab:orientation:start -->", "<!-- hermes-gitlab:orientation:end -->"
        prefix, suffix = "Custom team conventions\n", "\n## Local delivery notes\nKeep our release policy.\n"
        existing = prefix + start + "\nOlder persona\n" + end + suffix
        profiles = [self.root / "profiles" / name for name in ("project-egg", "commerce")]
        for profile in profiles:
            (profile / "SOUL.md").write_text(existing)
            (profile / "memories/INDEX.md").write_text("Our verified project notes\n")
        self.run_command("sync-knowledge")
        for profile in profiles:
            self.assertEqual((profile / "SOUL.md").read_text(),
                             (bundle / "project-egg/SOUL.md").read_text())
            backups = list(profile.glob("backups/gitlab-soul/*/SOUL.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), existing)
            self.assertEqual((profile / "memories/INDEX.md").read_text(), "Our verified project notes\n")
            with patch.dict(os.environ, {"HERMES_HOME": str(profile)}):
                _external_dirs_cache_clear()
                for name in ("close-worktree", "tunnel-preview"):
                    viewed = json.loads(skill_view(name))
                    source = Path(viewed["_source_path"])
                    self.assertEqual(source.read_bytes(),
                                     (bundle / "global-project/skills" / name / "SKILL.md").read_bytes())
        self.run_command("sync-knowledge")
        for profile in profiles:
            self.assertEqual((profile / "SOUL.md").read_text(),
                             (bundle / "project-egg/SOUL.md").read_text())
            self.assertEqual(len(list(profile.glob("backups/gitlab-soul/*/SOUL.md"))), 1)

    def test_quiet_display_migrates_existing_profiles_without_losing_custom_settings(self):
        from gateway.display_config import resolve_display_setting

        self.run_command("add-project", "commerce", "--repos", "101")
        profile = self.root / "profiles" / "commerce"
        path = profile / "config.yaml"
        config = yaml.safe_load(path.read_text())
        config["display"] = {"show_reasoning": True, "show_cost": True, "platforms": {
            "mattermost": {"show_reasoning": True, "long_running_notifications": True,
                           "streaming": True, "tool_preview_length": 23},
            "gitlab": {"thinking_progress": True, "tool_progress": "all"},
        }}
        config.pop("onboarding", None)
        path.write_text(yaml.safe_dump(config))
        egg_path = self.root / "profiles/project-egg/config.yaml"
        egg_config = yaml.safe_load(egg_path.read_text())
        egg_config["display"].pop("busy_ack_enabled", None)
        egg_config.pop("onboarding", None)
        egg_path.write_text(yaml.safe_dump(egg_config))
        self.run_command("sync-knowledge")
        migrated = yaml.safe_load(path.read_text())
        self.assertTrue(migrated["display"]["show_cost"])
        self.assertEqual(migrated["display"]["platforms"]["mattermost"]["tool_preview_length"], 23)
        self.assertEqual(migrated["model"], config["model"])
        for target in (profile, self.root / "profiles" / "project-egg"):
            settings = yaml.safe_load((target / "config.yaml").read_text())
            self.assertIs(settings["display"]["busy_ack_enabled"], False)
            self.assertIs(settings["onboarding"]["seen"]["busy_input_prompt"], True)
            for platform in ("mattermost", "gitlab"):
                for key in ("show_reasoning", "thinking_progress", "long_running_notifications", "streaming"):
                    self.assertFalse(resolve_display_setting(settings, platform, key), (target.name, platform, key))
                self.assertEqual(resolve_display_setting(settings, platform, "tool_progress"), "off")
                self.assertTrue(resolve_display_setting(settings, platform, "interim_assistant_messages"))
        before = path.read_bytes()
        self.run_command("sync-knowledge")
        self.assertEqual(path.read_bytes(), before)

    def test_workflow_nodes_stay_in_soul(self):
        bundle = Path(__file__).parents[1] / "templates"
        soul = (bundle / "project-egg/SOUL.md").read_text()
        self.assertIn("```mermaid\nstateDiagram", soul)
        graph = soul.split("```mermaid\n", 1)[1].split("```", 1)[0]
        edges = re.findall(r"^\s*(\w+|\[\*\]) --> (\w+|\[\*\])", graph, re.MULTILINE)
        nodes = {node for edge in edges for node in edge} - {"[*]"}
        self.assertIn(("AwaitingAssignment", "Working"), edges)
        self.assertIn(("Validating", "PreparingMergeRequest"), edges)
        self.assertIn(("AwaitingReview", "Completed"), edges)
        for path in [bundle / "project-egg/prompts/architecture.md",
                     bundle / "project-egg/prompts/README.md",
                     bundle / "project-egg/skills/README.md",
                     bundle / "project-egg/TAXONOMY.md",
                     *sorted(path for path in (bundle / "global-project/skills").glob("*/SKILL.md")
                             if path.parent.name != "codev-workflow")]:
            with self.subTest(path=path.name, skill=path.parent.name):
                text = path.read_text()
                self.assertNotRegex(text, r"(?m)^Nodes:")
                self.assertFalse(set(re.findall(r"`([^`]+)`", text)) & nodes)
                self.assertNotIn("stateDiagram", text)
        self.run_command("add-project", "commerce", "--repos", "101")
        copied = (self.root / "profiles/commerce/SOUL.md").read_text()
        self.assertIn(graph, copied)
        self.run_command("sync-knowledge")
        self.assertIn(graph, (self.root / "profiles/commerce/SOUL.md").read_text())
        workflow = bundle / "global-project/skills/codev-workflow"
        router = (workflow / "SKILL.md").read_text()
        self.assertIn("`codev-workflow`", soul)
        for relative in re.findall(r"`(tools/[a-z-]+\.md)`", router):
            self.assertTrue((workflow / relative).is_file(), relative)

    def test_orientation_limits_visible_messages_across_surfaces(self):
        bundle = Path(__file__).parents[1] / "templates" / "project-egg" / "SOUL.md"
        text = bundle.read_text()
        self.assertIn("Maksimal sekali per request", text)
        self.assertIn("Kode hanya lewat assignment GitLab", text)
        self.assertIn("Secret hanya lewat DM Mattermost terverifikasi", text)
        self.assertNotIn("codev-handoff", text)
        config = yaml.safe_load(
            (Path(__file__).parents[1] / "templates" / "project-egg" / "config.yaml").read_text())
        self.assertTrue(config["display"]["platforms"]["mattermost"]["interim_assistant_messages"])
        self.assertFalse(config["display"]["platforms"]["mattermost"]["tool_progress"])
        self.assertTrue(config["display"]["platforms"]["gitlab"]["interim_assistant_messages"])
        self.assertFalse(config["display"]["platforms"]["gitlab"]["tool_progress"])
        self.assertIn("Proses berpikir tidak ditampilkan", text)

    def test_project_marker_preserves_metadata_and_survives_empty_registration(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        path = self.root / "profiles" / "existing"
        path.mkdir(parents=True)
        (path / "config.yaml").write_text("{}")
        meta = path / "profile.yaml"
        meta.write_text("description: Existing knowledge\ndisplay_name: My project\ncustom: keep\n")
        self.run_command("add-project", "existing", "--repos", "101")
        saved = yaml.safe_load(meta.read_text())
        self.assertIs(saved.get("hermes_gitlab_project"), True)
        self.assertEqual(saved["display_name"], "My project")
        self.assertEqual(saved["custom"], "keep")
        cli.add_project(self.root, "existing", [], None, replace=True)
        self.assertTrue(cli.is_project_profile(path))
        revision = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        cli.remove_project_registration(self.root, "existing", revision=revision, confirmation="existing")
        self.assertTrue(cli.is_project_profile(path), "Keep project identity while native deletion may need retry")
        self.assertFalse(cli.is_project_profile(self.root / "profiles" / "project-egg"))

    def test_knowledge_refresh_preserves_file_modes_and_rejects_unsafe_targets(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        profile = self.root / "profiles" / "commerce"
        soul = profile / "SOUL.md"
        soul.write_text("Private custom instructions\n")
        soul.chmod(0o640)
        config = yaml.safe_load(self.config_path.read_text())
        cli.sync_project_knowledge(profile, config)
        self.assertEqual(soul.stat().st_mode & 0o777, 0o640)
        before = soul.read_bytes()
        inventory = profile / "PROJECT.yaml"
        inventory.unlink()
        outside = self.root / "unrelated.yaml"
        outside.write_text("Keep unrelated content")
        inventory.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            cli.sync_project_knowledge(profile, config)
        self.assertEqual(outside.read_text(), "Keep unrelated content")
        self.assertEqual(soul.read_bytes(), before)
        inventory.unlink()
        config["platforms"]["gitlab"]["extra"]["url"] = "https://user:secret@gitlab.example"
        with self.assertRaises(ValueError):
            cli.sync_project_knowledge(profile, config)
        self.assertFalse(inventory.exists())
        self.assertEqual(soul.read_bytes(), before)

    def test_inventory_uses_scoped_gitlab_host_not_another_profiles_environment(self):
        from agent.secret_scope import set_secret_scope, reset_secret_scope

        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        profile = self.root / "profiles" / "commerce"
        config = yaml.safe_load(self.config_path.read_text())
        with patch.dict(os.environ, {"GITLAB_URL": "https://another-profile.example"}):
            for host in ("https://correct.example", ""):
                token = set_secret_scope({"GITLAB_URL": host})
                try:
                    cli.sync_project_knowledge(profile, config)
                    self.assertEqual(yaml.safe_load((profile / "PROJECT.yaml").read_text())["gitlab_url"], host or None)
                finally:
                    reset_secret_scope(token)

    def test_legacy_routes_identify_projects_and_metadata_symlinks_are_rejected(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        path = self.root / "profiles" / "commerce"
        meta = path / "profile.yaml"
        old = {"description": "Legacy project"}
        meta.write_text(yaml.safe_dump(old))
        revision = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        cli.remove_project_registration(self.root, "commerce", revision=revision, confirmation="commerce")
        self.assertTrue(cli.is_project_profile(path), "Legacy registrations remain projects after route removal")
        external = self.root / "external.yaml"
        external.write_text("description: Keep this\n")
        meta.unlink()
        meta.symlink_to(external)
        before = self.config_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "symlink"):
            cli.add_project(self.root, "commerce", ["101"], None)
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(external.read_text(), "description: Keep this\n")

    def test_plugin_load_creates_bundled_egg_once_and_projects_copy_its_full_starter(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        egg = self.root / "profiles" / "project-egg"
        self.assertTrue((egg / "config.yaml").is_file())
        bundle = Path(__file__).parents[1] / "templates" / "project-egg"
        self.assertEqual((egg / "SOUL.md").read_bytes(), (bundle / "SOUL.md").read_bytes())
        config = yaml.safe_load((egg / "config.yaml").read_text())
        self.assertEqual(config["model"], {"default": "gpt-6-sol", "provider": "openai-codex"})
        config["model"] = {"default": "egg-model", "provider": "custom"}
        config["agent"] = {"max_turns": 42}
        config["compression"] = {"enabled": False}
        (egg / "config.yaml").write_text(yaml.safe_dump(config))
        files = {"SOUL.md": "Our project personality", "system_prompt.md": "Our custom prompt",
                 "prompts/review.md": "Review carefully", "skills/example/SKILL.md": "Example skill",
                 "skills/example/assets/sample.txt": "Skill asset", "memories/MEMORY.md": "Starter conventions",
                 ".env": "CUSTOM_TOOL_KEY=template-test-key\n"}
        for relative, content in files.items():
            path = egg / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        for relative in ("sessions/history.jsonl", "cron/jobs.json", "gateway_state.json"):
            path = egg / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
        cli.ensure_template()
        self.assertEqual((egg / "SOUL.md").read_text(), files["SOUL.md"])
        files["SOUL.md"] = (egg / "SOUL.md").read_text()
        self.run_command("add-project", "commerce", "--repos", "101", "--description", "Commerce project")
        project = self.root / "profiles" / "commerce"
        for relative in ("TAXONOMY.md", "prompts/architecture.md"):
            self.assertEqual((project / relative).read_bytes(), (bundle / relative).read_bytes())
        for relative, content in files.items():
            self.assertEqual((project / relative).read_text(), content)
        copied = yaml.safe_load((project / "config.yaml").read_text())
        for key in ("model", "agent", "compression"):
            self.assertEqual(copied[key], config[key])
        for relative in ("sessions/history.jsonl", "cron/jobs.json", "gateway_state.json"):
            self.assertFalse((project / relative).exists())
        (project / "SOUL.md").write_text("Commerce personality")
        (egg / "SOUL.md").write_text("Next generation starter")
        self.run_command("add-project", "commerce", "--repos", "102")
        self.assertEqual((project / "SOUL.md").read_text(), "Commerce personality")
        self.run_command("add-project", "finance", "--repos", "103")
        self.assertEqual((self.root / "profiles" / "finance" / "SOUL.md").read_text(), "Next generation starter")
        for name in ("default", "project-egg", "global-project"):
            with self.assertRaises(SystemExit):
                self.run_command("add-project", name, "--repos", "104")
            with self.assertRaises(ValueError):
                cli.remove_project_registration(self.root, name, confirmation=name,
                                                revision=hashlib.sha256(self.config_path.read_bytes()).hexdigest())

    def test_shared_profile_is_created_once_and_new_projects_load_its_live_skills(self):
        from agent.skill_utils import get_external_skills_dirs, _external_dirs_cache_clear

        cli = importlib.import_module(self.command["handler_fn"].__module__)
        shared = self.root / "profiles" / "global-project"
        egg = self.root / "profiles" / "project-egg"
        self.assertTrue((shared / "config.yaml").is_file(), "Plugin installation creates the shared profile")
        self.assertFalse(cli.is_project_profile(shared))
        skill = shared / "skills" / "team-conventions" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("Shared team conventions")
        # Upgrading an existing egg must merge the link without replacing customization.
        config = yaml.safe_load((egg / "config.yaml").read_text())
        config["skills"] = {"external_dirs": "../other-skills", "disabled": ["example"]}
        (egg / "config.yaml").write_text(yaml.safe_dump(config))
        (shared / "SOUL.md").write_text("Shared profile customization")
        cli.ensure_template()
        after = (egg / "config.yaml").read_bytes()
        cli.ensure_template()
        self.assertEqual((egg / "config.yaml").read_bytes(), after)
        self.assertEqual((shared / "SOUL.md").read_text(), "Shared profile customization")
        self.assertEqual(skill.read_text(), "Shared team conventions")
        self.assertEqual(yaml.safe_load(after)["skills"], {
            "external_dirs": ["../other-skills", "../global-project/skills"], "disabled": ["example"]})
        # An upgraded starter may still have local copies before explicit sync.
        legacy = egg / "skills/gitlab-workflow"
        legacy.mkdir()
        (legacy / "SKILL.md").write_text("Old starter customization")
        self.run_command("add-project", "commerce", "--repos", "101")
        project = self.root / "profiles" / "commerce"
        self.assertFalse((project / "skills/gitlab-workflow").exists())
        self.assertEqual(next(project.glob("backups/gitlab-skills/*/gitlab-workflow/SKILL.md")).read_text(),
                         "Old starter customization")
        self.assertFalse((project / "skills" / "team-conventions").exists(), "Shared skills are referenced, not copied")
        with patch.dict(os.environ, {"HERMES_HOME": str(project)}):
            _external_dirs_cache_clear()
            self.assertEqual(get_external_skills_dirs(), [(shared / "skills").resolve()])
            skill.write_text("Updated shared conventions")
            self.assertEqual((get_external_skills_dirs()[0] / "team-conventions" / "SKILL.md").read_text(),
                             "Updated shared conventions")

    def test_shared_setup_preserves_invalid_or_symlinked_starter_configuration(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        egg = self.root / "profiles" / "project-egg"
        path = egg / "config.yaml"
        for invalid in ("skills: wrong\n", "skills:\n  external_dirs: 42\n", "skills: [broken"):
            path.write_text(invalid)
            with self.assertRaises((ValueError, yaml.YAMLError)):
                cli.ensure_template()
            self.assertEqual(path.read_text(), invalid)
        path.unlink()
        external = self.root / "external.yaml"
        external.write_text("{}")
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            cli.ensure_template()
        self.assertEqual(external.read_text(), "{}")

    def test_conflicts_and_invalid_input_do_not_create_profiles_or_overwrite_config(self):
        self.run_command("add-project", "commerce", "--repos", "101")
        before = self.config_path.read_bytes()
        for profile, repos in (("finance", "101"), ("../escape", "102"), ("finance", "bad-id")):
            with self.assertRaises(SystemExit):
                self.run_command("add-project", profile, "--repos", repos)
            self.assertEqual(self.config_path.read_bytes(), before)
        self.assertFalse((self.root / "profiles" / "finance").exists())

    def test_template_copy_failure_does_not_publish_an_incomplete_profile(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        destination = self.root / "profiles" / "failed-egg"
        native_dir = cli.get_profile_dir
        with patch.object(cli, "get_profile_dir", side_effect=lambda name: destination if name == "project-egg" else native_dir(name)), \
                patch.object(cli.shutil, "copytree", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                cli.ensure_template()
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.glob(".project-egg-*")), [])
        self.assertTrue((destination.parent / "project-egg" / "config.yaml").is_file())

    def test_malformed_config_is_not_replaced(self):
        self.config_path.write_text("gateway: [broken")
        with self.assertRaises(SystemExit):
            self.run_command("add-project", "commerce", "--repos", "101")
        self.assertEqual(self.config_path.read_text(), "gateway: [broken")
        self.assertFalse((self.root / "profiles" / "commerce").exists())

    def test_native_top_level_routes_and_multiplex_precedence(self):
        config = yaml.safe_load(self.config_path.read_text())
        config["profile_routes"] = []
        config["multiplex_profiles"] = True
        config["gateway"]["multiplex_profiles"] = False
        self.config_path.write_text(yaml.safe_dump(config))
        self.run_command("add-project", "commerce", "--repos", "101")
        saved = yaml.safe_load(self.config_path.read_text())
        self.assertEqual(saved["profile_routes"][0]["chat_id"], "repo:101")
        self.assertEqual(saved["gateway"]["profile_routes"], config["gateway"]["profile_routes"])
        self.assertIn("101", self.run_command("projects"))
        with patch.dict(os.environ, {"GATEWAY_MULTIPLEX_PROFILES": "false"}):
            with self.assertRaises(SystemExit):
                self.run_command("add-project", "finance", "--repos", "102")
        self.assertFalse((self.root / "profiles" / "finance").exists())
        config["multiplex_profiles"] = False
        self.config_path.write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {"GATEWAY_MULTIPLEX_PROFILES": "true"}):
            self.run_command("add-project", "finance", "--repos", "102")
        self.assertTrue((self.root / "profiles" / "finance").is_dir())

    def test_conflicting_thread_only_route_is_rejected(self):
        config = yaml.safe_load(self.config_path.read_text())
        config["gateway"]["profile_routes"].append({
            "platform": "gitlab", "thread_id": "3", "profile": "finance"})
        self.config_path.write_text(yaml.safe_dump(config))
        with self.assertRaises(SystemExit):
            self.run_command("add-project", "commerce", "--repos", "101")
        self.assertFalse((self.root / "profiles" / "commerce").exists())

    def test_nested_platform_settings_cannot_override_saved_projects(self):
        from gateway.config import PlatformConfig
        from gateway.config_loader import merge_platform_sections

        config = yaml.safe_load(self.config_path.read_text())
        config["gateway"]["gitlab"] = {"extra": {"projects": "42", "require_profile_route": False}}
        self.config_path.write_text(yaml.safe_dump(config))
        self.run_command("add-project", "commerce", "--repos", "101")
        saved = yaml.safe_load(self.config_path.read_text())
        effective = PlatformConfig.from_dict(merge_platform_sections(saved, saved["gateway"], {})["gitlab"])
        self.assertEqual(effective.extra["projects"], ["42", "101"])
        self.assertTrue(effective.extra["require_profile_route"])

    def test_replace_routes_preserves_profile_and_rejects_stale_edit(self):
        self.run_command("add-project", "commerce", "--repos", "101,102")
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        profile = self.root / "profiles" / "commerce"
        memory = profile / "memories" / "MEMORY.md"
        memory.parent.mkdir(exist_ok=True)
        memory.write_text("Keep this knowledge")
        revision = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        cli.add_project(self.root, "commerce", ["102"], None, replace=True, revision=revision)
        saved = yaml.safe_load(self.config_path.read_text())
        self.assertEqual(saved["platforms"]["gitlab"]["extra"]["projects"], ["102"])
        self.assertEqual(memory.read_text(), "Keep this knowledge")
        with self.assertRaisesRegex(ValueError, "changed"):
            cli.add_project(self.root, "commerce", [], None, replace=True, revision=revision)
        saved["gateway"]["profile_routes"][-1]["enabled"] = False
        self.config_path.write_text(yaml.safe_dump(saved))
        cli.add_project(self.root, "commerce", ["102"], None, replace=True)
        self.assertTrue(yaml.safe_load(self.config_path.read_text())["gateway"]["profile_routes"][-1]["enabled"])
        cli.add_project(self.root, "commerce", [], None, replace=True)
        self.assertTrue((profile / "config.yaml").exists())
        self.assertNotIn("commerce", self.run_command("projects"))
        self.assertEqual(yaml.safe_load(self.config_path.read_text())["platforms"]["gitlab"]["extra"]["projects"], [])

    def test_delete_registration_preserves_profile_for_native_desktop_teardown(self):
        self.run_command("add-project", "commerce", "--repos", "101,102")
        self.run_command("add-project", "finance", "--repos", "201")
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        config = yaml.safe_load(self.config_path.read_text())
        extra = config["platforms"]["gitlab"]["extra"]
        extra["projects"].append("999")
        extra["repository_info"] = {"101": {"name": "Commerce"}, "201": {"name": "Finance"}}
        self.config_path.write_text(yaml.safe_dump(config))
        revision = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        self.assertEqual(cli.remove_project_registration(self.root, "commerce", revision=revision,
                                                        confirmation="commerce"), ("commerce", True))
        saved = yaml.safe_load(self.config_path.read_text())
        self.assertEqual(saved["platforms"]["gitlab"]["extra"]["projects"], ["201", "999"])
        self.assertEqual(saved["platforms"]["gitlab"]["extra"]["repository_info"], {"201": {"name": "Finance"}})
        self.assertEqual(saved["platforms"]["gitlab"]["extra"]["toolsets"], ["web"])
        self.assertTrue((self.root / "profiles" / "commerce" / "config.yaml").is_file())
        self.assertEqual(saved["gateway"]["profile_routes"][0], config["gateway"]["profile_routes"][0])
        # Native deletion can be retried without recreating a profile or changing unrelated routes.
        before = self.config_path.read_bytes()
        cli.remove_project_registration(self.root, "commerce", revision=hashlib.sha256(before).hexdigest(),
                                        confirmation="commerce")
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_delete_registration_rejects_stale_confirmation_and_other_route_dependencies(self):
        self.run_command("add-project", "commerce", "--repos", "101")
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        before = self.config_path.read_bytes()
        revision = hashlib.sha256(before).hexdigest()
        for name, confirm, rev in (("default", "default", revision), ("commerce", "wrong", revision),
                                   ("commerce", "commerce", "0" * 64), ("../bad", "../bad", revision)):
            with self.assertRaises(ValueError):
                cli.remove_project_registration(self.root, name, revision=rev, confirmation=confirm)
            self.assertEqual(self.config_path.read_bytes(), before)
        config = yaml.safe_load(before)
        config["gateway"]["profile_routes"].append({"platform": "telegram", "chat_id": "456", "profile": "commerce"})
        self.config_path.write_text(yaml.safe_dump(config))
        before = self.config_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "other profile routes"):
            cli.remove_project_registration(self.root, "commerce", revision=hashlib.sha256(before).hexdigest(),
                                            confirmation="commerce")
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_delete_missing_profile_only_cleans_its_registration(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        config = yaml.safe_load(self.config_path.read_text())
        config["gateway"]["profile_routes"].append({"name": "hermes-gitlab-repo-101", "platform": "gitlab",
                                                    "chat_id": "repo:101", "profile": "missing"})
        config["platforms"]["gitlab"]["extra"]["projects"] = ["101"]
        self.config_path.write_text(yaml.safe_dump(config))
        before = self.config_path.read_bytes()
        self.assertEqual(cli.remove_project_registration(self.root, "missing", revision=hashlib.sha256(before).hexdigest(),
                                                        confirmation="missing"), ("missing", False))
        self.assertFalse((self.root / "profiles" / "missing").exists())
        self.assertEqual(yaml.safe_load(self.config_path.read_text())["platforms"]["gitlab"]["extra"]["projects"], [])

    def test_delete_rejects_transport_dependencies_and_symlinked_profiles(self):
        cli = importlib.import_module(self.command["handler_fn"].__module__)
        self.run_command("add-project", "commerce", "--repos", "101")
        config = yaml.safe_load(self.config_path.read_text())
        config["gateway"]["profile_routes"].append({"platform": "telegram", "bot_profile": "commerce",
                                                    "profile": "personal", "enabled": False})
        self.config_path.write_text(yaml.safe_dump(config))
        before = self.config_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "other profile routes"):
            cli.remove_project_registration(self.root, "commerce", revision=hashlib.sha256(before).hexdigest(),
                                            confirmation="commerce")
        self.assertEqual(self.config_path.read_bytes(), before)
        (self.root / "profiles" / "linked").symlink_to(self.root / "profiles" / "commerce", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            cli.remove_project_registration(self.root, "linked", revision=hashlib.sha256(before).hexdigest(),
                                            confirmation="linked")
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertTrue((self.root / "profiles" / "commerce" / "config.yaml").exists())


if __name__ == "__main__":
    unittest.main()
