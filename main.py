import asyncio
import contextlib
import logging
import signal
import sys

from rich.live import Live

import config
from bot.client import DiscordSelfBotClient
from utils.console_ui import Dashboard, create_console, render_shutdown_panel
from utils.logger import configure_logging


async def _run_client(client) -> None:
    """Run Discord until it exits or systemd sends a graceful stop signal."""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def request_shutdown(signum: int) -> None:
        logger = logging.getLogger(__name__)
        logger.info("received %s; beginning graceful shutdown", signal.Signals(signum).name)
        stop_event.set()

    installed_signals: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown, signum)
            installed_signals.append(signum)
        except (NotImplementedError, RuntimeError):
            # Signal handlers are unavailable on some embedded/Windows loops;
            # Discord's normal close path still handles keyboard interrupts.
            pass

    client_task = asyncio.create_task(client.start(config.DISCORD_TOKEN), name="discord-client")
    stop_task = asyncio.create_task(stop_event.wait(), name="shutdown-watcher")
    try:
        done, _ = await asyncio.wait(
            {client_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done and not client_task.done():
            await client.close()
            try:
                await asyncio.wait_for(client_task, timeout=30)
            except asyncio.TimeoutError:
                logging.getLogger(__name__).error("Discord client did not stop within 30 seconds")
                client_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client_task
        else:
            await client_task
    finally:
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task
        for signum in installed_signals:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(signum)
        if not client.is_closed():
            await client.close()


def main() -> None:
    show_dashboard = config.DASHBOARD_ENABLED and sys.stdout.isatty()
    console = create_console() if show_dashboard else None
    configure_logging(console)

    startup_errors = config.validate_runtime_config()
    if startup_errors:
        logging.getLogger(__name__).error("invalid configuration: %s", "; ".join(startup_errors))
        raise SystemExit(78)

    if not config.OPENROUTER_API_KEY:
        logging.getLogger(__name__).warning(
            "OPENROUTER_API_KEY is missing; vision and text fallback paths are unavailable"
        )
    if config.SERPER_ENABLED and not config.SERPER_API_KEY:
        logging.getLogger(__name__).warning(
            "SERPER_ENABLED is true but SERPER_API_KEY is missing; current web search is unavailable"
        )
    logging.getLogger(__name__).warning(
        "this deployment uses a user-account self-bot; Discord's supported production path is a dedicated bot account"
    )

    client = DiscordSelfBotClient(console)

    try:
        if show_dashboard:
            dashboard = Dashboard(client, client.brain)
            with Live(dashboard, console=console, refresh_per_second=4, screen=False):
                asyncio.run(_run_client(client))
        else:
            asyncio.run(_run_client(client))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).exception("Discord client stopped unexpectedly")
        raise
    finally:
        if console is not None:
            console.print(render_shutdown_panel())


if __name__ == "__main__":
    main()
