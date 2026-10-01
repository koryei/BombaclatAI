# Changelog

## 2026-09-15

- Added a session-wide CAPTCHA safety guard. When Discord reports a CAPTCHA,
  Bombaclat stops outbound/account-changing retries across DMs, replies,
  reactions, GIFs, reminders, friend actions, and server actions.
- Added owner command `!captcha status` so the stop state and manual recovery
  path are visible instead of hidden behind generic Discord errors.
- Persisted the safety stop across service restarts and added
  `!captcha acknowledge` for owner-confirmed manual recovery.
- Relaxed direct dependency pins into compatible ranges so ARM64 VM package
  indexes can resolve versions they actually publish, while keeping
  `discord.py-self` on the supported `2.0.x` API line.

This file tracks meaningful changes to Bombaclat's codebase and behavior.
The `!recent` command reads the top entries from this file directly, so the
The bot can always tell you what's changed about itself recently.

## 2026-09-15 - conversation-specific humor calibration
- Reworked the voice rules so humor is optional, short, specific, and deadpan instead of a constant performance
- Added a small one-month chat-derived calibration set and owner feedback storage for labeled good and bad replies
- Added owner-only `!humor good|bad` feedback; reply to a Bombaclat message first so future prompts learn the rhythm without copying lines

## 2026-09-15 - GIF gallery command
- Added `!gif gallery [n]` plus `!gif show` and `!gif all` aliases to display learned GIF categories, descriptions, and previewable URLs

## 2026-09-15 - clearer GIF learning counts
- GIF learning now labels repeated or already-classified media as `already known` instead of the ambiguous `skipped`

## 2026-09-15 - owner server and relationship controls
- Added owner-only `!server list|join|leave` commands for explicit server membership management
- Added owner-only `!friend status|list|accept|block|unblock|remove` controls
- Incoming friend requests are accepted automatically by default through relationship events and periodic reconciliation, with `!friend auto on|off` to control it

## 2026-09-15 - GIF learner respects CDN rotation and free limits
- Discord CDN query strings are no longer treated as a brand-new GIF every time history is fetched
- GIF learning pauses after the free vision provider rate-limits instead of hammering every remaining file
- GIF learning now allows up to 8 MB by default and reports deferred items separately

## 2026-09-15 - GIF learning download fallback
- GIF learning now retries a failed Discord attachment read through its signed CDN URL
- `!gif learn` reports coarse failure reasons such as oversized media, unsupported types, network failures, and vision classification failures

## 2026-09-15 - one-time vision-learned GIF reactions
- Added owner-only `!gif learn` to classify GIFs from a controlled channel with the configured free vision model
- Persisted GIF URLs, social reaction categories, descriptions, and confidence in SQLite so normal conversation reuses labels without repeated vision calls
- Added bounded direct and autonomous GIF actions with category matching, cooldowns, hourly caps, and safety blocks for help, sadness, and escalation

## 2026-09-15 - tighter anti-slop humor rules
- Reworked the persona guidance so jokes must use a concrete detail, opinion, callback, or specific exaggeration from the current conversation
- Added explicit rejection of generic reaction filler and a final prompt-level comedy filter for replies that could fit under any unrelated post
- Tuned situational tones and provider-outage fallbacks toward shorter, more specific, less canned responses

## 2026-09-14 - Serper conversational query fix
- Current searches now remove conversational lead-ins such as `oh wow thats nice can you search` before sending the actual topic to Serper
- Minecraft current searches use a `site:minecraft.net` query restriction so Serper returns official update evidence instead of unrelated pages
- Added routing coverage for conversational GTA follow-ups and confirmed the exact screenshot wording returns usable GTA 6 results

## 2026-09-14 - Serper current-information search
- Replaced the production LangSearch adapter with a bounded Serper Web Search API client while preserving the `search_public_web` tool contract and smart routing behavior
- Added Serper organic-result normalization, Google freshness parameters, relative-date parsing, safe failure states, caching, HTTPS filtering, and existing Minecraft official-source safeguards
- Updated configuration, tests, setup documentation, and provider-specific logs to use `SERPER_*` settings

## 2026-09-14 - current-search relevance is stricter
- Bounded searches now require every non-generic topic term, reject incidental .NET/macOS-style matches, and reject stale year claims hidden behind recent provider dates
- Minecraft update/news searches require official Minecraft-domain evidence instead of trusting generic guides or unrelated provider matches
- When the provider cannot supply trustworthy current evidence, the bot keeps the honest no-result response instead of inventing or silently crawling a special-case source
- Added regression coverage for official-domain filtering, stale titles, and low-quality no-result behavior

