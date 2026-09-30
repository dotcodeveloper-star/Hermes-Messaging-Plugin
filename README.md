# Hermes GitLab messaging · 0.3.33

GitLab mentions and issue assignments reach Hermes through **outbound polling**
with a bot account PAT. **GitLab Projects** appears below **Kanban** in Hermes
Desktop. **Projects** registers repositories to Hermes project profiles.
**Sessions** lists GitLab-triggered Hermes sessions — globally or for one project —
with a rough cost-based usage percentage of a Pro 5x week. Token counts remain in session details.
**Heatmap** shows a compact year of daily GitLab assistant activity with full weekday labels; future dates are disabled.

One business project = one named Hermes profile. Multiple GitLab repositories
share that profile's knowledge; each GitLab issue or standalone merge request
keeps one conversation across comments and discussions. One default-profile gateway owns the shared
GitLab connection and uses Hermes's native multiplex router.

This replaces the earlier webhook transport. **No webhook secret, per-repository
webhooks, public listener, or tunnel is needed.** Replies are comments on the
originating issue/MR. Assignment means assigning the bot account to an issue;
moving a card between board columns does not trigger a reply.

## Replies in GitLab

Session identity is the repository ID plus issue/MR number, independent of the
comment, discussion, event ID, or sender. A related MR continues the issue's session
when both repositories belong to the same Hermes profile. The plugin uses GitLab's
[closing and related issue APIs](https://docs.gitlab.com/api/merge_requests/): a single
closing issue takes priority; otherwise a single related issue is used. Multiple
candidate issues, unregistered repositories, or different profiles keep the MR
separate. Relationship API failures retry the event instead of starting a separate
conversation. GitLab references such as `Closes #3` and `Related to #3` establish
these relationships; matching titles or branch names alone do not.

Existing card sessions are reused. For sessions split by older versions, the most
recent issue discussion is resumed when no card session exists. When an MR gains
an issue link later, the issue session takes priority; if the issue has none, the
existing MR transcript is resumed. Separate old transcripts remain available and
are not concatenated. Hermes's normal explicit reset and idle-reset policies still
apply. Conversation turns are serialized, including issue/MR turns sharing a session.

Comment mentions reply inside the original issue/MR discussion, including mentions
on ordinary single comments. The plugin finds the to-do item's `#note_ID` in the
card's paginated discussions and uses GitLab's [discussion reply API](https://docs.gitlab.com/api/discussions/).
Missing or inaccessible source comments remain retryable; their replies are never
silently redirected to another discussion.

Description mentions and issue assignments have no comment anchor. Those responses
create or continue a bot discussion on the card. Its ID survives gateway restarts.

The native home-channel prompt and Codex auto-compaction tuning notice are hidden
on GitLab by default. Actual answers (including quoted notices), failures and
approval messages still pass through. The platform prompt also asks the agent to
answer the project request directly and skip generic onboarding invitations.

Codev project profiles disable reasoning, tool-progress messages and long-running
heartbeats (`⏳ Working — N min`). Interim replies remain enabled for the single
short preamble required by SOUL; subsequent narration is suppressed by that
instruction. This is not a transport-level limit on interim messages.

## Install

### Backend

Install from GitHub so the plugin directory is a git checkout (required for
`hermes plugins update hermes-gitlab`):

```sh
hermes -p default plugins install nemixe/Hermes-Messaging-Plugin --force --enable
hermes -p default config set gateway.multiplex_profiles true
hermes -p default config set plugins.entries.hermes-gitlab.allow_gateway_injection true
hermes -p default gateway restart
```

`allow_gateway_injection` lets a GitLab issue session's report continue the Mattermost
thread session it came from (see **Reports continue the origin thread session**).
Without it, reports are posted to the thread as plain messages, as in earlier releases.

`plugin.yaml` is at the repository root. Do not append `/hermes-gitlab` or
`#hermes-gitlab` — those install only a subdirectory and drop `.git`, so update
cannot pull.

After installing or updating, fully quit and reopen Hermes Desktop to reload its
backend API and UI. If you previously copied a standalone Desktop UI, refresh it:

```sh
cp ~/.hermes/plugins/hermes-gitlab/desktop/plugin.js ~/.hermes/desktop-plugins/hermes-gitlab/plugin.js
```

Later:

```sh
hermes -p default plugins update hermes-gitlab
hermes -p default gateway restart
```

For a source checkout, clone this repository into `~/.hermes/plugins/hermes-gitlab`.
No additional dependencies are required in the tested unmodified Hermes runtime
(`64a9b43261`). Desktop must include upstream route fix `6fc7032aac` (#109063);
the version label alone is insufficient because different builds share it.
This is a native Hermes plugin and does not require edits to Hermes core.

### Configure the bot

In **Messaging → GitLab** on the default backend, enter:

- **GITLAB_URL**: self-hosted GitLab HTTPS base URL, including any installation subpath.
- **GITLAB_TOKEN**: bot account PAT with `api` scope.
- **GITLAB_ALLOWED_USERS**: comma-separated numeric IDs of users permitted to trigger Hermes,
  or `*` to allow everyone who can mention or assign the bot in registered repositories.

Wildcard support requires plugin 0.3.1 or later. Save `*` in the default profile's
Messaging → GitLab settings, then restart the default messaging gateway. This grants
trigger access only within the registered repository list; it does not grant GitLab
repository permissions. Empty values remain invalid. The bot's own mentions are ignored; assigning an issue to itself starts the Mattermost handoff into a GitLab coding session.

The bot must be able to read repositories/issues/MRs, post comments, and be
assigned issues. Hermes discovers its username using `/api/v4/user`. Credentials
belong to the **default profile**, not each project. `GITLAB_PROJECTS` is unnecessary
when using the management page.

The management page saves repository IDs and profile routes. No YAML editing is
required for that. Optional settings in the default profile's existing `config.yaml`
can set the polling interval or start the connector idle before onboarding:

```yaml
gateway:
  multiplex_profiles: true
platforms:
  gitlab:
    enabled: true
    typing_indicator: false
    gateway_restart_notification: false
    extra:
      projects: []
      require_profile_route: true
      poll_interval: 30
      max_workers: 5
```

`poll_interval` is seconds, minimum 5. The empty repository list lets the poller
start idle before onboarding. The page/CLI manages this list after that.

`max_workers` is how many different GitLab cards may run at once. The default is 5,
and the allowed range is 1–64. The same setting is **Concurrent workers** in
**Messaging → GitLab**, saved as `GITLAB_MAX_WORKERS`. That value wins over
`max_workers` in this file. Leave the field empty to use 5. Mention and assignment
requests beyond the cap stay in the inbox until a worker finishes; the next free slot
starts the oldest waiting card without waiting for another poll. One issue or MR
remains one conversation. Commands such as `/status` and `/stop` are not held by
this cap. Restart the messaging gateway after changing it.

Remove legacy `GITLAB_PROJECTS`, `GITLAB_WEBHOOK_SECRET`, `GITLAB_LISTEN_HOST`, and
`GITLAB_LISTEN_PORT` settings when upgrading. Old GitLab webhooks can be removed;
this release exposes no webhook endpoint.

HTTPS verification stays enabled. Install your internal CA in the runtime's trust
store if needed. HTTP is allowed only for loopback local testing.

### Desktop interface

If Desktop runs **on the same machine as the backend**, the unified package contributes its Desktop
half automatically. Enable **GitLab Projects** in **Capabilities → Plugins**.

If Desktop runs **on a different machine**, also copy the extracted package's UI file there:

```sh
mkdir -p ~/.hermes/desktop-plugins/hermes-gitlab
cp desktop/plugin.js ~/.hermes/desktop-plugins/hermes-gitlab/plugin.js
```

Enable it in **Capabilities → Plugins**; use **Reload desktop plugins** from the
command palette if necessary. Select the **backend connection and its default profile** in Desktop.
Calls use the active backend's authenticated connection. The Desktop UI stores no PAT.

Restart/reconnect the Hermes Desktop backend after installing the Python
package so it mounts the plugin API. This backend is separate from the messaging
gateway. A missing API error usually means the backend needs restarting or the
plugin has not been enabled in its default profile. A standalone backend launched
for a named profile may not mount default-only plugins; use the default profile
for this shared connection management page.

## Manage projects

Open **GitLab Projects** below **Kanban**. **Projects** is the registry; click a
row for repositories, recent sessions, and edit/delete. **Sessions** lists GitLab
sessions for all projects or one project. Its percentage column and session detail
divide each session's USD estimate by the weekly share of the $100/month Pro 5x
price (~$23.08/week), then scale the result to one-third. This rough calibration
maps an observed ~$13.79 day from ~60% price ratio to ~20% estimated weekly use;
it is not measured subscription quota. Click a row for tokens, related project,
card, and the option to open it.
**Heatmap** uses local calendar days and a year filter. Hover or focus a day to see its assistant
response count, estimated token cost, and the calibrated weekly percentage. Hermes
stores cost per session, so the heatmap divides each session's cost equally among
its assistant responses; daily amounts are approximate.

1. Select an existing profile, or create a new project/profile with a name and description.
2. Search repositories accessible to the bot and select **Save and activate**.
3. New profiles copy the `project-egg` starter: prompts, skills and their assets,
   SOUL, configuration, and starter memory. Each project receives its own copy.
   Existing project settings and knowledge stay intact when editing registrations.
4. Saving restarts the **default messaging gateway on the selected backend** to load
   the repository mappings. All bots on that shared gateway briefly pause.
5. The page shows the model selection and restart result separately. A failed restart
   keeps your saved registration; **Retry gateway restart** retries activation only.

If `project-egg` has no model selected, the page offers the native setup
command. The model summary reports the saved selection; it does not make a paid
model call or verify provider connectivity. Provider credentials stored only in the
default `.env` are not copied into project profiles; use Hermes's shared provider
login or configure that provider in the project when needed.

### Project starter: project-egg

GitLab Projects lists project profiles only. Creating a project or explicitly
registering a profile with `hermes -p default gitlab add-project` stores
`hermes_gitlab_project: true` in that profile's `profile.yaml`, preserving its other
metadata. The marker keeps projects visible when they have no repositories.
Existing managed GitLab routes also identify older projects; saving stamps their
marker. Ordinary profiles, `default`, `project-egg`, and `global-project` are excluded.
The detail view displays the **Project profile ID** used by the repository mapping.
Creating a project in Desktop cannot silently reuse an unrelated profile name.

The editable starter ships inside the plugin at `templates/project-egg/`:

```text
templates/project-egg/
├── config.yaml
├── SOUL.md
├── TAXONOMY.md
├── memories/
├── prompts/
└── skills/
```

When the enabled plugin first loads on the default backend, it copies this folder
into `~/.hermes/profiles/project-egg/`. The template is installed atomically and
existing `project-egg` customizations are preserved on reload or update. The bundled
template defaults to `gpt-6-sol` through `openai-codex`; new projects copy the installed
starter's model selection. Other default-profile files are not imported.

### Shared Bitwarden secrets for project profiles

Hermes already supports Bitwarden **Secrets Manager** as a profile secret source.
Create a Secrets Manager project containing keys named for the environment variables
the project profiles need (for example, `ANTHROPIC_API_KEY`). Give a machine account
read access to that project, then configure the `project-egg` starter on the
backend that runs the gateway:

```sh
hermes -p project-egg secrets bitwarden setup
hermes -p project-egg secrets bitwarden status
```

Use the full **Secrets Manager machine account access token** from its
**Access tokens** tab, not a Password Manager API key. The token starts with
`0.`; a different token cannot decrypt the shared project.

The setup wizard saves `secrets.bitwarden.project_id` and `enabled: true` in
`project-egg/config.yaml`, and the machine account's `BWS_ACCESS_TOKEN` in its
owner-only `.env`. New GitLab project profiles clone both files. For existing
project profiles, run the same setup command with each profile name, then restart
the default gateway. Run setup on each Hermes backend, including Mac Mini; the
configuration and bootstrap token do not sync between machines. Keep the token
out of the distributed plugin template.
The GitLab bot PAT still belongs to the default profile's Messaging settings.

Installation also creates `~/.hermes/profiles/global-project/` as a shared skills
profile. Bundled `codev-workflow`, `tunnel-preview`, `close-worktree`,
`mattermost-access`, `caveman` and `ponytail` skills, plus the `superpowers/` skill set, are seeded from `templates/global-project/skills/`. Put additional
shared skills in `global-project/skills/<skill-name>/SKILL.md`, or one level under a
category directory such as `superpowers/`. The
plugin merges `../global-project/skills` into `project-egg`'s
`skills.external_dirs`, preserving other skill directories and settings. New
projects inherit this reference, so shared skills stay in one place. Existing
project configurations gain this reference when running `gitlab sync-knowledge`.
The relative path resolves from each
profile's home, including on another backend. Reloading preserves shared profile
files and avoids duplicate entries. Neither starter nor shared profile can be
registered or deleted through GitLab Projects.

`caveman` (from JuliusBrussee/caveman) is the shared reply-brevity skill. Reply
style is controlled only through each profile's SOUL.md and this skill; the CLI
no longer injects brevity lines into SOUL.md during sync.

`ponytail` (from DietrichGebert/ponytail) is the shared lazy-senior-dev coding
skill: YAGNI, stdlib first, the shortest solution that works.

`superpowers/` is a verbatim copy of the obra/superpowers 6.4.1 skills. It is kept
under a category directory because Hermes seeds its own `test-driven-development`,
`systematic-debugging` and `requesting-code-review` into every profile and refuses
a bare name that matches both; `skill_view("superpowers/<name>")` (and the
`superpowers:<name>` references inside the skills) resolve unambiguously.
`codev-workflow` wires them per state: `brainstorming` → `writing-plans` in
Planning (the plan lands in the GitLab card, not a file), and `using-git-worktrees` → `executing-plans` →
`test-driven-development` → `requesting-code-review` →
`finishing-a-development-branch` in Working.

`tunnel-preview` handles requested temporary public previews: one Pinggy SSH tunnel
per web/API service, temporary application URL/origin environment settings, public
verification and restoration on stop. It keeps preview state in the active project
and does not start tunnels merely by installing or syncing the skill.

`/close-worktree` removes a selected linked worktree after shutting down its
dedicated app processes, preview tunnels and Docker dependencies. It verifies
ownership, preserves shared infrastructure and volumes, and stops on unresolved
work/data or shutdown failures. Creating or syncing the skill performs no cleanup.
CoDev creates issue worktrees with native `git worktree add`. `close-worktree`
checks the current request, Git registration, issue/branch identity and live runtime
evidence before shutdown or removal. A matching issue number alone is insufficient;
open cards retain their worktrees unless the requester explicitly overrides that rule.

A mention inside a Mattermost thread reaches the session together with the thread
it was made in: the plugin's `pre_gateway_dispatch` hook reads the thread with the
default profile's Mattermost bot, and attaches the root post plus the newest earlier
replies (oldest first, the bot's own posts marked, system posts and the mentioning
post excluded, bounded to 60 replies / 30000 characters with older replies counted)
as channel context ahead of the mention. Usernames come from the Mattermost API and
are cached. Top-level posts, DMs without a thread, other platforms and internal events
are untouched. When Mattermost is unconfigured or the request fails or times out, the
mention is still dispatched without the block and a warning is logged.

`mattermost-access` reads threads, follows forwarded post links, searches within a
channel using Mattermost filters, and posts authorized replies, cross-thread notices,
new channel threads or DMs using the bot on the default messaging profile. PIC DMs
use verified responsibility from the project team map; unknown ownership is asked
in the originating discussion. Confidential requests still open a separate DM
session: it asks for the material, names the dest file (for example
`$HERMES_HOME/memories/env.md`), and writes the reply there. The original
thread reads that file on a later turn. It reads the default profile's
Mattermost messaging settings: `MATTERMOST_URL` and `MATTERMOST_TOKEN` from
`.env`, or `platforms.mattermost` `url`/`token` in `config.yaml`. Installing
or syncing the skill does not send messages. Existing DM handoff records remain valid.

The profile's `memories/semantic/team.md` holds verified team identities and
responsibilities for blocker, decision, review and testing mentions. Connecting
or syncing does not launch onboarding or send messages.

`TAXONOMY.md` defines durable project knowledge: small startup summaries, an index,
topic pages for architecture/repositories/decisions/workflows, and dated observations.
`SOUL.md` points architecture tasks to `prompts/architecture.md`, which uses that
taxonomy. Only the index and a small memory pointer are seeded; topic pages are
created when there is real knowledge to record. Repository documentation and GitLab
remain authoritative, with profile memory holding concise evidence and links.

Each registered project also gets a generated profile-root `PROJECT.yaml` with its
active mapped repository IDs, known names/URLs, configured GitLab server and expected
`workspace/<id>` clone paths. Registration does not clone code. CLI registrations
may have unknown names/URLs until saved with repository metadata; the numeric ID
and configured server let the agent discover them with available authenticated tools.
Credentials are never included in this inventory.

The bundled `SOUL.md` defines the task lifecycle through one Mermaid state diagram.
Prompts and shared skills provide instructions for their specific tasks.
The SOUL tells the agent to read that inventory, consult saved knowledge, then
inspect the README and code
before asking the user for project context. It applies to Mattermost, GitLab and
Desktop conversations routed to the profile, and distinguishes supported tasks from
the tools, credentials and permissions actually available. Mattermost still needs
to reach the correct profile; a GitLab repository mapping does not route a chat channel.
A Mattermost-triggered session answers questions and inspects code there. Implementation,
code generation and task-doer work require a confirmed GitLab issue:
create or reuse it in a mapped repository, and assign this profile's Codev bot so the
GitLab assignment session implements.

The managed SOUL accepts confidential material — `.env` files, secret variables,
tokens, keys, credentials, and other private values — for authorized tasks in
verified private DMs on Mattermost or other messaging platforms, without treating
private delivery alone as a leak. Shared/public or unverified conversations use
a verified DM or local `.env` instead. Secret values stay out of replies, logs,
Git and memories. This is agent guidance, not a transport filter; it updates
when the bundled SOUL is synced explicitly.

Mapping saves and removals refresh the affected inventory. Default-backend plugin
startup backfills existing registered profiles and clears disabled mappings from their
inventories while preserving custom SOUL text and memories. Legacy bundled skill
references are migrated to lookup by name.
For a manual refresh after editing routes or updating the plugin, run
`hermes -p default gitlab sync-knowledge`. This replaces `project-egg/SOUL.md`
and every managed project SOUL with the bundled version, saving changed originals
under each profile's `backups/gitlab-soul/sync-*/SOUL.md`. Identical SOULs are left
alone. The command also updates bundled skills once in
`global-project`, backing up changed files under its `backups/gitlab-skills/sync-*/`.
It links the installed `project-egg` starter and registered or retained GitLab
profiles to the shared skills. Retired `codev-gitlab`, `codev-handoff`, `gitlab-cli`,
`gitlab-workflow` and `mattermost-onboarding` folders in shared/project profiles
and local copies of bundled skills are moved intact to each profile's
`backups/gitlab-skills/sync-*/`, so they no longer shadow the shared versions.
Printed backup paths retain customizations and supporting
files for recovery. Other skills and learned knowledge stay in their profiles.
Identical shared files are left alone; failed backups stop replacements. Automatic
startup seeds missing shared files but preserves existing shared and local skills.
New project creation also archives any bundled local skills inherited from an
older starter, so the new project immediately uses the shared versions.
For local terminals, setup and sync set an unset/default working directory to the
profile's absolute root, beside `SOUL.md`, `PROJECT.yaml` and `memories/`. New profiles
rebase the starter's directory to their own root. Old `workspace/` defaults are
migrated; other explicit directories and non-local terminal backends are preserved.
Use a new conversation to ensure the updated startup instructions are loaded.
The block and `PROJECT.yaml` are plugin-managed; keep custom instructions outside
the `hermes-gitlab:orientation` markers and learned facts in `memories/`.

The bundled SOUL identifies the agent as **Codev**. On every surface (including
Desktop, TUI, CLI, Mattermost and GitLab), visible replies are one instant preamble
when work needs thinking, then a concise final result or an actionable blocker.
Working notes stay internal; retries, compaction, reviews and resumed work do not
trigger another preamble. Immediately answerable questions receive the answer
directly. Blockers name the missing input and where to provide it; recoverable
failures are handled silently. Required approvals remain visible.

Project setup and `gitlab sync-knowledge` apply the bundled quiet display settings
and mark the busy-input tip as seen in new and existing project profiles, with config
backups. They preserve unrelated display and onboarding preferences. Mattermost and
GitLab disable response streaming so partial narration is not streamed to chat;
interim replies stay enabled for the preamble.
Use a new conversation after syncing to load the updated SOUL instructions.

Project implementation on every surface requires a verified GitLab issue currently
assigned to this profile's Codev bot; an MR must resolve to that issue. Questions,
investigation and read-only reviews need no assignment. Issue-only requests do not
assign the bot; after creating a card the Mattermost session asks once whether to
start, and a yes from an authorized user self-assigns the bot, which dispatches the
issue session. When the card records the Mattermost thread permalink (Planning writes
it), the assignment dispatch verifies that permalink on the configured Mattermost
server, hands the issue session a `Mattermost origin` link, posts the origin note in
the issue, and relays the session's final reply (question, blocker or result) to that
thread as a turn of the thread's own session. An authorized assignment returns the issue link and leaves
implementation with the GitLab worker, avoiding
duplicate work from Desktop/TUI/CLI.

A Mattermost mention about previous work can continue the owning GitLab issue session.
Resolve the issue from an explicit link or verified MR relation; for older unlinked
threads, search the mapped project and confirm uncertain matches. After reading the
relevant planning, refinement and follow-up context, the Mattermost session runs
`hermes -p default gitlab continue --issue '<project-id>:issues:<iid>'`. The command
verifies the live mention, route and bot assignment, then records a restart-safe
request in the existing GitLab queue. The issue session handles the next turn under
the existing worker limit, refreshes issue/MR/commit/CI/review state, and reports its
result or blocker in GitLab and the original Mattermost thread. Repeated calls for
the same mention queue one request. Mattermost activity without a mention does not
wake GitLab work; failed Mattermost report delivery retries without rerunning work.
An optional `--request '<text>'` adds an instruction to the forwarded mention.

### Reports continue the origin thread session

With `plugins.entries.hermes-gitlab.allow_gateway_injection: true` on the default
profile, the issue session's final reply is not posted to the origin thread by the
plugin. It is delivered as a turn of the Mattermost thread session that requested the
work, through Hermes's plugin message injection. That session sees the result, question
or blocker inside its own context, relays the substance in its own final reply to the
thread, and continues work that was waiting for it: for example a second card that was
blocked on the first one. The relay text tells it to self-assign a waiting card, or to run
`hermes -p default gitlab continue --issue '<project-id>:issues:<iid>' --request '<text>'`
for an issue session that is already assigned. A relayed turn has no mentioning post, so
`continue` verifies it against the recorded relay instead, requires `--request`, and
queues one continuation per relayed report and issue. Answers to a relayed question or
blocker go through the same command.

The session key comes from `HERMES_SESSION_KEY` when `continue` queued the handoff, and is
derived from the verified origin thread (channel type, channel, root post, profile) for
card assignments. The plugin falls back to a plain post when injection is not allowed,
the gateway runner is unavailable, the thread session no longer exists, or the relay is
guarded: the same report text for the same issue and thread twice in a row, or a chain
of three bot-to-bot relays (report → relayed continue → report …) without a human
mention. Guarded reports still reach the thread and GitLab; they just do not wake the
thread session. Injected turns skip the thread-context hook, so the relay text points a
reset session at `mattermost-access thread` for the earlier discussion. The report also
still lands in the GitLab card.

Codev owns assigned work through implementation, review feedback and QA verification.
It traces relevant UI/API/business-rule/authorization/data effects, makes routine
technical choices and asks the responsible team member for business scope or major
architecture decisions with findings and a recommendation. It validates, reviews,
pushes and reuses the issue/MR; opening an MR is not task completion. Done follows
team acceptance criteria; merge and deployment still require authorization.

UI changes require passing, rerunnable automated E2E tests and screenshots from the
running app at the tested revision. Reuse existing scenarios when coverage is
adequate; add or update tests only for gaps, and run them in either case.
The MR records scenarios, commands/results,
revision and relevant states/viewports, with screenshots uploaded to GitLab or
linked through reviewer-accessible artifacts. Build/unit tests and local screenshot
paths alone are insufficient. Failed checks or missing/stale/inaccessible evidence
mean incomplete verification: keep new MRs draft and do not advance to review.
Backend-only work uses relevant API/data/security checks without a screenshot gate.

On a fresh supported mention/assignment, Codev handles reviewer/QA findings on the
same MR, checks current CI and refreshes affected evidence. This guidance adds no
automatic wake-up for CI/review changes. Sync with `gitlab sync-knowledge` and use
a new conversation to load the updated persona; existing profile customizations
outside the managed block remain intact. GitLab replies and MR descriptions use
Bahasa Indonesia and preserve repository template headings. Secrets stay out of
replies and evidence.

### Codev worktrees and setup knowledge

The plugin supplies `card`, `conversation`, `clone`, `project`, `worktree`,
`owned_repository_ids` and `gitlab_url` in each event. Clone paths are profile-relative
`workspace/<numeric-repository-id>` locations; they do not imply a clone exists.
The GitLab event supplies the current card context; the profile's `SOUL.md` defines
assignment and worktree rules. This is written for the gateway's automatic
discussion replies and does not depend on the older `gitlab-card` poller skill.
The Mattermost path ends with the verified issue link while the GitLab session implements.

The agent verifies or clones the repository with native Git over SSH, then uses
`git worktree add` with a verified base commit. New issue worktrees live under
`workspace/<repository-id>/.worktrees/<conversation-key>` with a local `feature/`, `fix/`
or `chore/` branch. The agent checks `git worktree list --porcelain` before creating
or reusing one, keeps `/.worktrees/` in the clone's local Git exclude, preserves existing work and uses the verified worktree path for all
subsequent edits and checks. Worktree preparation runs through the agent's terminal
tool, not inside the poller.

The key comes from the conversation, so a linked MR shares its issue's key. For a
task spanning repositories, each owned clone gets a worktree with that same key.
Standalone cards stay isolated. If an issue/MR link is added after work started,
the agent preserves the older checkout and deliberately reconciles
existing work; it never resets or deletes a branch to join the histories.

Recurring setup procedures live in the profile's
`memories/semantic/workflows/`, linked through the index and repository notes. Record
verified steps from clone and dependencies through environment files, migrations,
tests, start/stop commands, isolated ports/data, and how the user accesses the app.
This knowledge is available across worktrees; credentials are excluded.

Customize the bundled folder before installing, or select **project-egg** in Hermes's
normal profile selector and edit the installed starter. New projects clone the installed
profile's current contents using Hermes's native full-clone operation. Additional prompt
files, skill assets, configuration files, and starter memory are included. Later changes
to the starter apply to future projects; existing projects keep their independent copies,
except for the managed orientation/inventory refresh and explicit bundled-skill sync
described above.

To apply the latest bundled skills, including SSH clone and Codex review
guidance, run on the Hermes backend:

```sh
hermes -p default plugins update hermes-gitlab
hermes -p default gitlab sync-knowledge
hermes -p default gateway restart
```

Sync updates shared skills and archives legacy local copies, as described above.
Merge reusable customizations into `global-project/skills/`; keep project-specific
instructions in that project's SOUL or knowledge. `HERMES_HOME` remains the active
project profile when executing shared skills. Sync does not provision SSH
credentials. Verify repository access as the Hermes runtime user before retrying; a fresh bot mention can resume the
blocked GitLab conversation.

Hermes's native clone excludes prior conversations, scheduled jobs, and runtime state.
Messaging connections and multiplexer routes belong to the default backend and are
not duplicated. Template model/tool credentials follow native cloning rules, including
shared fallback for rotating OAuth logins. Keep personal secrets out of the distributed
plugin folder. `project-egg` is reserved for the starter and does not appear as a GitLab
project registration or deletion target.

The native restart cooldown is respected before requesting a fresh restart, so a
quick second save does not silently reuse a restart that loaded the old mapping.
A completed restart command can precede gateway connections becoming ready. If its
outcome cannot be confirmed within 30 seconds, check **Messaging** on that backend.

New profiles have independent knowledge and sessions. Description applies only when
creating a profile. Removing a registration preserves the profile and its knowledge.
To move a repository, remove it from the old profile and save, then register it under
the new profile. Each save restarts the shared gateway.

To remove the entire project, select it, choose **Delete project**, and type its
exact profile name. This permanently deletes its Hermes profile, including
memories, sessions, credentials, skills and scheduled jobs, and removes its managed
repository registrations. It keeps the GitLab repositories themselves. The default
connection profile cannot be deleted. Other profile routes using the same profile
must be removed first.

Desktop removes the registration, then uses Hermes's native profile-deletion flow
to stop that profile's processes and clean up its tabs and data. If the second step
fails, the page reports the partial result and supports retrying with fresh
configuration. Restart the default messaging gateway afterward to apply the saved
repository list. Project deletion still uses this manual restart step.

Saving automatically requests a gateway restart. Stale concurrent edits are rejected; refresh
before retrying. Saving re-enables selected registrations marked as disabled.
Configuration is backed up and written atomically, although YAML
formatting/comments may change.

Registration does not clone or index code. The Codev workflow clones with
native Git over SSH when needed, or asks on GitLab when setup is blocked.
GitLab sessions use the selected project profile's **Capabilities → Tools**
settings, the same toolsets its CLI sessions use. The old
`platforms.gitlab.extra.toolsets` setting no longer controls them. Enable Browser
Automation there to expose `browser_exec` and `browser_vault_fill` when the backend
is available. Menu changes apply on the next GitLab turn; restart the gateway
after updating the plugin. No live
credentials or permissions are changed by extracting the plugin package.

### Menu opens the chat instead of the page

Hermes Desktop builds from revision `a55c972e09` can cache the route list before
runtime plugins load. The menu then highlights GitLab Projects while the workspace
still shows a chat. This is a Desktop rendering bug; changing the PAT or reinstalling
the GitLab plugin does not fix it.

Update to a Desktop build containing upstream commit `6fc7032aac` (#109063),
which fixes both the main workspace and split-pane routes. No local Hermes patch
is needed on that build. `hermes-desktop-runtime-routes.patch` is an obsolete
historical workaround; do not apply it to current Hermes.

The plugin API uses Hermes's existing profile secret scope. Missing default-profile
GitLab URL/token values are explicitly empty, so they cannot fall back to another
profile's process environment. It does not require `set_multiplex_context` or change
Hermes's global multiplexing state.

### CLI alternative

```sh
hermes -p default gitlab add-project commerce --repos 101,102 --description "Commerce services"
hermes -p default gitlab add-project finance --repos 201,202
hermes -p default gitlab projects
```

Names and IDs are examples. CLI additions are additive. Generated native routes
use `chat_id: repo:<ID>` and a named profile. Missing or conflicting routes are
held for retry before card context is fetched or an agent runs.

## Hermes commands in GitLab

Post a standalone comment starting with the bot mention, for example
`@codev-bot /help` or `@codev-bot /status`. Use the username of your bot account.
Commands bypass the card's busy queue and reply in the triggering discussion.
Ordinary mentions on a busy card are steered into its running turn instead (see
[Polling and reliability](#polling-and-reliability)).
Issue descriptions, assignments, quotes, and ordinary prose remain agent context.

Supported commands: `/help`, `/commands`, `/status`, `/context`, `/stop`, `/new`
(`/reset`), `/model`, `/reasoning`, `/version`, `/usage`, `/skills`, `/reload-skills`,
`/compress`, and `/title`. These use native Hermes session behavior; commands that
require an idle agent return its busy response. `/stop` and `/new` do not automatically
retry the work they cancel. Host-wide administration and custom skill commands are
not exposed through this GitLab transport; unsupported commands return guidance.

For a pending operation, reply **in the approval prompt's discussion** with
`@codev-bot /approve`, `@codev-bot /approve session` when offered, or
`@codev-bot /deny [reason]`. Session approval applies to the native pattern for that
card's conversation. It does not disable security scanning. Permanent and bulk
approvals are not exposed here. The bot validates the actual comment's author/body,
its position after the prompt, the project/profile, and the native approval request ID.
Unrelated, expired, replayed, or pre-restart prompts cannot approve a newer operation.
After a timeout, the old reply cannot revive the blocked operation; a human must
provide a fresh instruction and respond to any new approval prompt.

Commands are claimed once before dispatch, including across restarts and duplicate
to-dos for one comment. If delivery fails or the process exits during dispatch, the
command is **not** automatically executed again. Check `/status` before resending
a session command; answer the current prompt when resending an approval.

## Polling and reliability

The default gateway reads the bot's global pending **and done** GitLab to-dos,
without a `project_id` filter, and maps each response's `project.id` to a registered
Hermes profile locally. Each cycle starts with two listing requests, plus pagination,
regardless of repository count. No listing requests are made when no repositories
are registered. Reading done items matters because posting a reply can automatically
complete other to-dos on the same card.

Pending items are scanned in full. Completed items use descending to-do IDs and a
SQLite checkpoint, retaining the previous high-water ID and processing the entire
page that reaches it. Checkpoints advance only after successful collection; failed
pages are retried, and saved inbox work continues independently. Unexpected ordering
or malformed rows disable early stopping for that scan. On 2026-09-16,
`gitlab.dot.co.id` was checked read-only: 177 completed items across two pages were
strictly descending; the pending list was empty. The [REST endpoint](https://docs.gitlab.com/api/todos/)
has no documented date or sort parameters. Requests use its returned order rather
than sending `order_by=id` or `sort=desc`. The inbox dispatches only incomplete
items, oldest ID first, and keeps completed IDs across restarts to prevent replay.

An initial full scan, an hourly full recheck, and a full recheck after repository or
allowed-user changes catch older items behind the checkpoint. Such late completed
items can wait until the next hourly recheck. Per-repository creation-date cutoffs
still exclude completed history from before registration; old pending items remain
eligible. This is a creation-ID checkpoint, not a GitLab event cursor.
Allowed issue/MR mentions and issue assignments enter a local SQLite inbox before
processing. Hermes fetches the card and latest 20 comments, chooses the registered
profile, and posts its response through the bot PAT.

Requests on one card run sequentially. A successfully delivered native response
completes the inbox item only after agent execution started. Busy/startup deferrals,
context failures, and delivery failures are retried.

A mention that arrives while the card's turn is still running is **steered** into
that turn through the gateway's steer path, regardless of the profile's
`display.busy_input_mode`: the running agent receives the comment as its next user
message after the current tool batch, the inbox item completes, the bot acknowledges
in the mention's discussion, and the turn's final reply covers both requests. If no
agent is live yet (turn pending, startup restore) the item stays queued and the next
poll retries. Issue assignments and Mattermost `gitlab continue` handoffs always wait
for their own turn because they attach an origin note and relay a report. If the agent runs and returns
a provider-error notice that is successfully posted, that request is handled;
mention the bot again after fixing the provider problem. State lives at
`<default Hermes home>/gitlab/<account-hash>.sqlite3`; the hash includes GitLab URL
and bot ID. A file lock prevents two gateways in the same Hermes root from polling
that account concurrently. Preserve this state during updates and migration.

## Verification and limits

- After setup, mention the bot on an issue/MR or assign it a fresh issue from an
  allowed user. Expect a comment after the polling interval plus model time.
  Inspect gateway logs for fetch, routing, processing, or delivery failures.
  A Mattermost implementation request should confirm an issue, assign the bot, and
  start that GitLab assignment session; the bot's own mention comments stay ignored.
- This follows GitLab **to-do creation**, not a complete event log. GitLab 17.8+
  with multiple to-dos enabled creates a new to-do per mention. Repeated issue
  assignment may not create another to-do; use a fresh mention for another response.
  MR assignments and reviewer requests are outside this release.
- Each repository's first configured connection imports pending requests, including
  old ones, and skips completed requests created before that connection. Its cutoff
  survives restarts. Review the bot's pending list before first launch if needed.
- Delivery is at least once: a crash after GitLab accepts a reply but before the
  local completion commit can cause a repeated comment. Completed inbox items
  survive restarts. There is no exactly-once delivery guarantee.
- Polling lists the bot's to-dos globally, regardless of repository count. Pending
  pages are scanned each cycle; done history is scanned in full initially, hourly,
  and after scope changes. Large histories still increase full-scan traffic and latency.
- Context caps: 20 notes, 4,000 characters per note, 40,000 total comment characters,
  20,000 description characters, and 20,000 trigger characters. Attachments, inline
  diff reviews, cloning, and moving/closing cards are not included.

## Local checks

```sh
PYTHONPATH="$HOME/.hermes/hermes-agent" \
  "$HOME/.hermes/hermes-agent/venv/bin/python" -m unittest discover -s tests -v
node tests/check_desktop.mjs
node tests/check_desktop_routes.mjs
```

Tests use loopback fake GitLab servers, temporary Hermes homes, and local response
handlers. They exercise native auth/plugin loading, profile creation and routing,
repository edits, typed deletion and native teardown of temporary profiles, polling,
durable retries, pagination, and comment delivery.
They do not call a real GitLab instance or model. Live deployment has not
been verified with your GitLab URL/PAT.

The Desktop check uses the installed Hermes checkout's React controls and SDK.
Set `HERMES_AGENT_ROOT` if that checkout is elsewhere. For a browser preview with
sample data, run `node tests/check_desktop.mjs --preview` and open the printed URL.
Append `?long` for a long repository editor. Its footer should end just above the
pane edge, with no outer-pane scrollbar or blank tail; check wide and narrow panes.
The route regression check compiles the native Desktop route components with the
production React compiler, then registers a page after mounting the shell. It
checks late registration and removal in both the workspace and split panes.

References: [Hermes Desktop SDK](https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk),
[GitLab To-dos API](https://docs.gitlab.com/api/todos/),
[GitLab to-do behavior](https://docs.gitlab.com/user/todos/),
[GitLab Notes API](https://docs.gitlab.com/api/notes/).
