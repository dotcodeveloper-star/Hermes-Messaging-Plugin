"""Desktop management API. Mounted behind Hermes's existing session/OAuth auth."""
import asyncio
from contextlib import closing, contextmanager
import datetime
import hashlib
import importlib
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
import yaml

from agent.secret_scope import build_profile_secret_scope, set_secret_scope, reset_secret_scope
from gateway.config import GatewayConfig, PlatformConfig
from gateway.config_loader import merge_platform_sections
from gateway.platforms._shared import extra_or_secret
from hermes_constants import get_default_hermes_root, set_hermes_home_override, reset_hermes_home_override
from hermes_cli.profiles import profiles_to_serve, read_profile_meta

# Hermes imports this API as a standalone module. Give relative imports the
# installed package root; never depend on another profile's plugin namespace.
__path__ = [str(Path(__file__).resolve().parent.parent)]
cli = importlib.import_module(__name__ + ".cli")
adapter = importlib.import_module(__name__ + ".adapter")
router = APIRouter()


@contextmanager
def root_scope():
    root = get_default_hermes_root()
    home_token = set_hermes_home_override(root)
    secret_token = None
    try:
        # A missing default-profile credential must not fall through to the
        # backend process's environment, which may belong to another profile.
        secret_token = set_secret_scope({"GITLAB_URL": "", "GITLAB_TOKEN": "",
                                         **build_profile_secret_scope(root)})
        yield root
    finally:
        if secret_token is not None:
            reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)


def settings(root):
    raw = (root / "config.yaml").read_bytes()
    config = cli.read_config(root / "config.yaml", raw=raw)
    extra = PlatformConfig.from_dict(merge_platform_sections(config, config.get("gateway", {}), {}).get("gitlab", {})).extra
    return config, extra, hashlib.sha256(raw).hexdigest()


def connection(extra):
    url = str(extra_or_secret(extra, "url", "GITLAB_URL") or "").rstrip("/")
    token = extra_or_secret(extra, "token", "GITLAB_TOKEN")
    parsed = urlsplit(url)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}))):
        raise HTTPException(409, "Configure an HTTPS GitLab URL in Messaging → GitLab first")
    if not token:
        raise HTTPException(409, "Configure the bot PAT in Messaging → GitLab first")
    return url, str(token)