## 2026-09-14 - restart updates now detect edited entries
- Restart announcements now compare update titles and bullet content instead of only section titles
- Existing title-only tracking is migrated safely so a changed current entry is not silently skipped

## 2026-09-14 - LangSearch smart current-information search
- Replaced the old HTML search-provider path with a bounded LangSearch Web Search API client using the standard library only
- Added smart freshness routing: clear current requests search, ambiguous requests ask first, timeless questions answer normally, and local changelog questions stay local
- Added safe provider outcomes, HTTPS-only result filtering, normalized summaries, caching, a one-request-per-second free-tier gate, bounded timeouts, and no raw provider-error leakage
- Added `WEB_SEARCH_MODE=smart|ask|off`, pending confirmation isolation, and an application backstop when the model forgets to search
- Kept the autonomous planner and observation loop separate from unsolicited web search; current search does not crawl arbitrary provider result pages
- Added follow-up consistency guardrails so search answers preserve rumor/unconfirmed qualifiers, compare earlier Bombaclat claims, explicitly correct changed claims, and do not treat missing coverage as proof
- Preserved URL punctuation through the final response sanitizer so source links remain clickable instead of being flattened into domain text
- Added upcoming-month freshness routing and application-side date filtering so stale dated pages do not support current or upcoming claims
- Added authoritative local/UTC clock context and `as of` search anchors so relative dates are resolved from the configured timezone instead of model memory


## 2026-09-13 - deterministic current-info tool routing
- Clear questions about latest or recent news, game updates, and patch notes now invoke the bounded web-search tool before Bombaclat writes a reply
- Bombaclat changelog questions stay on the verified local changelog path instead of being sent to the public web

## 2026-09-13 - current questions beat repeat-ping jokes
- Natural questions without punctuation, including recent game updates, are now treated as real requests instead of empty spam
- Bombaclat can use the public web tools for current news, game updates, and patch notes before making a joke about the search

## 2026-09-13 - more human humor and context callbacks
- Tuned Bombaclat's voice to react to the exact conversation with dry observations, callbacks, and playful disbelief instead of generic assistant jokes
- Replaced bland restart wake-up lines with short context-friendly messages, while keeping help answers useful and preventing web-search fallbacks from inventing facts

## 2026-09-13 - image request routing fix
- Captions such as `look how much i spent` now route attached images to the vision model when the bot is directly addressed
- Added regression coverage for image questions about prices, spending, and screenshots while unrelated public attachments remain quiet

## 2026-09-13 - quieter context-aware vision replies
- Removed the interim `hold on im fetching the image` Discord message so explicit image questions produce one final response
- Vision prompts now prioritize the user's actual joke or question, prohibit attachment/process narration, and treat usage/token screenshots as context instead of automatically claiming they show a dollar cost

## 2026-09-13 - BETA utility agent tools
- Marked the new reminder, public web search, public page fetch, and safe calculator tools as BETA test features while they receive real-world testing
- Added persistent reminders with bounded 10-second-to-30-day delays, creator/owner cancellation checks, and background delivery in the originating channel
- Added read-only public web search and public HTTPS page summaries with SSRF, credential, size, content-type, and timeout guards
- Added a no-code-execution calculator for arithmetic, percentages, dates, token-cost math, and explicit unit conversions
- Added native tool schemas, execution tests, and safe failure responses without arbitrary shell, Python, private-network, or Discord-operation access

## 2026-09-13 - clock-aware presence and activities
- Added an EDT-aware school/life schedule: idle late night, getting-ready activity from 6:00-7:50, dnd for school and homework, social after school, and gaming at night
- Added rotating Minecraft, Fortnite, GTA V, Roblox, music, YouTube, and streaming activities with real Discord activity types and clean labels designed to pair with Rich Presence icons
- A real DM/mention response temporarily restores online status, then returns to the scheduled status after the conversation goes quiet; late-night replies use a sleepy mildly-confused tone
- Kept owner `!status` and `!activity` controls, including streaming with a configurable stream URL and optional Rich Presence application assets

## 2026-09-13 - persistent owner review loop
- Implemented opt-in `!reviews` modes plus `!review` inspection, digest, and per-channel preview controls
- Added persistent review sessions/messages with bounded context, private-context redaction, expiry, delivery cooldowns, and audit events
- Owner replies can approve, reject, adjust, ask why, continue a bounded follow-up, or explicitly confirm a safe memory; ambiguous messages never authorize actions
- Preview mode pauses autonomous posts/reactions until an exact owner approval, while normal autonomy remains independent when review mode is off
- Made review feedback idempotent and connected explicit action corrections to future planner preference hints
- Added persistence, redaction, reply-routing, and duplicate-feedback tests
- Review context now excludes Bombaclat's own command/restart output, so owner reports focus on the human conversation instead of leaking old `!memory` dumps or lifecycle messages
- Existing persisted review sessions are refreshed when inspected, so older reports can be repaired without losing their decision context; added regression coverage for this migration path

