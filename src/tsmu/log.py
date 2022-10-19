import logging
import os
from datetime import datetime
from logging import LogRecord
from pathlib import Path
from typing import Any, Final, Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.traceback import Traceback, install

# traceback handling
install(show_locals=True)


class MyRichHandler(RichHandler):
    """MyRichHandler."""

    emoji: bool = True
    emoji_by_levels: Final[dict[str, str]] = {
        "INFO": "🔈",
        "WARNING": "🔶",
        "ERROR": "🛑",
        "FATAL": "💀",
    }

    def __init__(self, *args, emoji: bool = True, **kwargs):
        error_console = Console(stderr=True)
        self.emoji = emoji
        super().__init__(*args, console=error_console, **kwargs)

    def render(
        self,
        *,
        record: LogRecord,
        traceback: Optional[Traceback],
        message_renderable: "ConsoleRenderable",
    ):
        """Render log for display.
        Args:
            record (LogRecord): logging Record.
            traceback (Optional[Traceback]): Traceback instance or None for no Traceback.
            message_renderable (ConsoleRenderable): Renderable (typically Text) containing log message contents.
        Returns:
            ConsoleRenderable: Renderable to display log.
        """
        path = Path(record.pathname).name + ":" + record.funcName
        level = self.get_level_text(record)
        time_format = None if self.formatter is None else self.formatter.datefmt
        log_time = datetime.fromtimestamp(record.created)

        # Emoji for log ideas:
        # • https://gist.github.com/tburry/d8a4abc16d78d3a604ad63ea00eaf1f6
        # • https://github.com/paulospx/loglevel2emoji
        if self.emoji:
            emoji_by_levels = self.emoji_by_levels
            level_str = level.plain.strip()
            level = emoji_by_levels.get(level_str) if level_str in emoji_by_levels else level
        log_renderable = self._log_render(
            self.console,
            [message_renderable] if not traceback else [message_renderable, traceback],
            log_time=log_time,
            time_format=time_format,
            level=level,
            path=path,
            line_no=record.lineno,
            link_path=record.pathname if self.enable_link_path else None,
        )
        return log_renderable


# rich_handler.setFormatter(logging.Formatter('%(name)s - %(message)s', datefmt="[%X]"))


class MyRichComponentHandler(MyRichHandler):
    """MyRichComponentHandler."""

    def get_level_text(self, record: LogRecord) -> Text:
        level_text = super().get_level_text(record)
        component_name = record.name
        level_text = level_text + Text(component_name, style="cyan") + Text(" -")
        # Show thread_name
        #        level_text = (
        #            level_text
        #            + Text(component_name, style="cyan")
        #            + Text("[" + record.threadName + "]")
        #            + Text(" -")
        #        )
        return level_text


DEFAULT_SILENCED_LOGGERS = frozenset({"paramiko.transport", "paramiko.transport.sftp"})


def SetupInteractiveScriptLogging(
    show_component: bool = False,
    show_path: bool = False,
    emoji: bool = True,
    on_root_logger: bool = True,
    silence_loggers: set[str] | frozenset[str] = DEFAULT_SILENCED_LOGGERS,
) -> Any:

    # logger = logging.getLogger(get_script_name(__file__))
    logger = logging.getLogger(os.path.basename(__file__))

    # options on markup

    if show_component:
        rich_handler = MyRichComponentHandler(
            rich_tracebacks=True, show_path=show_path, markup=True, emoji=emoji
        )
    else:
        rich_handler = MyRichHandler(
            rich_tracebacks=True, show_path=show_path, markup=True, emoji=emoji
        )
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))

    if on_root_logger:
        root_logger = logging.getLogger("")
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(rich_handler)

        for sln in silence_loggers:
            sl = logging.getLogger(sln)
            sl.setLevel(logging.WARNING)
    else:
        logger.setLevel(logging.INFO)
        logger.addHandler(rich_handler)

    return logger


def get_script_name(fn: str) -> str:
    """Given a script name, get the name of the script.

    Almost always, you are passing a script's __file__ to this.

        logger = logging.getLogger(get_script_name(__file__))

    E.g. if you have an interactive script like rotateKey_fetch.py, this
    function will return rotateKey_fetch so you've a nice name for logging
    purposes.
    """
    try:
        script_name = os.path.splitext(os.path.basename(fn))[0]
    except:
        script_name = fn
    return script_name
