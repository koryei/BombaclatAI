# BombaclatAI - Autonomous Discord Companion

A self-bot (via `dolfies/discord.py-self`) that acts as a real, persistent
member of a friend group's Discord: it remembers people and conversations
across every server/GC/DM it's in, decides on its own when to jump into a
conversation, controls its own status/activity/bio, and learns from
feedback over time.

> Automating a user account is against Discord's published Terms of Service.
> Use this setup only if you accept the account risk.

## Architecture

```
main.py                    entry point
config.py                  static config + persona system prompt

db/
  database.py               SQLite connection + schema (WAL mode, async)
  repository.py              all persistence queries (messages, users,
                              memories, decisions, reviews, trigger weights, config)

core/
  models.py                  shared dataclasses
  triggers.py                 pattern detectors (sadness, celebration,
                              help requests, escalation, boredom, banter)
  learning.py                 self-evolving trigger weights + user vibe EMA
  personality.py              situational tone selection (supportive, hyper,
                              help, chill, dismissive, curious)
  memory.py                   passive fact extraction + safe recall
  reasoner.py                  LLM-backed judgment call for borderline
                              autonomous decisions
  decision_engine.py           combines safety gates, planner decisions,
                              trigger hints, learned weights, and fallback reasoning
  autonomous_planner.py        native model action planner for ignore/reply/
                              get-to-know/reaction choices
  brain.py                     dynamic multimodal orchestration boundary; the
                              only class that touches both DB and Discord
  agent_tools.py             allowlisted native function schemas for memory,
                              profile/context lookup, search, page reading,
                              reminders, reactions, and calculations
  serper_client.py           bounded Serper Web Search API client with
                              normalized results, caching, and safe failures
  web_freshness.py           current-information classification and confirmation
                              policy for direct requests

bot/
  client.py                   discord.Client subclass, thin adapter to Brain
                              (system filtering + command-aware ingestion)
  presence.py                  status / activity / bio control
  autonomous_loop.py            background tasks (autonomous posting,
                              presence evolution)
  commands.py                  owner-only text commands

llm/
  gemini_client.py             Gemini API wrapper, shared rate limiter,
                              native multimodal input, and tool-call parsing
  openrouter_text_client.py    text and multimodal OpenRouter fallback with
                              native tool-call parsing
  openrouter_vision_client.py  bounded compatibility vision transport with
                              retries and in-memory image input

  prompt_builder.py             builds the final prompt (persona + tone +
                              memories + history)
```

## How it thinks