## 2026-09-13 - model-driven autonomous planning
- Made `AUTONOMY_MODE=autonomous` the explicit default; `conservative` remains available when trigger-first behavior is wanted
- Added a native planner that can choose ignore, reply, get-to-know question, or low-stakes reaction instead of requiring a hardcoded trigger to fire first
- Kept trigger detectors as cheap context hints and a provider-outage fallback, while escalation blocking, confidence thresholds, privacy, cooldowns, and Discord execution remain code-enforced
- Made the native agent the primary semantic memory path when enabled; the legacy regex extractor now runs only when agent tooling is disabled, preventing duplicate/conflicting facts
- Added participant and source-message validation for quiet observation so learned facts stay attached to the person who actually said them
- Added planner, attribution, and quiet-observation regression coverage

## 2026-09-13 - native bounded agent tools
- Added native Gemini function-call parsing plus OpenRouter-compatible tool payloads instead of relying only on prompt instructions
- Added an allowlisted tool contract for validated `remember_fact`, profile/context lookup, and `react_to_message` actions
- Direct and autonomous text turns can now request safe tool actions; the Brain enforces privacy, schema, cooldown, permission, and tool-count limits before execution
- Kept a normal Gemini/OpenRouter text fallback when tool calls fail, and added parser/executor/payload tests
- Added quiet autonomous observation: when a safe conversation is not worth a visible reply, the agent can still remember directly stated facts without posting; escalation contexts are excluded
- Added a read-only `get_recent_updates` tool so natural questions about Bombaclat's updates are answered from the verified changelog in its own voice
- Owner-only natural phrases like `Restart`, `can you restart yourself`, `logoff`, or `can you boot off` now reuse the safe lifecycle path even when prefixed by a direct `@Bombaclat` mention, send a short confirmation, and then restart or stop; non-owners cannot trigger them
- Owner-only private orders now use a native model parser for indirect/slang variations such as `ask them to`, `make sure they`, or `get them to`, then resolve the target, find a recent shared server/GC, forward the instruction, and confirm only after Discord accepts it

## 2026-09-13 - documented future owner review loop (not implemented)
- Added `IDEAS.md` with a future design for sending autonomous decision context to the owner and allowing focused approve/reject/correction conversations
- Documented privacy, persistence, idempotency, opt-in delivery, and anti-spam requirements
- No runtime behavior changed by this idea entry

## 2026-09-13 - contextual memory extraction fix
- Fixed interest learning from sentences like `tame impala is a goated singer i love that dude bro`, which now attaches the interest to `tame impala` instead of storing the vague tail `i love that dude bro`
- Standalone vague interest phrases such as `i love that dude` are now ignored instead of becoming misleading long-term memories
- Added regression coverage for contextual subject extraction and vague-memory rejection
- Broadened the contextual matcher to handle casual variants such as `djio is goated dude i love that singer imo`

## 2026-09-13 - human-like wake-up, user learning, and social reactions
- Replaced the single repetitive no-update restart line with one natural wake-up message selected from a small local pool, while keeping restart announcements exactly once per pending restart
- Expanded safe fact learning for common statements such as games, music, names, preferences, and goals, and added lightweight per-user communication style signals
- Fixed the get-to-know trigger so its signal reaches the reasoning threshold instead of silently declining every opportunity
- Preserved a curated set of emojis in generated replies and added occasional reaction-only actions for low-stakes banter, celebrations, and boredom with per-user, channel, and hourly safeguards
- Added tests covering social fact extraction, get-to-know decisions, emoji cleaning, and reaction policy selection

## 2026-09-13 - Gemini text fallback through OpenRouter
- Added `thinkingmachines/inkling-small:free` as a bounded OpenRouter text fallback when Gemini fails, times out, or is locally rate-limited
- Added safe fallback selection logging, short 429 retries, timeout handling, and a local last-resort reply so a provider outage does not crash the bot
- Added `OPENROUTER_TEXT_MODEL` configuration and documented fallback testing

## 2026-09-13 - expanded vision rate-limit retries
- Increased vision rate-limit handling from 2 retries to 5 retries, for up to 6 total attempts
- Raised the retry backoff ceiling to 10 seconds so free-tier rate-limit windows have more time to clear while remaining bounded