async def gitlab_get(extra, path, params=None):
    url, token = connection(extra)
    try:
        async with aiohttp.ClientSession(headers={"PRIVATE-TOKEN": token}, timeout=aiohttp.ClientTimeout(total=10)) as client:
            async with client.get(f"{url}/api/v4/{path}", params=params, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    raise HTTPException(502, f"GitLab returned HTTP {response.status}; check the bot's access")
                return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        raise HTTPException(502, "Could not reach GitLab; check the URL, PAT and network") from None


def repository(item, extra):
    try:
        ident = next(iter(cli.ids([item["id"]])))
        name = item["path_with_namespace"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError()
        # Derive links from the configured server and GitLab's encoded namespace.
        from urllib.parse import quote
        url, _ = connection(extra)
        return {"id": ident, "name": name[:1000], "url": url + "/" + quote(name, safe="/")}
    except (KeyError, TypeError, ValueError):
        raise HTTPException(502, "GitLab returned an invalid repository") from None


@contextmanager
def errors():
    try:
        yield
    except yaml.YAMLError:
        raise HTTPException(409, "Invalid YAML in the default profile's config.yaml") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except OSError:
        raise HTTPException(409, "Could not read or save Hermes configuration on this backend") from None


def configured_workers(extra):
    raw = extra_or_secret(extra, "max_workers", "GITLAB_MAX_WORKERS", adapter.DEFAULT_MAX_WORKERS)
    try:
        return adapter.worker_count(raw)
    except (TypeError, ValueError):
        return adapter.DEFAULT_MAX_WORKERS

@router.get("/projects")
def projects():
    with errors(), root_scope() as root:
        config, extra, revision = settings(root)
        routes = [r for r in cli.route_settings(config).get("profile_routes", []) if cli.managed_route(r)]
        info = extra.get("repository_info") or {}
        profiles = {name: path for name, path in profiles_to_serve(True) if name not in cli.RESERVED_PROFILES}
        # Existing managed routes identify legacy projects until their next save stamps metadata.
        names = sorted(({name for name, path in profiles.items() if cli.is_project_profile(path)}
                        | {r["profile"] for r in routes}) - cli.RESERVED_PROFILES)
        rows = []
        for name in names:
            repos = []
            for route in routes:
                if route.get("profile") == name:
                    ident = route["chat_id"].split(":")[1]
                    repos.append({"id": ident, "name": info.get(ident, {}).get("name", f"Repository {ident}"),
                                  "url": info.get(ident, {}).get("url"), "enabled": route.get("enabled", True)})
            rows.append({"profile": name, "profile_type": "project", "available": name in profiles,
                         "description": read_profile_meta(profiles[name])["description"] if name in profiles else "",
                         "repositories": sorted(repos, key=lambda r: r["name"].casefold())})
        try:
            url, _ = connection(extra)
            configured = True
        except HTTPException:
            url, configured = "", False
        events = load_events(root)
        latest = {}
        open_count = 0
        for event in events:
            if event["status"] != "delivered":
                open_count += 1
            profile = event.get("profile")
            if profile and profile not in latest:
                latest[profile] = compact_event(event)
        latest_session = {}
        sessions = load_sessions(root)
        by_profile = {}
        for session in sessions:
            profile = session.get("profile")
            if not profile:
                continue
            if profile not in latest_session:
                latest_session[profile] = compact_session(session)
            by_profile.setdefault(profile, []).append(session)
        for row in rows:
            cost, status = session_cost_summary(by_profile.get(row["profile"]) or [])
            row["last_event"] = latest.get(row["profile"])
            row["last_session"] = latest_session.get(row["profile"])
            row["cost_usd"] = cost
            row["cost_status"] = status
            for key in ("input_tokens", "output_tokens"):
                row[key] = sum(session[key] for session in by_profile.get(row["profile"], []))
        return {"projects": rows, "revision": revision, "url": url, "connection_configured": configured,
                "multiplex_enabled": GatewayConfig.from_dict(config).multiplex_profiles,
                "poll_interval": extra.get("poll_interval", 30),
                "max_workers": configured_workers(extra), "transport": "polling",
                "open_count": open_count, "session_count": len(sessions)}


def inbox_path(root):
    folder = Path(root) / "gitlab"
    if not folder.is_dir():
        return None
    files = [path for path in folder.glob("*.sqlite3") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def command_from(todo):
    body = todo.get("body")
    if todo.get("action_name") not in {"mentioned", "directly_addressed"} or not isinstance(body, str):
        return None
    match = re.fullmatch(r"\s*@\S+[ \t]+(/[a-z][a-z0-9-]*(?:[ \t]+[^\r\n]+)?)[ \t]*", body, re.I)
    return match[1].strip() if match else None


def event_status(completed, last_error):
    if completed:
        return "delivered"
    return "retrying" if last_error else "pending"


def compact_event(event):
    return {key: event[key] for key in ("id", "status", "created_at", "kind", "iid", "target_type", "repository")
            if key in event}


def public_event(ident, payload, completed, attempts, last_error, routes, info, delivery):
    todo = json.loads(payload)
    if not isinstance(todo, dict):
        raise ValueError("invalid to-do")
    project = todo.get("project") if isinstance(todo.get("project"), dict) else {}
    target = todo.get("target") if isinstance(todo.get("target"), dict) else {}
    author = todo.get("author") if isinstance(todo.get("author"), dict) else {}
    project_id = str(project.get("id") or "")
    if not re.fullmatch(r"[1-9][0-9]*", project_id):
        raise ValueError("invalid project")
    resource = {"Issue": "issues", "MergeRequest": "merge_requests"}.get(todo.get("target_type"))
    iid = str(target.get("iid") or "")
    repo = info.get(project_id) or {}
    name = repo.get("name") or project.get("path_with_namespace") or f"Repository {project_id}"
    if not isinstance(name, str) or not name.strip():
        name = f"Repository {project_id}"
    command = command_from(todo)
    action = todo.get("action_name")
    kind = command or ("assignment" if action == "assigned" else "mention")
    username = author.get("username") or author.get("id") or ""
    return {
        "id": str(ident),
        "created_at": str(todo.get("created_at") or "")[:40],
        "profile": routes.get(project_id),
        "repository": {"id": project_id, "name": name[:1000], "url": repo.get("url")},
        "action": action if action in {"mentioned", "directly_addressed", "assigned"} else None,
        "target_type": todo.get("target_type") if todo.get("target_type") in {"Issue", "MergeRequest"} else None,
        "iid": iid if re.fullmatch(r"[1-9][0-9]*", iid) else "",
        "title": str(target.get("title") or "")[:1000],
        "author": str(username)[:200],
        "body": str(todo.get("body") or "")[:20000],
        "status": event_status(completed, last_error),
        "attempts": int(attempts or 0),
        "last_error": last_error,
        "card": f"{project_id}:{resource}:{iid}" if resource and re.fullmatch(r"[1-9][0-9]*", iid) else None,
        "conversation": delivery.get("conversation") if isinstance(delivery, dict) else None,
        "discussion": delivery.get("discussion") if isinstance(delivery, dict) else None,
        "command": command,
        "kind": kind,
    }


def load_events(root):
    path = inbox_path(root)
    if path is None:
        return []
    config, extra, _ = settings(root)
    routes = {r["chat_id"].split(":")[1]: r["profile"]
              for r in cli.route_settings(config).get("profile_routes", []) if cli.managed_route(r)}
    info = extra.get("repository_info") or {}
    try:
        database = sqlite3.connect(path, timeout=2)
    except sqlite3.Error:
        return []
    try:
        rows = database.execute(
            "SELECT id, payload, completed, attempts, last_error FROM inbox ORDER BY id DESC").fetchall()
        deliveries = {}
        for ident, *_ in rows:
            row = database.execute("SELECT value FROM meta WHERE key = ?", (f"delivery:todo:{ident}",)).fetchone()
            if row:
                try:
                    deliveries[ident] = json.loads(row[0])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
        events = []
        for ident, payload, completed, attempts, last_error in rows:
            try:
                events.append(public_event(ident, payload, completed, attempts, last_error, routes, info,
                                           deliveries.get(ident)))
            except (TypeError, ValueError, json.JSONDecodeError, KeyError):
                continue
        return events
    except sqlite3.Error:
        return []
    finally:
        database.close()


@router.get("/events")
def events(profile: str = Query("", max_length=64), status: str = Query("", max_length=20),
           q: str = Query("", max_length=200), page: int = Query(1, ge=1, le=10000)):
    with errors(), root_scope() as root:
        rows = load_events(root)
        needle = q.strip().casefold()
        filtered = []
        for event in rows:
            if profile and event.get("profile") != profile:
                continue
            if status == "open":
                if event["status"] == "delivered":
                    continue
            elif status and event["status"] != status:
                continue
            if needle:
                hay = " ".join([
                    event.get("profile") or "", event["repository"]["name"], event.get("title") or "",
                    event.get("author") or "", event.get("body") or "", event.get("iid") or "",
                    event.get("kind") or "",
                ]).casefold()
                if needle not in hay:
                    continue
            filtered.append(event)
        per_page = 50
        start = (page - 1) * per_page
        chunk = filtered[start:start + per_page]
        return {"events": chunk, "next_page": page + 1 if start + per_page < len(filtered) else None,
                "open_count": sum(1 for event in rows if event["status"] != "delivered")}

SESSION_COLUMNS = (
    "id", "source", "title", "chat_id", "origin_json", "model", "billing_provider",
    "actual_cost_usd", "estimated_cost_usd", "cost_status",
    "input_tokens", "output_tokens", "message_count",
    "started_at", "ended_at", "last_activity_at", "archived", "hidden",
)

_LIST_PRICE_PROVIDERS = ("openai", "anthropic", "google", "fireworks", "minimax")
_LIST_PRICE_ALIASES = {
    "openai-codex": "openai", "openai-api": "openai", "codex": "openai",
    "google-gemini": "google", "gemini": "google", "vertex": "google",
}


def iso_from_unix(value):
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(value):
    try:
        return None if value is None else round(float(value), 6)
    except (TypeError, ValueError):
        return None

def list_price_usd(model, provider, input_tokens, output_tokens):
    if not model or (not input_tokens and not output_tokens):
        return None
    try:
        from decimal import Decimal
        from agent.usage_pricing import BillingRoute, _lookup_official_docs_pricing, _OFFICIAL_DOCS_PRICING
    except Exception:
        return None
    bare = str(model).strip().split("/")[-1]
    if not bare:
        return None
    mapped = _LIST_PRICE_ALIASES.get((provider or "").strip().lower(), (provider or "").strip().lower())
    entry = _lookup_official_docs_pricing(BillingRoute(provider=mapped or "openai", model=bare)) if mapped else None
    if not entry or not (entry.input_cost_per_million or entry.output_cost_per_million):
        entry = None
        for name in ((mapped,) if mapped else ()) + _LIST_PRICE_PROVIDERS:
            if not name:
                continue
            candidate = _OFFICIAL_DOCS_PRICING.get((name, bare.lower()))
            if candidate and (candidate.input_cost_per_million or candidate.output_cost_per_million):
                entry = candidate
                break
        if entry is None:
            return None
    amount = Decimal(0)
    million = Decimal("1000000")
    if entry.input_cost_per_million is not None and input_tokens:
        amount += Decimal(input_tokens) * entry.input_cost_per_million / million
    if entry.output_cost_per_million is not None and output_tokens:
        amount += Decimal(output_tokens) * entry.output_cost_per_million / million
    if amount <= 0:
        return None
    return round(float(amount), 6)


def as_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def row_get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def parse_card(chat_id):
    if not isinstance(chat_id, str):
        return "", None, "", None
    parts = chat_id.split(":")
    if len(parts) != 3:
        return "", None, "", None
    project_id, resource, iid = parts
    target_type = {"issues": "Issue", "merge_requests": "MergeRequest"}.get(resource)
    if not target_type or not re.fullmatch(r"[1-9][0-9]*", project_id) or not re.fullmatch(r"[1-9][0-9]*", iid):
        return "", None, "", None
    return project_id, target_type, iid, f"{project_id}:{resource}:{iid}"


def compact_session(session):
    return {key: session[key] for key in (
        "id", "title", "last_activity_at", "cost_usd", "cost_status", "card", "iid",
        "target_type", "repository", "input_tokens", "output_tokens") if key in session}

def session_cost_summary(rows):
    total = 0.0
    estimated = False
    for session in rows:
        try:
            total += float(session.get("cost_usd") or 0)
        except (TypeError, ValueError):
            continue
        if session.get("cost_status") in {"included", "estimated"}:
            estimated = True
    return round(total, 6), ("estimated" if estimated else None)


def public_session(profile, row, info):
    origin = {}
    raw_origin = row_get(row, "origin_json")
    if isinstance(raw_origin, str) and raw_origin.strip():
        try:
            parsed = json.loads(raw_origin)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            origin = parsed
    chat_id = origin.get("chat_id") or row_get(row, "chat_id") or ""
    if not isinstance(chat_id, str):
        chat_id = ""
    project_id, target_type, iid, card = parse_card(chat_id)
    if not project_id:
        parent = origin.get("parent_chat_id")
        if isinstance(parent, str) and parent.startswith("repo:"):
            candidate = parent.split(":", 1)[1]
            if re.fullmatch(r"[1-9][0-9]*", candidate):
                project_id = candidate
    repo = info.get(project_id) or {}
    name = repo.get("name")
    if not isinstance(name, str) or not name.strip():
        name = f"Repository {project_id}" if project_id else ""
    actual = money(row_get(row, "actual_cost_usd"))
    estimated = money(row_get(row, "estimated_cost_usd"))
    input_tokens = as_int(row_get(row, "input_tokens"))
    output_tokens = as_int(row_get(row, "output_tokens"))
    cost = actual if actual else (estimated if estimated else 0.0)
    if not cost:
        cost = list_price_usd(row_get(row, "model"), row_get(row, "billing_provider"),
                              input_tokens, output_tokens) or 0.0
    title = row_get(row, "title")
    if not isinstance(title, str) or not title.strip():
        title = None
    else:
        title = title.strip()[:1000]
    cost_status = row_get(row, "cost_status")
    if not isinstance(cost_status, str) or not cost_status.strip():
        cost_status = None
    else:
        cost_status = cost_status.strip()[:40]
    author = origin.get("user_name") or origin.get("user_id") or ""
    model = row_get(row, "model")
    repository = None
    if project_id:
        repository = {"id": project_id, "name": name[:1000], "url": repo.get("url")}
    return {
        "id": str(row_get(row, "id") or ""),
        "profile": profile,
        "title": title,
        "source": "gitlab",
        "model": str(model)[:200] if model else None,
        "cost_usd": cost,
        "cost_status": cost_status,
        "actual_cost_usd": actual,
        "estimated_cost_usd": estimated,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "message_count": as_int(row_get(row, "message_count")),
        "started_at": iso_from_unix(row_get(row, "started_at")),
        "last_activity_at": iso_from_unix(row_get(row, "last_activity_at") or row_get(row, "started_at")),
        "ended_at": iso_from_unix(row_get(row, "ended_at")) or None,
        "repository": repository,
        "card": card,
        "target_type": target_type,
        "iid": iid,
        "author": str(author)[:200] if author else "",
        "conversation": chat_id or None,
    }


def load_sessions(root):
    config, extra, _ = settings(root)
    routes = [r for r in cli.route_settings(config).get("profile_routes", []) if cli.managed_route(r)]
    info = extra.get("repository_info") or {}
    profiles = {name: path for name, path in profiles_to_serve(True) if name not in cli.RESERVED_PROFILES}
    names = sorted(({name for name, path in profiles.items() if cli.is_project_profile(path)}
                    | {r["profile"] for r in routes if r.get("profile")}) - cli.RESERVED_PROFILES)
    sessions = []
    for name in names:
        try:
            path = Path(cli.get_profile_dir(name)) / "state.db"
        except (TypeError, ValueError, OSError):
            continue
        if not path.is_file():
            continue
        try:
            database = sqlite3.connect(str(path), timeout=2)
        except sqlite3.Error:
            continue
        try:
            database.row_factory = sqlite3.Row
            database.execute("PRAGMA query_only=ON")
            cols = {row[1] for row in database.execute("PRAGMA table_info(sessions)")}
            if "id" not in cols or "source" not in cols:
                continue
            select = [col for col in SESSION_COLUMNS if col in cols]
            where = ["source = 'gitlab'"]
            if "hidden" in cols:
                where.append("IFNULL(hidden, 0) = 0")
            if "archived" in cols:
                where.append("IFNULL(archived, 0) = 0")
            if "last_activity_at" in cols and "started_at" in cols:
                order_sql = "COALESCE(last_activity_at, started_at) DESC"
            elif "last_activity_at" in cols:
                order_sql = "last_activity_at DESC"
            elif "started_at" in cols:
                order_sql = "started_at DESC"
            else:
                order_sql = "rowid DESC"
            sql = (f"SELECT {', '.join(select)} FROM sessions WHERE {' AND '.join(where)} "
                   f"ORDER BY {order_sql} LIMIT 500")
            for row in database.execute(sql):
                try:
                    session = public_session(name, row, info)
                except (TypeError, ValueError, KeyError):
                    continue
                if session.get("id"):
                    sessions.append(session)
        except sqlite3.Error:
            continue
        finally:
            database.close()
    sessions.sort(key=lambda session: session.get("last_activity_at") or "", reverse=True)
    return sessions


def load_activity(root, year, month, timezone):
    config, extra, _ = settings(root)
    routes = [r for r in cli.route_settings(config).get("profile_routes", []) if cli.managed_route(r)]
    profiles = {name: path for name, path in profiles_to_serve(True) if name not in cli.RESERVED_PROFILES}
    names = sorted(({name for name, path in profiles.items() if cli.is_project_profile(path)}
                    | {r["profile"] for r in routes if r.get("profile")}) - cli.RESERVED_PROFILES)
    start = datetime.datetime(year, month or 1, 1, tzinfo=timezone).timestamp()
    following = (datetime.datetime(year + 1, 1, 1, tzinfo=timezone) if month is None else
                 datetime.datetime(year + (month == 12), month % 12 + 1, 1,
                                   tzinfo=timezone)).timestamp()
    days = {}
    for name in names:
        try:
            path = Path(cli.get_profile_dir(name)) / "state.db"
            if not path.is_file():
                continue
            with closing(sqlite3.connect(str(path), timeout=2)) as database:
                database.row_factory = sqlite3.Row
                database.execute("PRAGMA query_only=ON")
                columns = {row[1] for row in database.execute("PRAGMA table_info(sessions)")}
                message_columns = {row[1] for row in database.execute("PRAGMA table_info(messages)")}
                if not {"id", "source", "started_at"} <= columns or not {"session_id", "role", "timestamp"} <= message_columns:
                    continue
                select = ", ".join(col for col in SESSION_COLUMNS if col in columns)
                where = ["source = 'gitlab'", "started_at < ?",
                         "COALESCE(last_activity_at, started_at) >= ?" if "last_activity_at" in columns else "started_at >= ?"]
                if "hidden" in columns:
                    where.append("IFNULL(hidden, 0) = 0")
                if "archived" in columns:
                    where.append("IFNULL(archived, 0) = 0")
                for session in database.execute(f"SELECT {select} FROM sessions WHERE {' AND '.join(where)}",
                                                (following, start)):
                    try:
                        stamps = {float(row[0]) for row in database.execute(
                            "SELECT CAST(timestamp AS REAL) FROM messages WHERE session_id = ? AND role = 'assistant'",
                            (session["id"],)) if row[0] is not None and row[0] > 0}
                        if not stamps:
                            continue
                        cost = public_session(name, session, extra.get("repository_info") or {})["cost_usd"]
                    except (sqlite3.Error, TypeError, ValueError, KeyError):
                        continue
                    for stamp in stamps:
                        if start <= stamp < following:
                            date = datetime.datetime.fromtimestamp(stamp, timezone).date().isoformat()
                            day = days.setdefault(date, {"date": date, "responses": 0, "cost_usd": 0.0})
                            day["responses"] += 1
                            day["cost_usd"] += cost / len(stamps)
        except (sqlite3.Error, TypeError, ValueError, OSError):
            continue
    return [{**days[date], "cost_usd": round(days[date]["cost_usd"], 6)} for date in sorted(days)]


@router.get("/activity")
def activity(year: int = Query(..., ge=2000, le=2100), month: int | None = Query(None, ge=1, le=12),
             timezone: str = Query("UTC", max_length=64)):
    try:
        zone = ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise HTTPException(status_code=422, detail="Invalid timezone")
    with errors(), root_scope() as root:
        return {"days": load_activity(root, year, month, zone)}


@router.get("/sessions")
def sessions(profile: str = Query("", max_length=64), q: str = Query("", max_length=200),
             page: int = Query(1, ge=1, le=10000)):
    with errors(), root_scope() as root:
        rows = load_sessions(root)
        needle = q.strip().casefold()
        filtered = []
        for session in rows:
            if profile and session.get("profile") != profile:
                continue
            if needle:
                repo = (session.get("repository") or {}).get("name") or ""
                hay = " ".join([
                    session.get("profile") or "", session.get("title") or "",
                    session.get("author") or "", session.get("iid") or "",
                    session.get("card") or "", session.get("conversation") or "",
                    session.get("model") or "", repo,
                ]).casefold()
                if needle not in hay:
                    continue
            filtered.append(session)
        per_page = 50
        start = (page - 1) * per_page
        chunk = filtered[start:start + per_page]
        cost, status = session_cost_summary(filtered)
        return {"sessions": chunk, "next_page": page + 1 if start + per_page < len(filtered) else None,
                "session_count": len(rows), "cost_usd": cost, "cost_status": status,
                "input_tokens": sum(s["input_tokens"] for s in filtered),
                "output_tokens": sum(s["output_tokens"] for s in filtered)}


@router.get("/repositories")
async def repositories(q: str = Query("", max_length=200), page: int = Query(1, ge=1, le=10000)):
    with errors(), root_scope() as root:
        _, extra, _ = settings(root)
        items = await gitlab_get(extra, "projects", {"search": q, "page": page, "per_page": 50,
                                                    "order_by": "id", "sort": "asc", "archived": "false"})
        if not isinstance(items, list):
            raise HTTPException(502, "GitLab returned an invalid repository list")
        return {"repositories": [repository(item, extra) for item in items],
                "next_page": page + 1 if len(items) == 50 else None}


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repositories: list[str] = Field(max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def model_setup(path):
    """Expose only model display fields from the copied starter configuration.

    Native profile cloning preserves settings and reuses shared rotating OAuth logins.
    """
    try:
        from hermes_cli.config import read_user_config_raw, split_model_config_default
        model = read_user_config_raw(path / "config.yaml").get("model") or {}
        if isinstance(model, str):
            name, provider = split_model_config_default(model)
        else:
            name, provider = split_model_config_default(model.get("default") or model.get("model"))
            provider = str(model.get("provider") or provider or "").strip()
        return {"model": name or "", "provider": provider or "auto"}
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        return {"model": "", "provider": ""}


@router.post("/gateway/restart")
async def restart_gateway():
    with errors(), root_scope() as root:
        config, _, _ = settings(root)
        if not GatewayConfig.from_dict(config).multiplex_profiles:
            raise HTTPException(409, "Enable the default profile's multiplex gateway before restarting")
        from hermes_cli import web_server
        # A recent restart may already have read the OLD mapping. Respect the
        # native cooldown, then request a fresh restart for this saved config.
        recent = web_server._LAST_GATEWAY_RESTART
        if recent:
            delay = web_server.GATEWAY_RESTART_COOLDOWN_SECONDS - (time.monotonic() - recent[0])
            if delay > 0:
                await asyncio.sleep(delay + 0.05)
        from hermes_cli.web_server_gateway import _restart_gateway_after
        result = await asyncio.to_thread(_restart_gateway_after, "default",
            what="GitLab project registration", label="GitLab Projects")
        # Native errors can contain process paths or environment details.
        if not result.get("restart_started"):
            return {"restart_started": False}
        return {"restart_started": True, "restart_pid": result["restart_pid"]}


@router.get("/gateway/restart/status")
async def restart_status(pid: int = Query(ge=1)):
    from hermes_cli.web_routers.actions import get_action_status
    result = await get_action_status("gateway-restart", lines=1)
    # Another action may have replaced the shared native restart record.
    status = "unknown"
    if result.get("pid") == pid:
        if result["running"]:
            status = "running"
        elif result["exit_code"] is not None:
            status = "finished" if result["exit_code"] == 0 else "failed"
    return {"status": status}


@router.put("/projects/{project_name}")
async def save_project(project_name: str, mapping: Mapping):
    with errors(), root_scope() as root:
        _, extra, revision = settings(root)
        if mapping.revision != revision:
            raise HTTPException(409, "Configuration changed; refresh the project list before saving")
        ids = cli.ids(mapping.repositories) if mapping.repositories else set()
        info = {}
        # ponytail: sequential verification caps GitLab pressure; batch if onboarding hundreds of repos is slow.
        for ident in sorted(ids, key=int):
            row = repository(await gitlab_get(extra, f"projects/{ident}"), extra)
            if row["id"] != ident:
                raise HTTPException(502, "GitLab returned a different repository")
            info[ident] = row
        name, path, created = await asyncio.to_thread(cli.add_project, root, project_name, mapping.repositories,
            mapping.description, replace=True, revision=mapping.revision, repository_info=info,
            require_project_profile=True)
        setup = model_setup(path)
        # Saving is authoritative even when the native restart cannot be started.
        try:
            restart = await restart_gateway()
        except Exception:
            restart = {"restart_started": False}
        return {"profile": name, "created": created, "model_setup": setup, **restart}


class DeleteMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation: str = Field(min_length=1, max_length=64)


@router.delete("/projects/{project_name}")
async def delete_project(project_name: str, mapping: DeleteMapping):
    with errors(), root_scope() as root:
        name, required = await asyncio.to_thread(cli.remove_project_registration, root, project_name,
            revision=mapping.revision, confirmation=mapping.confirmation)
        return {"profile": name, "profile_delete_required": required, "restart_required": True}