1. **Every message**, in every server/GC/DM the account is in, is stored in
   SQLite (`data/bombaclat.db`) with author, channel, and timestamp. The native
   agent semantically extracts stable facts ("i love minecraft", "my favorite
   game is...") and saves them per-user; a legacy pattern extractor is kept only
   when agent tooling is disabled.
2. Incoming mentions and DMs are grouped into a short **conversation batch**,
   so several messages arriving close together are answered as one exchange
   instead of one API request per ping. The autonomous loop waits for a quiet
   moment, evaluates only new context, and asks the native **autonomous planner**
   whether to ignore, reply, ask a get-to-know question, or react. Cheap trigger
   detectors provide context hints and remain the fallback when providers fail.
3. Escalation detection is a hard safety rule, checked first, and is never
   overridden by learning - if a real argument looks like it's happening,
   the bot always stays quiet.
4. The planner can act even when no regex trigger matches, but it must clear
   hard-coded safety and confidence gates. `AUTONOMY_MODE=autonomous` enables
   that model-first behavior by default. Setting it to `conservative` restores
   trigger-first decisions while keeping native tools available for replies.
   If native planning is unavailable, the older learned-trigger/reasoner path
   still makes the decision.
5. Every decision (post or decline) is logged with its reasoning and context
   metadata. Routine decline DMs are disabled by default to avoid noisy owner
   notifications; use `!think`, `!recent`, or explicit feedback to review them.
6. Feedback (explicit via `!feedback`, humor labels via `!humor`, or organic via replies/reactions
   after a post) nudges that trigger's learned weight up or down, so the
   bot's instincts shift over time based on what's actually welcomed. Humor
   labels retain short owner-approved examples and corrections, so the voice
   learns the group's timing instead of collecting generic slang.
7. The bot keeps lightweight user profiles: stable facts from natural messages,
   message/question/emoji patterns, rolling vibe, and context-safe memories.
   It can use those profiles to ask an occasional get-to-know-you question
   instead of treating every person as a stranger.
8. Low-stakes celebration, banter, and boredom moments may get one emoji
   reaction instead of another generated message. Reactions use the existing
   autonomous cooldowns plus per-user and hourly caps, and never replace help
   or emotional-support replies.

Normal text replies use a bounded agent turn first. Gemini can call safe
native tools such as `remember_fact`, `get_user_profile`,
`search_recent_context`, and `react_to_message`; Bombaclat validates every
call before executing it. Quiet autonomous observation can also remember a
fact without posting, but only when the model supplies a verified participant
and source message. With agent tooling enabled, semantic memory is primary and
legacy regex extraction is only the explicit disabled-agent fallback. If the
agent turn fails, normal text generation uses Gemini first. If Gemini fails, times out, or hits the local rate limiter, Bombaclat makes a short bounded OpenRouter request using
`OPENROUTER_TEXT_MODEL` (default:
`thinkingmachines/inkling-small:free`). If both providers fail, it sends a
short local fallback instead of crashing or claiming the request succeeded.

## Owner commands

Only usable by `OWNER_ID` (defaults to Koryei's user ID, override via `.env`):

```
!config [key] [value]           view or set a config override
!vision on|off|status            control image vision requests
!gif learn [limit] [force]       classify GIFs from the current channel once
!gif list [n]                    show the learned GIF library
!gif gallery [n]                 show learned GIFs with previewable URLs
!server list                     list joined servers and IDs
!server join <invite>            join a server through an invite
!server leave [guild_id]         leave a server, or the current one
!friend status                   show friends, requests, blocks, and auto-accept
!friend list [kind]              list friends, incoming, outgoing, or blocked users
!friend accept [all|user_id]     accept pending friend requests
!friend block <user_id>          block a user
!friend unblock <user_id>        unblock a user
!friend remove <user_id>         remove a friend
!friend auto on|off              toggle automatic incoming-request acceptance
!captcha status                  show whether the CAPTCHA safety guard is active
!captcha acknowledge             clear it after you manually verify in Discord
!autonomous on|off               toggle autonomous posting per channel
!reviews on|off|full|digest|status owner review delivery and audit mode
!review <id>|digest|preview ...   inspect a decision or gate a channel
!status <online|idle|dnd|invisible>
!activity <type> <text>
!bio <text>
!mood                             current tone/energy snapshot
!recent [n]                       markdown report: recent memories, autonomous
                                  activity, live stats, and changelog updates
!changelog [n]                    recent code and behavior changes
!think [n]                        last n autonomous decisions + reasoning
!weights                          learned trigger weights
!feedback <approve|reject|adjust> <id> [correction]   train/correct the loop
!humor good|bad [note]             rate a reply (reply to it first)
!humor status                      show humor calibration feedback
!memory list|add|forget           inspect/edit what the bot remembers
!dm <user_id> <text>              send a DM as the bot
!tell <user_id|name> <text>       send exact text in a recent shared server/GC
!restart                          restart and announce changelog updates
!stop                             shut down the process without restarting
!help
```

`!restart` sends a short pre-restart message in the command channel, replaces
this process, and posts one varied, human-like wake-up message there after
Discord reconnects. The bot then resumes its normal presence, memory, direct
reply, autonomous, and reaction loops.
`!stop` sends a shutdown message and closes the process without replacing it.
When `!restart` has new or edited entries in the latest update feed, the
wake-up includes a short update list; otherwise it uses one of the natural
wake-up lines.

If Discord reports a CAPTCHA, Bombaclat latches a persistent session-wide safety guard:
outbound messages, reactions, GIFs, reminders, relationship changes, and
server membership changes stop retrying. Use `!captcha status`, complete any
verification manually in Discord, then use `!captcha acknowledge` or restart
the service. The guard is deliberately not a CAPTCHA solver or bypass; the
supported long-term setup is a dedicated Discord bot account installed through
OAuth2 rather than a user-account self-bot.

In a true 1-on-1 DM, the owner can also use a narrow natural order such as
`you just tell Vetian that its Gemini`. Bombaclat only confirms after it has
resolved Vetian, found a recent shared server/GC, and successfully sent the
message; it will say it could not act instead of pretending.

## Setup

1. Python 3.10+, virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Remove the conflicting official Discord package, install dependencies:
   ```bash
   pip uninstall -y discord.py google-generativeai
   pip install -r requirements.txt
   ```
3. Configure `.env`:
   ```env
   DISCORD_TOKEN=your_discord_user_token
   GEMINI_API_KEY=your_google_ai_studio_key
   OPENROUTER_API_KEY=your_openrouter_key
   OPENROUTER_TEXT_MODEL=thinkingmachines/inkling-small:free
   OPENROUTER_VISION_MODEL=inclusionai/ling-3.0-flash-vl:free
   VISION_ENABLED=true
   GIFS_ENABLED=true
   GIF_LEARN_MAX_IMAGE_MB=8
   REACTIONS_ENABLED=true
   AGENT_ENABLED=true
   AGENT_MAX_TOOL_CALLS=4
   AGENT_MAX_ORCHESTRATION_STEPS=3
   AGENT_OBSERVATION_ENABLED=true
   AUTONOMOUS_PLANNER_ENABLED=true
   AUTONOMY_MODE=autonomous
   OWNER_REVIEW_MODE=off
   SERPER_API_KEY=your_serper_api_key
   SERPER_ENABLED=true
   SERPER_MAX_RESULTS=5
   SERPER_TIMEOUT_SECONDS=10
   SERPER_CACHE_SECONDS=600
   WEB_SEARCH_MODE=smart
   OWNER_ID=1283126476463542375
   ```
4. Run:
   ```bash
   python3 main.py
   ```

For a Linux VM deployment with systemd, rotating logs, graceful shutdown, and
nightly SQLite backups, follow [`deploy/README.md`](deploy/README.md).

The SQLite database is created automatically at `data/bombaclat.db` on first
run and persists across restarts. Message IDs, conversation batches, curiosity
cooldowns, and interaction events are stored so restarts do not reset context
or cause the same exchange to be evaluated repeatedly. Configured old message
and memory records are pruned safely at startup.

## Social behavior

Learning here means persistent, explainable memory and user-profile signals,
not retraining Gemini's model weights. The native agent is the primary semantic
learner when enabled: clear statements such as `i play valorant`, `i listen to
deftones`, or `call me jay` can become safe memories. The old regex extractor
is retained only as a fallback when agent tooling is disabled. Commands, bot
messages, and attachment-only posts are not learned as personal facts.
Corrections are still conservative, so use `!memory forget` if a stored fact
needs to be removed manually.

The bot occasionally asks a light get-to-know-you question after someone has
sent multiple messages and the bot has no safe context about them. It uses a
long per-user/channel cooldown so this does not become an interview.

For casual autonomous moments, it may react with one of a small set of emojis
instead of generating text. Reaction-only actions do not create fake bot
messages in history, have per-user/hourly limits, and never downgrade help,
sadness, escalation, or direct-mention replies.

## Dynamic multimodal agent behavior

A directly addressed image in a DM or mention is passed as native image input to
the same agent turn that handles ordinary conversation. The model can answer
from the image, stay conversational without using it, or request an allowlisted
tool when the user's intent requires external data. Validated tool results are
fed back into bounded follow-up turns, so sequences such as web search followed
by public-page reading can be selected at runtime instead of being hard-coded as
separate pipelines. If no tool is needed, the agent falls back to a normal text
reply; if a provider fails, the other configured model or local fallback is used.

Public image posts without direct context remain quiet unless
`VISION_PUBLIC_SOCIAL_ENABLED=true`. Image bytes are validated, bounded, held in
memory only for the request, never written to SQLite, and never included in
logs. Unsupported, too-large, unreadable, timed-out, or failed images receive
an honest fallback instead of an invented description. The owner can use
`!vision on|off|status` to control normal vision availability at runtime.

To teach Bombaclat a private GIF library, put the GIFs in a channel it can
read and run `!gif learn`. Each new GIF is sent to the configured free vision
model once, then its reaction labels and URL are stored in SQLite. Later
conversation does not re-analyze the GIF, even when Discord rotates a signed
CDN query string. Use `!gif learn 100 force` only when you intentionally want
to reclassify already learned GIFs, and `!gif list` to inspect the learned labels. GIF
reactions remain optional and cooldown-limited, and are blocked for help,
sadness, or escalating conversations.

The orchestration budget is controlled by `AGENT_MAX_TOOL_CALLS` and
`AGENT_MAX_ORCHESTRATION_STEPS`; these limits prevent tool loops while still
allowing the model to choose the correct sequence. Current-information search
remains intent-gated so casual questions cannot accidentally trigger public web
requests.

## Smart current-information search

Bombaclat uses the optional Serper Web Search API for bounded current-information
lookups. This does not add a Python dependency or make the key mandatory for
startup; add your own key locally to `.env` when you want live search:

```env
SERPER_API_KEY=your_serper_api_key
SERPER_ENABLED=true
SERPER_MAX_RESULTS=5
SERPER_TIMEOUT_SECONDS=10
SERPER_CACHE_SECONDS=600
WEB_SEARCH_MODE=smart
```

The smart route is deliberately small and model-friendly:

- `what are the recent GTA 6 updates?` searches automatically
- `what's going on with GTA?` asks `u want me to look up the latest on that or were u asking generally`
- `what is GTA?` answers normally without spending a search request
- `WEB_SEARCH_MODE=ask` asks before every otherwise-clear lookup; `off` disables web search
- local Bombaclat changelog questions use the verified local changelog, not public search

The model still chooses normal tool use. The application only backstops an
unmistakably current request if the model forgets to call `search_public_web`.
The autonomous planner and quiet observation loop never initiate web searches.
Results are bounded, cached, HTTPS-filtered, and kept under a built-in one-request-per-second provider gate; they are treated as untrusted reference data. Missing keys, rate limits, malformed responses, or outages produce an
honest fallback instead of a provider/topic-blaming joke or fabricated answer. Check your Serper account for current pricing and usage limits; they are not duplicated here as fixed application guarantees.

Minecraft update and news lookups are stricter than ordinary searches: they
require the full topic, reject stale year claims even when Serper reports a
recent publication date, and discard unrelated guide/news hubs. The bot does not
invent a Minecraft answer or silently crawl arbitrary pages when the provider
cannot find trustworthy evidence; it says so plainly instead.

Serper usage, pricing, and availability are controlled by the provider and can
change. Never paste the API key into Discord, source code, screenshots, or chat.

## Changelog

Code changes are tracked in [CHANGELOG.md](CHANGELOG.md). The `!recent`
command reads directly from that file, so the bot's own self-report always
reflects the actual code - update `CHANGELOG.md` whenever you make a
meaningful change so `!recent` stays accurate.

The owner review loop is implemented and documented in
[IDEAS.md](IDEAS.md). It is opt-in, rate-limited, persistent across restarts,
and keeps review conversation separate from action authorization.

## Terminal UI

On startup you'll get a green, neofetch-style boot banner with account,
server, and config info, followed by a live-updating status dashboard
(uptime, messages seen, autonomous posts/declines, API usage, etc.) that
refreshes several times a second while normal logs scroll above it.

## Testing

See [TESTING.md](TESTING.md) for a full solo test checklist and instructions
for getting friends to try it out and report feedback.

---
## Security
- No hardcoded secrets in source (all API keys via `.env`, excluded by `.gitignore`).
- Secret scanning performed; `.env` replaces real tokens with `<PLACEHOLDER>` (rotate before production).
- Report security issues via repo issues (not in chat/logs).

## Status
Active development — changelog tracked in `CHANGELOG.md`. 18 micro-commits on main.
=== ARCHIVE NOTE ===

> Noted for archive: this repo is intended for public viewing / archival. Security practices applied (placeholders, .gitignore, SECURITY.md, scan complete). Real keys must be rotated before any production use.
