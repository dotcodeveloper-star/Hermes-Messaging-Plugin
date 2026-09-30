---
name: mattermost-access
description: Use to read or search Mattermost channel threads, follow forwarded post links, post a requested cross-thread notice or new channel thread, send a responsible-person DM, or handle a pending confidential DM reply.
metadata:
  hermes:
    tags: [mattermost, messaging, threads, dm, search]
---

# Mattermost access

Shared contract: `$HERMES_HOME/SOUL.md`. Use the current routed conversation first; the helper reaches other Mattermost posts through the default profile's bot `MATTERMOST_URL`/`MATTERMOST_TOKEN` in `.env` or `platforms.mattermost` in `config.yaml`. It can only read or post where that bot has permission. Loading this skill does not authorize a message.

Use `python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py"` with the commands below. IDs come from trusted Mattermost metadata or same-server permalinks, not display names. Read only channels and threads relevant to the task. A forward or quoted reply is a pointer: follow its original post and thread when accessible, and keep the source context distinct from the forwarding comment.

## Read and explore

```sh
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" thread --post '<post-id-or-permalink>'
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" recent --channel '<channel-id>' --page 0
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" search --channel '<channel-id>' --terms '"exact phrase" from:alice after:2026-09-01'
```

A mention inside a thread already arrives with that thread's root and newest earlier replies as a `Mattermost thread context` block; use `thread` for replies that block omitted, for other threads, and for forwarded links. `thread` returns the root and replies in pages. `search` scopes results to the channel; use Mattermost's `from:`, `before:`, `after:`, `on:`, quoted phrase and exclusion filters, then open relevant results with `thread`. Page through results when needed. `recent` is for browsing without a search term. Search visibility and relevance still govern what to read.

For a Mattermost reference, use the `permalink` returned by `thread` or `post`, or the verified `origin_url` from a GitLab handoff. These links use the configured Mattermost server. Do not write or guess a Mattermost hostname yourself; if no verified permalink is available, cite the post ID without a link.

## Never post to the current routed conversation

The gateway delivers your final reply to the thread, DM or GitLab discussion this session is routed to. `post` there is always a duplicate: the same text will arrive twice. Use `post` only when the destination is a different thread or channel from the one that will receive your final reply, and only when SOUL authorizes it. If you are unsure whether the destination is the current conversation, compare its root post ID with the session's routed thread; when they match, do not post. After a `post` to another thread, your final reply must not repeat that message, only reference it by permalink if needed.

## Notify

For an authorized cross-thread notice, read the source and destination threads, then post a short action and source permalink in the destination thread. Send one post per destination; avoid copying confidential content into a wider audience. For a new channel discussion, omit `--root`. For a reply, supply any post in the target thread; the helper resolves its root and checks the channel.

```sh
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" post --channel '<channel-id>' --root '<target-post-id>' --message '<action and source link>'
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" post --channel '<channel-id>' --message '<new-thread message>'
```

For a responsible-person DM, read `memories/semantic/team.md` and match the specific domain/action to a confirmed PIC. Verify the Mattermost account before sending. If responsibility or identity is unknown, ask the requester or lead in the originating discussion; do not guess a recipient or use `@all`, `@channel`, or `@here`.

```sh
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" send --user '<verified-username-or-id>' --message '<specific action and context link>'
```

## Confidential DM handoff

For a requested secret, choose a profile-local dest with private parent permissions. Name only the items and dest in the DM; keep values out of command arguments, logs and originating channel posts. The DM session writes it; the original work session reads it on a later turn. Acknowledge the DM request in the original thread, then end that turn. Do not poll or hold it open.

```sh
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" request --user '<verified-username-or-id>' --dest '<profile-path>' --keys '<NAME,NAME>' --message 'Mohon kirim <items> di DM ini; saya simpan di <dest>. Setelah itu, balas di thread asal agar kerja lanjut.'
python3 "$HERMES_HOME/../global-project/skills/mattermost-access/scripts/access.py" pending --user '<current-mattermost-user-id>' --channel '<current-chat-id>'
```

Keep the returned request ID and dest. A reply needs a matching pending request. Write supplied material to its dest with file tools (`0600`; merge `.env`), then run `complete --id '<request-id>'`. Acknowledgement names the dest and asks for a reply in the original thread. The original session may use `status --id '<request-id>'` on a later turn.

Missing credentials belong on the default profile. A Cloudflare 1010/403 requires the Mattermost admin to allow this API client/host.
