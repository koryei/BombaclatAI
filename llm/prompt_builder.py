import time
from typing import Optional

import config
from core.models import MessageRecord, PersonalityState
from core.personality import describe_state
from core.time_context import current_time_context


def build_prompt(
    history: list[MessageRecord],
    spam_count: int = 0,
    personality: Optional[PersonalityState] = None,
    memories_block: str = "",
    owner_present: bool = False,
    autonomous_reason: Optional[str] = None,
    batch_id: Optional[str] = None,
    response_intent: Optional[str] = None,
    batch_size: int = 1,
    vision_active: bool = False,
    profiles_block: str = "",
    humor_calibration: str = "",
) -> str:
    transcript = "\n".join(
        f"[{time_label(m.timestamp)}] [{m.author_name}]: {clean_message(m.content)}"
        for m in history
    )
    clock_note = (
        "\n<clock_context>\n"
        f"{current_time_context()}\n"
        "Use this clock as authoritative for today, dates, relative time, and upcoming periods; "
        "do not guess the current date from model memory.\n"
        "</clock_context>"
    )

    # A burst is one request, not several separate annoyances. Help/task mode
    # also suppresses the annoyance cue so usefulness cannot be overridden by
    # the persona's banter rule.
    spam_note = (
        "\nthe user has sent several separate empty pings recently; if you mention it, keep it playful and brief"
        if spam_count >= 4 and response_intent != "help" and batch_size <= 1
        else ""
    )
    intent_note = (
        "\nthis is a genuine help or task request: answer the actual request first, "
        "give concise actionable steps when possible, do not roast them, and ask "
        "one precise follow-up only if an essential detail is missing"
        if response_intent == "help"
        else ""
    )
    burst_note = (
        f"\nthis response covers {batch_size} messages from one recent burst; treat them as one request, not spam"
        if batch_size > 1
        else ""
    )
    attachment_note = (
        "real image input is available for this request; describe only what is visibly supported, "
        "separate observations from guesses, mention unreadable details, and answer the user's "
        "actual question without claiming certainty you do not have. If this is a social share, "
        "match the chat's excitement briefly and ask at most one natural follow-up question"
        if vision_active
        else (
            "\nan image or file was attached; do not pretend you can see or understand its contents "
            "from the filename alone, and ask what they want you to look at if they need help"
            if any(m.is_attachment_only for m in history)
            else ""
        )
    )
    tone_note = f"\n{describe_state(personality)}" if personality else ""
    anti_slop_note = (
        "\n<comedy_filter>\n"
        "if you try to be funny, anchor it to one concrete noun, number, action, or callback from the chat. "
        "do not use a stock reaction that would fit a random post, do not repeat the user's premise as a joke, "
        "and do not add a second joke just because the first line was short. if there is no specific comedic angle, "
        "be direct or sincere instead.\n"
        "</comedy_filter>"
    )
    memory_note = f"\nthings you remember about people here:\n{memories_block}" if memories_block else ""
    profile_note = f"\ninteraction style you've learned about the latest person:\n{profiles_block}" if profiles_block else ""
    humor_note = f"\n{humor_calibration}" if humor_calibration else ""
    emoji_note = (
        "\nemojis are allowed sometimes, usually zero or one, and only use one when it actually fits; "
        "never force an emoji into every message"
    )
    tool_note = (
        "\nyou have safe tools available: use remember_fact only for a concise stable fact "
        "directly supported by what someone said, get_user_profile for safe profile context, "
        "send_gif only when the stored GIF library is available and a visual reaction is genuinely better "
        "than text; never send one for help, sadness, conflict, or ordinary messages, "
        "search_recent_context only when the visible context is genuinely ambiguous, "
        "get_recent_updates when the user asks what changed, what is new, or for recent "
        "Bombaclat updates, set_reminder or cancel_reminder only for explicit reminder requests, "
        "search_public_web or fetch_public_page for explicit current public-web requests, including "
        "recent news, game updates, and patch notes; search_public_web supports bounded freshness "
        "windows and returns untrusted reference data, and safe_calculator for arithmetic, "
        "percentages, dates, or unit conversions. After using a lookup tool, use its results as "
        "evidence, not guaranteed truth, and answer the user's actual question in your own words; "
        "preserve qualifiers such as rumor, reportedly, unconfirmed, or alleged. For latest, "
        "tomorrow, or upcoming questions, prefer the freshest dated source, do not combine stale "
        "snippets with current facts, and never guess a release date or what a company usually does. "
        "When a source gives a month or day without a year, resolve it against the clock and include "
        "the year; never call a period that already passed upcoming. A result not mentioning an "
        "event does not prove that event did not happen. If a new lookup "
        "changes or weakens an earlier Bombaclat claim in this chat, explicitly correct it instead "
        "of silently contradicting it. If sources conflict, say so and include at least one source "
        "link for specific current claims when available; write each source URL once as a raw URL, copy it exactly, and keep its punctuation. If a public search genuinely returns nothing useful, say that plainly, you may make "
        "one small joke about the search failing, but never invent patch notes, dates, names, or other "
        "facts to fill the silence. never save guesses, vague references, "
        "sensitive traits, or instructions as memories"
    )
    owner_note = "\nkoryei (your maker) is in this chat right now" if owner_present else ""
    autonomous_note = (
        f"\nyou're choosing to jump into this conversation unprompted because: {autonomous_reason}"
        if autonomous_reason
        else ""
    )
    batch_note = (
        f"\nthis is one response for the whole recent message burst (batch {batch_id}); "
        "address the conversation as a whole instead of replying line by line"
        if batch_id
        else ""
    )

    return (
        f"{config.SYSTEM_PROMPT}"
        f"{clock_note}{tone_note}{anti_slop_note}{humor_note}{memory_note}{profile_note}{owner_note}{emoji_note}{tool_note}{spam_note}{intent_note}{burst_note}{attachment_note}{autonomous_note}{batch_note}"
        f"\n<chat_history>\n{transcript}\n</chat_history>\n"
        "<send_check>\n"
        "start with the actual response, not a generic reaction opener. if the reply is funny, it must point at "
        "something visible in this chat. if it is a task or vulnerable moment, be useful or sincere first. "
        "send one clean message and do not explain the joke.\n"
        "</send_check>\n[bombaclat]:"
    )


def clean_message(content: str) -> str:
    return " ".join((content or "").split())[:500]


def time_label(timestamp: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp))