## 2026-09-13 - vision request matching and retry follow-ups
- Normalized common caption variations such as `whats this` and harmless transposed letters so repeated image questions still route to vision
- Added contextual follow-up phrases such as `send it over`, `drop it again`, and `lets see it` for image-only replies after Bombaclat asks for the attachment
- Added safe skipped-route logging so missed image requests can be diagnosed without logging message contents or image data

## 2026-09-13 - vision response budget and provider parsing fix
- Increased the vision output budget and explicitly disabled Ling VL thinking mode so the model returns an actual visual answer instead of exhausting the response limit
- Added safe parsing for alternate OpenRouter-compatible text response shapes and diagnostic finish-reason metadata without logging raw model output

## 2026-09-13 - stop command and vision routing diagnostics
- Added owner-only `!stop`, which sends a shutdown message and closes the process without replacing it
- Explicit image requests can no longer fall through to the text model when vision is disabled or the OpenRouter key is missing; they return the honest vision fallback instead
- Added structured route logs showing whether a request selected vision, whether the key is configured, and which model was selected

## 2026-09-13 - contextual vision follow-ups
- Image-only replies to Bombaclat's recent request to send or attach an image now route through the real vision client instead of the text model
- Added reply-reference and recent-conversation detection so Bombaclat no longer claims it cannot see image bytes after the user provides the requested attachment
- Unrelated public image posts remain silent

## 2026-09-13 - vision api
- Added vision API
- Added vision API key presence check and model validation
- Added vision API rate limit handling
- Added vision API usage tracking
- Added vision API error handling

## 2026-09-13 - vision command controls
- Added owner-only `!vision on|off|status` so vision can be controlled and inspected without editing config manually
- Added safe status output for the configured model, API-key presence, and public-social mode without exposing secrets

## 2026-09-13 - owner restart command and startup update announcement
- Added owner-only `!restart`, which verifies the pre-restart message, persists the target channel, replaces the process, and announces after Discord reconnects
- Added changelog baseline tracking so the wake-up message lists only updates since the previous startup, or says `alright im back guys` when there are none
- Added restart coverage to the owner help text, README, and testing checklist

## 2026-09-13 - OpenRouter vision requests and image privacy routing
- Added an OpenRouter vision client configured for `inclusionai/ling-3.0-flash-vl:free`, with in-memory image data, safe size/type validation, and no raw image content or URLs in logs
- Added explicit vision routing for true private DMs and direct Bombaclat mentions; ordinary public image posts remain silent during autonomous evaluation
- Added one hardcoded `hold on im fetching the image` status before a valid vision request, bounded retries for provider rate limits, timeout handling, and an honest fallback when inspection fails
- Added prompt rules for visible-fact versus guess separation, brief social-image hype with at most one natural follow-up, and permanently prohibited em dash punctuation in generated replies
- Added optional `VISION_PUBLIC_SOCIAL_ENABLED` routing for a later social-image mode, disabled by default

## 2026-09-13 - changelog command and change-tracking rule
- Added owner-only `!changelog [n]` to display recent code and behavior updates
  directly from `CHANGELOG.md`
- Established that every meaningful code/behavior change must add a changelog
  entry before the work is considered complete

## 2026-09-13 - verified owner actions and context continuity
- Added owner-only natural `tell/message/send` handling in private DMs plus
  `!tell <user_id|name> <text>` for explicit actions
- Owner orders now resolve the target, find a recent shared server/GC channel,
  send the exact text, and confirm only after Discord accepts the message
- Added an anti-hallucination rule: Bombaclat cannot claim an action completed
  without a verified send result
- Fixed database default-path resolution so isolated tests and runtime overrides
  cannot accidentally use an old path captured during module import

## 2026-09-13 - attachment-aware context and quieter image handling
- Discord attachments are now represented in context with safe filenames and
  type metadata instead of becoming empty messages
- Image/file-only posts no longer trigger autonomous replies on their own
- Directly mentioned attachments prompt Bombaclat to ask what help is wanted;
  it will not pretend to see or understand an image it has not actually read

## 2026-09-13 - help-first task handling and calmer personality
- Added explicit help/task response mode so genuine requests take priority over
  spam banter, including natural phrases like `help me`, `how to`, and `dyk how`
- Repeated messages inside one response batch are now treated as one request,
  not several reasons to scold the person
- Technical/task prompts may receive concise actionable steps or one precise
  clarifying question instead of a performative roast
- Added a final help-mode response guard that replaces overtly hostile model
  output with a useful clarifying question rather than sending it
- Reduced the persona's default hostility while preserving light teasing for
  genuinely empty or abusive spam

