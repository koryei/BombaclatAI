"""Maps a situation (trigger + who's involved + time of day) to a tone.

The persona's voice rules (lowercase, short, casual) never change - what
shifts is the *energy* behind them. Comforting someone reads different from
hyping someone up, even in the same lowercase-only voice.
"""

from core.models import PersonalityState, UserVibe

TONE_DIRECTIVES: dict[str, str] = {
    "supportive": "be warm and reassuring, then stop; only joke if the person is already joking and the joke can use a specific detail without undercutting them",
    "hyper": "match their excitement, but make the energy about the actual detail they gave you; use one original exaggeration or sharp observation, not a pile of hype words",
    "help": "be useful and direct, answer the actual task first; ask one precise question only if needed, then add one dry aside only if the situation genuinely earned it",
    "dismissive": "keep it short and disengaged, do not escalate or take a side; a dry one-liner is okay only when it points at something specific in the chat",
    "curious": "react to the exact thing they said, then ask one light casual follow-up question; dont interrogate or fill space with generic enthusiasm",
    "chill": "stay relaxed and observant; let humor come from one immediate concrete detail, and say less if there is no real angle",
    "late_night": "you are half asleep; keep it short and mildly confused if someone randomly pings you, with one specific dry observation if available, but do not be genuinely rude",
    "neutral": "have a clear point of view and react to one concrete detail; be funny only when the context gives you an original angle, otherwise be concise and real",
}

_TRIGGER_TONE_MAP: dict[str, str] = {
    "sadness": "supportive",
    "celebration": "hyper",
    "help_request": "help",
    "escalation": "dismissive",
    "boredom": "chill",
    "banter": "hyper",
    "curiosity": "curious",
    "get_to_know": "curious",
}


def time_of_day_energy(hour: int, minute: int = 0) -> float:
    """Mirror the EDT school/life schedule: sleepy early, peak after school."""
    total_minutes = (hour % 24) * 60 + max(0, min(minute, 59))
    if total_minutes < 6 * 60:
        return 0.25
    if total_minutes < 7 * 60 + 50:
        return 0.4
    if total_minutes < 14 * 60 + 50:
        return 0.35
    if total_minutes < 16 * 60:
        return 0.5
    if total_minutes < 20 * 60:
        return 0.8
    if total_minutes < 23 * 60:
        return 0.9
    return 0.35


_PRESENCE_ACTIVITIES: dict[str, tuple[tuple[str, str], ...]] = {
    "sleepy": (
        ("listening", "late night music"),
        ("watching", "YouTube in bed"),
        ("playing", "Minecraft but barely awake"),
    ),
    "getting_ready": (
        ("watching", "getting ready for school"),
        ("listening", "getting ready for school"),
        ("watching", "getting ready for school"),
    ),
    "school": (
        ("watching", "at school"),
        ("listening", "in class"),
        ("watching", "trying to survive school"),
    ),
    "homework": (
        ("watching", "doing homework"),
        ("listening", "doing work"),
        ("watching", "locked in on homework"),
    ),
    "after_school": (
        ("playing", "outside"),
        ("listening", "good vibes"),
        ("watching", "out doing something"),
        ("playing", "touching grass"),
    ),
    "gaming": (
        ("playing", "Minecraft"),
        ("playing", "Fortnite"),
        ("playing", "GTA V"),
        ("playing", "Roblox"),
        ("streaming", "gaming chaos"),
    ),
    "late_night": (
        ("listening", "chill music"),
        ("watching", "YouTube at an unreasonable hour"),
        ("playing", "Minecraft quietly"),
    ),
}


def presence_profile(hour: int, minute: int = 0) -> tuple[str, str]:
    """Return the Discord status and activity mood for the EDT life schedule."""
    total_minutes = (hour % 24) * 60 + max(0, min(minute, 59))
    if total_minutes < 6 * 60:
        return "idle", "sleepy"
    if total_minutes < 7 * 60 + 50:
        return "idle", "getting_ready"
    if total_minutes < 14 * 60 + 50:
        return "dnd", "school"
    if total_minutes < 16 * 60:
        return "dnd", "homework"
    if total_minutes < 20 * 60:
        return "online", "after_school"
    if total_minutes < 23 * 60:
        return "online", "gaming"
    return "idle", "late_night"


def presence_activities(mood: str) -> tuple[tuple[str, str], ...]:
    """Return safe activity type/name pairs for a clock mood."""
    return _PRESENCE_ACTIVITIES.get(mood, _PRESENCE_ACTIVITIES["late_night"])


def determine_tone(
    trigger: str | None,
    user_vibe: UserVibe | None,
    hour: int,
    minute: int = 0,
) -> PersonalityState:
    tone = _TRIGGER_TONE_MAP.get(trigger or "", "neutral")
    if trigger is None and hour % 24 < 6:
        tone = "late_night"

    baseline_energy = time_of_day_energy(hour, minute)
    user_energy = user_vibe.energy if user_vibe else 0.5
    user_formality = user_vibe.formality if user_vibe else 0.4

    energy = max(0.0, min(1.0, user_energy * 0.6 + baseline_energy * 0.4))
    formality = max(0.0, min(1.0, user_formality))

    return PersonalityState(
        tone=tone,
        energy=energy,
        formality=formality,
        directive=TONE_DIRECTIVES.get(tone, TONE_DIRECTIVES["neutral"]),
    )


def describe_state(state: PersonalityState) -> str:
    return f"[current vibe: {state.tone}] {state.directive}"
