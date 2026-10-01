"""Authoritative local and UTC clock context for prompts and current lookups."""

import datetime
import zoneinfo

import config


def current_datetime() -> datetime.datetime:
    """Return the current time in the configured user-facing timezone."""
    try:
        return datetime.datetime.now(zoneinfo.ZoneInfo(config.PRESENCE_TIMEZONE))
    except zoneinfo.ZoneInfoNotFoundError:
        return datetime.datetime.now().astimezone()


def current_time_context() -> str:
    """Return compact clock data that models can use instead of guessing dates."""
    local_now = current_datetime()
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    timezone_name = getattr(local_now.tzinfo, "key", config.PRESENCE_TIMEZONE)
    return (
        f"current date (authoritative): {local_now.date().isoformat()} ({local_now:%A}); "
        f"local time: {local_now:%H:%M:%S} {timezone_name}; "
        f"utc date: {utc_now.date().isoformat()}"
    )