## 2026-09-13 - conversation batching, safer autonomy, and runtime hardening
- Added channel-level response batching so rapid pings and overlapping messages
  are read as one recent conversation instead of producing one reply per event
- Added message IDs, command filtering, and uniqueness protection so outgoing
  bot messages are not duplicated in prompt history
- Autonomous evaluation now waits for a quiet moment and skips unchanged
  conversation state, sharply reducing repetitive decisions and Gemini calls
- Added persistent per-user/channel get-to-know cooldowns and made the trigger
  intentionally weaker so Bombaclat does not interrupt every unfamiliar person
- Disabled routine owner decline DMs by default; decisions remain available via
  `!think`, `!recent`, and explicit feedback
- Added an outbound DM CAPTCHA circuit breaker that stops retries after Discord
  requests verification instead of repeatedly provoking the same failure
- Scoped sensitive memories to their original private DM, filtered transient
  emotional venting, and stopped writing sensitive memory text to INFO logs
- Added startup retention cleanup, runtime `!config` application, structured
  batch/decision/Gemini event logging, and quieter third-party HTTP logs
- Strengthened escalation blocking so clear hostile exchanges take priority over
  curiosity or banter triggers

## 2026-09-08 - GC/DM fix, get-to-know trigger, and !recent
- Fixed a real bug: Group DMs (GCs) were being treated as 1-on-1 DMs and got
  a reply to every message instead of only on mention - the bot now
  correctly distinguishes `DMChannel` from `GroupChannel` and behaves like a
  normal server channel in group settings
- Added an `is_private_dm` column to `channel_settings` with an automatic,
  lossless migration for existing databases
- Added a new `get_to_know` autonomous trigger: when someone active in a
  chat has no stored memories yet, the bot may organically ask about them,
  gated through the LLM reasoner so it doesn't feel forced
- Broadened passive memory fact-extraction patterns (pets, hobbies, school,
  relationships, goals, currently playing/watching/reading)
- Added `!recent` - a markdown-formatted report of recently learned facts,
  recent autonomous activity, live stats, and this changelog
- Added extra structured logging around autonomous decisions and newly
  learned memories so `data/bot.log` captures a full narrative of what the
  bot has been doing

## 2026-09-08 - Autonomous brain, persistent memory, and terminal UI
- Migrated all conversation history, user profiles, and learned behavior
  from in-memory-only storage to a persistent SQLite database (WAL mode,
  auto-migrating schema) - nothing resets on restart anymore
- Built the decision engine: sadness / celebration / help-request / boredom
  / banter / curiosity detectors, each with an independently learned weight
  that adjusts from owner feedback and organic engagement (replies,
  reactions) after an unsolicited post
- Added a hard, non-learnable escalation safety check - the bot never
  overrides staying quiet during a real argument, no matter how much
  positive feedback an escalation-adjacent trigger has received elsewhere
- Added an LLM-backed reasoner for borderline autonomous decisions, with a
  short logged explanation for every post or decline
- Added an owner feedback loop: on "close call" declines the bot DMs
  Koryei a two-sentence explanation and takes `!feedback approve/reject`
- Added passive, safety-filtered memory extraction (sensitive facts never
  surface outside true 1-on-1 DMs) and situational personality tone
  (supportive / hyper / help / chill / dismissive / curious), blended from
  trigger type, the person's rolling vibe profile, and time of day
- Added autonomous presence control (status, activity, bio) that evolves on
  its own based on aggregate conversation energy
- Added a full owner command suite: `!config`, `!autonomous`, `!status`,
  `!activity`, `!bio`, `!mood`, `!think`, `!weights`, `!feedback`,
  `!memory`, `!dm`, `!help`
- Added a neofetch/fastfetch-style green boot banner and a live-updating
  terminal dashboard (uptime, messages seen, autonomous activity, API
  usage) built with `rich` + `pyfiglet`, with logs coordinating cleanly
  above the live display

## 2026-09-08 - Initial stable release
- Rebuilt the bot on `discord.py-self` + the modern `google-genai` SDK
- Master system prompt: lowercase, 1-3 sentence, chaotic-friend persona with
  anti-jailbreak and anti-spam handling
- Sliding per-channel history buffer (15 messages, `[Username]: message`
  format)
- Local rolling rate limiter (30 requests / 60s) to stay under the free-tier
  ceiling without ever throwing a 429
- Robust error handling around every generation call (timeout + API error
  fallbacks, never a terminal crash)
- Switched from `gemma-4-31b-it` (18-20s latency, frequent 500s) to
  `gemini-3.5-flash-lite` (0.6-0.7s latency, stable)
