# Latest Bombaclat Changes

This file is the curated current update feed. `CHANGELOG.md` remains the complete historical archive.

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

## 2026-09-14 - tool-call text can never be sent as a reply
- Fixed a leak where the model wrote a function call as prose (`declaration:default_api:search_public_web...`) and it was delivered as the Discord message
- Tools the current turn is not authorized to use are no longer offered to the model, so a blocked call cannot be attempted or narrated
- Added leak detection in the agent loop plus a final response-sanitizer net, so internal tool names never reach chat through any path
- A failed lookup with image context now answers the visible question and states plainly that current info could not be pulled

## 2026-09-14 - fixed over-strict search relevance filter
- Root cause of repeated `i couldn't find a useful current result` replies: the relevance filter required every query token to appear in a result, so filler words such as `information` disqualified correct pages
- Generic request words (`information`, `identify`, `about`, `details`, `know`, `more`) are now treated as stopwords instead of topic requirements
- Long multi-word subjects now tolerate one missing token, while short queries still require full topic coverage so unrelated results stay rejected
- Verified live: `porsche 911 gt3 rs latest information` now returns dated results through the production search path

## 2026-09-14 - native multimodal orchestration
- Directly addressed images now enter the same native agent turn as text instead of being forced through a separate vision-only response pipeline
- Gemini and OpenRouter fallbacks preserve image input while the model independently chooses ordinary dialogue or an allowlisted tool
- Validated tool results can be fed through bounded follow-up turns, enabling dynamic sequences such as search followed by public-page reading without hard-coded pipelines
- Added explicit orchestration budgets with `AGENT_MAX_TOOL_CALLS` and `AGENT_MAX_ORCHESTRATION_STEPS`, plus regression coverage for multimodal payloads and multi-tool execution

## 2026-09-14 - Serper conversational query fix
- Current searches now remove conversational lead-ins such as `oh wow thats nice can you search` before sending the actual topic to Serper
- Minecraft current searches use a `site:minecraft.net` query restriction so Serper returns official update evidence instead of unrelated pages
- Added routing coverage for conversational GTA follow-ups and confirmed the exact screenshot wording returns usable GTA 6 results

## 2026-09-14 - Serper current-information search
- Replaced the LangSearch production adapter with a bounded Serper Web Search API client while preserving the `search_public_web` tool contract and smart routing behavior
- Added Serper organic-result normalization, Google freshness parameters, relative-date parsing, safe failure states, caching, HTTPS filtering, and existing Minecraft official-source safeguards
- Updated configuration, tests, setup documentation, and provider-specific logs to use `SERPER_*` settings

## 2026-09-14 - stricter current-search relevance
- Current searches now require the full topic instead of allowing unrelated pages that match one generic word
- Minecraft update/news searches require official Minecraft-domain evidence and reject stale year claims even when a provider labels them recent
- When no trustworthy evidence survives, the bot gives the honest no-result response rather than inventing a current answer or using a special-case source path
- Added regression coverage for unrelated provider matches, official-domain filtering, stale titles, and honest no-result behavior

## 2026-09-14 - restart updates now detect edited entries
- Restart announcements now compare update titles and bullet content instead of only section titles
- Existing title-only tracking is migrated safely so a changed current entry is not silently skipped

## 2026-09-14 - LangSearch smart current-information search
- Current questions use a bounded LangSearch Web Search API client with normalized HTTPS results, summaries, caching, a one-request-per-second free-tier gate, and safe failure states
- Smart routing searches clear current requests, asks before ambiguous lookups, answers timeless questions normally, and keeps Bombaclat changelog questions local
- The model still chooses ordinary tool use; a narrow application backstop prevents an unmistakably current request from being answered from stale memory
- Autonomous planning remains separate, and arbitrary provider result pages are not automatically crawled
- Follow-up searches now preserve rumor/unconfirmed qualifiers, compare earlier Bombaclat claims, explicitly correct changed claims, and avoid treating missing coverage as proof
- Source URLs now keep their punctuation through response cleaning, so citations remain clickable
- Upcoming-month searches now use a bounded freshness window and reject stale dated pages before they reach the model
- Prompts now include authoritative local/UTC clock context, and validated current searches include an `as of` date anchor


## 2026-09-13 - deterministic current-info tool routing
- Clear questions about latest or recent news, game updates, and patch notes now invoke the bounded web-search tool before Bombaclat writes a reply
- Bombaclat changelog questions stay on the verified local changelog path instead of being sent to the public web

## 2026-09-13 - current questions beat repeat-ping jokes
- Natural questions without punctuation, including recent game updates, are now treated as real requests instead of empty spam
- Bombaclat can use the public web tools for current news, game updates, and patch notes before making a joke about the search

## 2026-09-13 - more human humor and context callbacks
- Tuned Bombaclat's voice to react to the exact conversation with dry observations, callbacks, and playful disbelief instead of generic assistant jokes
- Replaced bland restart wake-up lines with short context-friendly messages, while keeping help answers useful and preventing web-search fallbacks from inventing facts

## 2026-09-13 - latest changes feed
- Added a dedicated latest-update source so natural changelog questions and plain `!changelog` do not accidentally answer from an older archive entry
- Use `!changelog N` when you want the latest N sections from the full historical `CHANGELOG.md` archive

## 2026-09-13 - BETA utility agent tools
- Added BETA reminders with persistent SQLite storage, bounded delays, creator/owner cancellation, and background delivery
- Added BETA read-only public web search and public HTTPS page summaries with network, credential, content-size, and content-type guards
- Added a BETA safe calculator for arithmetic, percentages, dates, unit conversions, and token-cost math without code execution

## 2026-09-13 - context-aware vision replies
- Removed the interim image-fetching message so explicit image questions produce one final response
- Vision replies now prioritize the user's actual joke or question instead of narrating attachments or treating usage statistics as a dollar bill

## 2026-09-13 - model-assisted owner orders
- Private owner orders can use natural indirect or slang phrasing, resolve the target, find a recent shared GC/server, and forward the instruction after a verified send
- Direct lifecycle mentions such as `@Bombaclat yo bro could u logoff` use the real restart/stop path instead of a normal AI reply
