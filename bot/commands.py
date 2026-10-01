"""Owner-only slash-free command system (plain-text prefix commands, since
this runs on a self-bot account and real slash commands aren't available).

Every command here is gated to config.OWNER_ID - Koryei is the only one who
can reconfigure the bot's behavior, view its reasoning, or give it feedback.
"""

import logging

import config
from utils.changelog import get_latest_entries, get_recent_entries

logger = logging.getLogger(__name__)

_HELP_TEXT = (
    "bombaclat commands:\n"
    "!config [key] [value] - view or set a config value\n"
    "!vision on|off|status - control image vision requests\n"
    "!gif learn [limit] [force] - classify GIFs from this channel once\n"
    "!gif list [n] - show the learned GIF library\n"
    "!gif gallery [n] - show learned GIFs with previewable URLs\n"
    "!server list|join <invite>|leave [guild_id] - manage servers\n"
    "!friend status|list|accept|block|unblock|remove|auto - manage relationships\n"
    "!captcha status|acknowledge - inspect or manually clear the CAPTCHA guard\n"
    "!autonomous on|off - toggle autonomous posting in this channel\n"
    "!reviews on|off|important|full|digest|status - owner review delivery\n"
    "!review <decision_id>|digest|preview <channel_id> on|off\n"
    "!status <online|idle|dnd|invisible>\n"
    "!activity <playing|listening|watching|streaming|competing> <text>\n"
    "!bio <text>\n"
    "!mood - show current personality snapshot for this channel\n"
    "!recent [n] - markdown report: what it's learned, done, and how it's changed\n"
    "!changelog - show the curated latest changes feed\n"
    "!changelog [n] - show the latest n sections from the full changelog archive\n"
    "!think [n] - show the last n autonomous decisions\n"
    "!weights - show learned trigger weights\n"
    "!feedback <approve|reject> <decision_id>\n"
    "!humor good|bad [note] - rate a bot reply (reply to it first)\n"
    "!humor status - show humor calibration feedback\n"
    "!memory list [user_id]\n"
    "!memory add <user_id> <text>\n"
    "!memory forget <memory_id>\n"
    "!dm <user_id> <text>\n"
    "!tell <user_id|name> <text> - send exact text to a recent shared server/GC\n"
    "!restart - restart the process and announce changelog updates on return\n"
    "!stop - shut down the process without restarting\n"
    "!help"
)

_MAX_CHUNK = 1900


async def handle_command(brain, message) -> bool:
    """Returns True if the message was recognized and handled as a command."""
    if message.author.id != config.OWNER_ID:
        return False

    content = message.content.strip()
    if not content.startswith(config.COMMAND_PREFIX):
        return False

    parts = content[len(config.COMMAND_PREFIX):].strip().split()
    if not parts:
        return False

    cmd, *args = parts
    cmd = cmd.lower()

    try:
        reply = await _dispatch(brain, message, cmd, args)
    except Exception:
        logger.exception("Command handling failed for %s", cmd)
        reply = "that command blew up, check the logs"

    if reply:
        chunks = _chunk_text(reply)
        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    await message.reply(chunk, mention_author=False)
                else:
                    await message.channel.send(chunk)
            except Exception as exc:
                brain.note_discord_delivery_error(exc, "owner command response")
                logger.warning("Could not deliver command response for %s: %s", cmd, exc)
                break
    return True


