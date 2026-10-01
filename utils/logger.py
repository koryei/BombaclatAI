import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

import config
from rich.console import Console
from rich.logging import RichHandler


def configure_logging(console: Console | None = None) -> None:
    log_path = Path(config.LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the bot's own structured lifecycle messages visible without
    # flooding the dashboard with one HTTP line and one known SDK advisory per
    # Gemini request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s - %(message)s")
    )

    handlers: list[logging.Handler] = [file_handler]
    if console is not None:
        # RichHandler coordinates with an active `rich.live.Live` display on
        # the same console, so log lines print cleanly above the live
        # dashboard instead of corrupting it.
        rich_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            markup=False,
            rich_tracebacks=True,
            log_time_format="[%X]",
        )
        handlers.append(rich_handler)
    else:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(message)s",
        handlers=handlers,
        force=True,
    )