def _chunk_text(text: str, limit: int = _MAX_CHUNK) -> list[str]:
    """Splits long command output on line boundaries so nothing gets cut
    mid-word/mid-markdown, and so it fits Discord's message length limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def _dispatch(brain, message, cmd: str, args: list[str]) -> str | None:
    if cmd == "help":
        return _HELP_TEXT

    if cmd == "config":
        return await _cmd_config(brain, args)

    if cmd == "vision":
        return await _cmd_vision(brain, args)

    if cmd == "gif":
        return await _cmd_gif(brain, message, args)

    if cmd == "server":
        return await _cmd_server(brain, message, args)

    if cmd == "friend":
        return await _cmd_friend(brain, args)

    if cmd == "captcha":
        return _cmd_captcha(brain, args)

    if cmd == "autonomous":
        return await _cmd_autonomous(brain, message, args)

    if cmd == "reviews":
        return await _cmd_reviews(brain, message, args)

    if cmd == "review":
        return await _cmd_review(brain, message, args)

    if cmd == "status":
        return await _cmd_status(brain, args)

    if cmd == "activity":
        return await _cmd_activity(brain, args)

    if cmd == "bio":
        return await _cmd_bio(brain, args)

    if cmd == "mood":
        return await _cmd_mood(brain, message)

    if cmd == "recent":
        return await _cmd_recent(brain, message, args)

    if cmd == "changelog":
        return await _cmd_changelog(args)

    if cmd == "think":
        return await _cmd_think(brain, args)

    if cmd == "weights":
        return await _cmd_weights(brain)

    if cmd == "feedback":
        return await _cmd_feedback(brain, args)

    if cmd == "humor":
        return await _cmd_humor(brain, message, args)

    if cmd == "memory":
        return await _cmd_memory(brain, args)

    if cmd == "dm":
        return await _cmd_dm(brain, args)

    if cmd == "tell":
        return await _cmd_tell(brain, args)

    if cmd == "restart":
        return await _cmd_restart(brain, message)

    if cmd == "stop":
        return await _cmd_stop(brain, message)

    return "unknown command, try !help"


async def _cmd_config(brain, args: list[str]) -> str:
    if not args:
        all_config = await brain.repo.get_all_config()
        if not all_config:
            return "no config overrides set"
        return "\n".join(f"{k} = {v}" for k, v in all_config.items())

    key = args[0]
    if len(args) == 1:
        value = await brain.repo.get_config(key)
        return f"{key} = {value}" if value is not None else f"{key} is not set"

    value = " ".join(args[1:])
    if not config.apply_override(key, value):
        return "that is not a supported runtime setting or the value is invalid"
    await brain.repo.set_config(key, value)
    return f"set {key} = {value}"


async def _cmd_vision(brain, args: list[str]) -> str:
    action = args[0].lower() if args else "status"
    if action == "status":
        key_state = "configured" if config.OPENROUTER_API_KEY else "missing key"
        enabled_state = "on" if config.VISION_ENABLED else "off"
        social_state = "on" if config.VISION_PUBLIC_SOCIAL_ENABLED else "off"
        return (
            f"vision {enabled_state} | model {config.OPENROUTER_VISION_MODEL} | "
            f"api key {key_state} | public social {social_state}"
        )

    if action not in {"on", "off"}:
        return "usage: !vision on|off|status"

    enabled = action == "on"
    if enabled and not config.OPENROUTER_API_KEY:
        return "vision stays off because OPENROUTER_API_KEY is missing from .env"
    config.VISION_ENABLED = enabled
    await brain.repo.set_config("VISION_ENABLED", action)
    return f"vision {action}"


async def _cmd_gif(brain, message, args: list[str]) -> str:
    action = args[0].lower() if args else "status"
    if action == "status":
        rows = await brain.repo.list_gifs(limit=500)
        return (
            f"GIFs {'on' if config.GIFS_ENABLED else 'off'} | learned {len(rows)} | "
            f"vision {'configured' if config.OPENROUTER_API_KEY and config.VISION_ENABLED else 'unavailable'}"
        )
    if action == "list":
        limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
        return await brain.gif_library_report(limit=min(limit, 50))
    if action in {"gallery", "show", "all"}:
        limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 50
        return await brain.gif_library_report(limit=min(limit, 50), title="GIF gallery")
    if action == "learn":
        limit = 100
        force = False
        for arg in args[1:]:
            if arg.lower() == "force":
                force = True
            elif arg.isdigit():
                limit = int(arg)
        return await brain.learn_gifs_from_channel(message.channel, limit=limit, force=force)
    return "usage: !gif learn [limit] [force] | !gif list [n] | !gif gallery [n] | !gif status"


async def _cmd_server(brain, message, args: list[str]) -> str:
    action = args[0].lower() if args else "list"
    target = " ".join(args[1:]) if len(args) > 1 else None
    return await brain.server_admin(
        action,
        target,
        current_guild=getattr(message, "guild", None),
        announce_channel=getattr(message, "channel", None),
    )


async def _cmd_friend(brain, args: list[str]) -> str:
    action = args[0].lower() if args else "status"
    target = " ".join(args[1:]) if len(args) > 1 else None
    return await brain.friend_admin(action, target)


def _cmd_captcha(brain, args: list[str]) -> str:
    action = args[0].lower() if args else "status"
    if action == "status":
        return brain.captcha_status()
    if action == "acknowledge":
        return brain.captcha_acknowledge()
    return "usage: !captcha status|acknowledge"


async def _cmd_autonomous(brain, message, args: list[str]) -> str:
    if not args or args[0].lower() not in ("on", "off"):
        return "usage: !autonomous on|off"
    enabled = args[0].lower() == "on"
    channel_id = message.channel.id
    guild_id = message.guild.id if message.guild else None
    await brain.repo.ensure_channel(
        channel_id,
        guild_id,
        getattr(message.channel, "name", "dm"),
        is_private_dm=type(message.channel).__name__ == "DMChannel",
    )
    await brain.repo.set_channel_autonomous(channel_id, enabled)
    return f"autonomous mode {'enabled' if enabled else 'disabled'} for this channel"


async def _cmd_reviews(brain, message, args: list[str]) -> str:
    action = args[0].lower() if args else "status"
    if action == "status":
        return await brain.owner_review_status()
    if action == "digest":
        return await brain.review_digest_for_owner(message)
    return await brain.configure_owner_reviews(action)


async def _cmd_review(brain, message, args: list[str]) -> str:
    if not args:
        return "usage: !review <decision_id> | digest | preview <channel_id> on|off"
    if args[0].lower() == "digest":
        return await brain.review_digest_for_owner(message)
    if args[0].lower() == "preview":
        if len(args) != 3 or not args[1].isdigit() or args[2].lower() not in {"on", "off"}:
            return "usage: !review preview <channel_id> on|off"
        return await brain.set_review_preview(int(args[1]), args[2].lower() == "on")
    if not args[0].isdigit():
        return "usage: !review <decision_id> | digest | preview <channel_id> on|off"
    return await brain.review_report_for_owner(int(args[0]), message)


async def _cmd_status(brain, args: list[str]) -> str:
    if not args:
        return "usage: !status <online|idle|dnd|invisible>"
    ok = await brain.presence.set_status(args[0])
    return f"status set to {args[0]}" if ok else "couldn't set that status"


async def _cmd_activity(brain, args: list[str]) -> str:
    if len(args) < 2:
        return "usage: !activity <playing|listening|watching|streaming|competing> <text>"
    ok = await brain.presence.set_activity(" ".join(args[1:]), args[0])
    return "activity updated" if ok else "couldn't set that activity"


async def _cmd_bio(brain, args: list[str]) -> str:
    if not args:
        return "usage: !bio <text>"
    ok = await brain.presence.update_bio(" ".join(args))
    return "bio updated" if ok else "couldn't update bio"


async def _cmd_mood(brain, message) -> str:
    user_vibe = await brain.repo.get_user(message.author.id)
    now = brain._presence_now()
    from core.personality import determine_tone

    state = determine_tone(None, user_vibe, now.hour, now.minute)
    return f"tone: {state.tone}, energy: {state.energy:.2f}, formality: {state.formality:.2f}"


async def _cmd_recent(brain, message=None, args: list[str] | None = None) -> str:
    # Keep the old helper shape usable by lightweight tests that call
    # _cmd_recent(brain, args) directly.
    if args is None and isinstance(message, list):
        args, message = message, None
    args = args or []
    limit = 5
    if args and args[0].isdigit():
        limit = min(int(args[0]), 10)

    stats = brain.stats
    used, cap = brain.gemini.limiter.current_usage()
    is_private_dm = message is None or type(message.channel).__name__ == "DMChannel"
    memories = await brain.repo.list_memories_with_usernames(limit=limit)
    decisions = await brain.repo.get_recent_decisions(limit=limit)
    changelog_entries = get_recent_entries(limit=3)

    sections = [
        (
            "**bombaclat - recent activity report**\n"
            f"uptime `{stats.uptime_str()}` | messages seen `{stats.messages_seen}` | replies sent `{stats.replies_sent}`\n"
            f"autonomous posts `{stats.autonomous_posts}` | declines `{stats.autonomous_declines}` | "
            f"reactions `{stats.reactions_sent}` | owner dms `{stats.owner_dms_sent}`\n"
            f"memories stored `{stats.memories_stored}` | batches sent `{stats.batches_formed}` | "
            f"api usage `{used}/{cap} per min` | api errors `{brain.gemini.calls_failed}` | "
            f"outbound dms {'paused' if brain.outbound_dms_suspended else 'available'}"
        )
    ]

    memory_lines = ["\n**recently learned about people**"]
    if memories:
        for m in memories:
            if m["is_sensitive"] and not is_private_dm:
                continue
            who = m["username"] or f"user {m['about_user_id']}"
            memory_lines.append(f"- **{who}**: {m['memory_text']}")
        if len(memory_lines) == 1:
            memory_lines.append("- no shareable memories in this context")
    else:
        memory_lines.append("- nothing learned yet")
    sections.append("\n".join(memory_lines))

    decision_lines = ["\n**recent autonomous activity**"]
    if decisions:
        for d in decisions:
            verb = (
                "reacted" if d["decision"] == "react"
                else "spoke up" if d["decision"] == "post"
                else "stayed quiet"
            )
            trigger = d["trigger_type"] or "no trigger"
            feedback = f" [{d['owner_feedback']}]" if d["owner_feedback"] else ""
            decision_lines.append(
                f"- {verb} (`{trigger}`, conf {d['confidence']:.2f}): {d['reasoning']}{feedback}"
            )
    else:
        decision_lines.append("- no autonomous decisions logged yet")
    sections.append("\n".join(decision_lines))

    changelog_lines = ["\n**recent code updates**"]
    if changelog_entries:
        for entry in changelog_entries:
            changelog_lines.append(f"- **{entry['title']}**")
            for bullet in entry["bullets"][:4]:
                changelog_lines.append(f"  - {bullet}")
    else:
        changelog_lines.append("- no changelog found")
    sections.append("\n".join(changelog_lines))

    return "\n".join(sections)


async def _cmd_changelog(args: list[str]) -> str:
    if args and args[0].isdigit():
        limit = min(int(args[0]), 15)
        entries = get_recent_entries(limit=limit)
        heading = f"**bombaclat changelog archive, latest {limit} sections**"
    else:
        entries = get_latest_entries(limit=10)
        heading = "**bombaclat latest changes**"
    if not entries:
        return "no changelog entries found"

    lines = [heading]
    for entry in entries:
        lines.append(f"\n**{entry['title']}**")
        lines.extend(f"- {bullet}" for bullet in entry["bullets"])
    return "\n".join(lines)


async def _cmd_think(brain, args: list[str]) -> str:
    limit = 5
    if args and args[0].isdigit():
        limit = min(int(args[0]), 20)
    decisions = await brain.repo.get_recent_decisions(limit=limit)
    if not decisions:
        return "no decisions logged yet"
    lines = []
    for d in decisions:
        feedback = f" [{d['owner_feedback']}]" if d["owner_feedback"] else ""
        lines.append(
            f"#{d['id']} {d['decision']} ({d['trigger_type'] or 'none'}, "
            f"conf={d['confidence']:.2f}): {d['reasoning']}{feedback}"
        )
    return "\n".join(lines)


async def _cmd_weights(brain) -> str:
    weights = await brain.repo.get_all_trigger_weights()
    if not weights:
        return "no learned weights yet, still using defaults"
    return "\n".join(
        f"{w['trigger_type']}: {w['weight']:.2f} (+{w['success_count']}/-{w['failure_count']})"
        for w in weights
    )


async def _cmd_feedback(brain, args: list[str]) -> str:
    if len(args) < 2 or not args[1].isdigit():
        return "usage: !feedback <approve|reject|adjust> <decision_id> [correction]"
    verdict = args[0].lower()
    if verdict not in {"approve", "reject", "adjust"}:
        return "usage: !feedback <approve|reject|adjust> <decision_id> [correction]"
    note = " ".join(args[2:]) if verdict == "adjust" else ""
    return await brain.handle_feedback(int(args[1]), verdict, note=note, source="command")


async def _cmd_humor(brain, message, args: list[str]) -> str:
    return await brain.humor_feedback_from_command(message, args)


async def _cmd_memory(brain, args: list[str]) -> str:
    if not args:
        return "usage: !memory list [user_id] | !memory add <user_id> <text> | !memory forget <id>"

    sub = args[0].lower()
    if sub == "list":
        user_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        memories = await brain.repo.list_memories(user_id=user_id, limit=15)
        if not memories:
            return "no memories stored"
        return "\n".join(f"#{m['id']} (about {m['about_user_id']}): {m['memory_text']}" for m in memories)

    if sub == "add":
        if len(args) < 3 or not args[1].isdigit():
            return "usage: !memory add <user_id> <text>"
        from core.models import MemoryCandidate

        candidate = MemoryCandidate(
            about_user_id=int(args[1]), memory_text=" ".join(args[2:]), category="manual", confidence=1.0
        )
        await brain.repo.add_memory(candidate)
        return "memory added"

    if sub == "forget":
        if len(args) < 2 or not args[1].isdigit():
            return "usage: !memory forget <memory_id>"
        await brain.repo.delete_memory(int(args[1]))
        return "memory forgotten"

    return "usage: !memory list [user_id] | !memory add <user_id> <text> | !memory forget <id>"


async def _cmd_tell(brain, args: list[str]) -> str:
    if len(args) < 2:
        return "usage: !tell <user_id|name> <text>"
    return await brain.tell_user_in_shared_channel(args[0], " ".join(args[1:]))


async def _cmd_restart(brain, message) -> str | None:
    return await brain.restart_from_owner_message(message)


async def _cmd_stop(brain, message) -> str | None:
    return await brain.stop_from_owner_message(message)


async def _cmd_dm(brain, args: list[str]) -> str:
    if len(args) < 2 or not args[0].isdigit():
        return "usage: !dm <user_id> <text>"
    if brain.outbound_dms_suspended:
        return "outbound dms are paused because discord requested a captcha; restart only after handling it manually"
    ok = await brain.dm_user(int(args[0]), " ".join(args[1:]))
    if ok:
        return "sent"
    if brain.outbound_dms_suspended:
        return "outbound dms paused after discord requested a captcha"
    return "couldn't send that dm"
