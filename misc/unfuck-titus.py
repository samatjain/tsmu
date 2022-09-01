#!/usr/bin/env python3
import os
from pathlib import Path
import logging
import sys

from typing import Any, Optional

import json
import click
import typer

import subprocess
from shlex import quote

# Logging
from datetime import datetime
from rich.logging import RichHandler
from logging import LogRecord
from rich.text import Text
from rich.traceback import Traceback

from rich.traceback import install

install(show_locals=True)

from rich.console import Console


class MyRichHandler(RichHandler):
    def __init__(self, *args, **kwargs):
        error_console = Console(stderr=True)
        super().__init__(*args, console=error_console, **kwargs)

    #    def get_level_text(self, record: LogRecord) -> Text:
    #        level_text = super().get_level_text(record)
    #        component_name = record.name
    #        level_text = level_text + Text(component_name, style="cyan") + Text(" -")
    #        # Show thread_name
    #        #        level_text = (
    #        #            level_text
    #        #            + Text(component_name, style="cyan")
    #        #            + Text("[" + record.threadName + "]")
    #        #            + Text(" -")
    #        #        )
    #        return level_text

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


rich_handler = MyRichHandler(rich_tracebacks=True, show_path=False, markup=True)
rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
# rich_handler.setFormatter(logging.Formatter('%(name)s - %(message)s', datefmt="[%X]"))

# import os
# logger = logging.getLogger(os.path.basename(__file__))
# logger.setLevel(logging.INFO)
# logger.addHandler(rich_handler)
# Attach to root logger for debugging from other components
logger = logging.getLogger(os.path.basename(__file__))
root_logger = logging.getLogger("")
root_logger.setLevel(logging.INFO)
root_logger.addHandler(rich_handler)
silence_loggers = frozenset({"paramiko.transport", "paramiko.transport.sftp"})
for sln in silence_loggers:
    sl = logging.getLogger(sln)
    sl.setLevel(logging.WARNING)
# End logging

## chdir context manager (in Python 3.11?)

try:
    from contextlib import chdir as contextlib_chdir
except ImportError:
    pass
    import os
    from contextlib import AbstractContextManager

    class contextlib_chdir(AbstractContextManager):
        """Non thread-safe context manager to change the current working directory."""

        def __init__(self, path):
            self.path = path
            self._old_cwd = []

        def __enter__(self):
            self._old_cwd.append(os.getcwd())
            os.chdir(self.path)

        def __exit__(self, *excinfo):
            os.chdir(self._old_cwd.pop())


## end chdir context manager

## from tsmu.py

import transmissionrpc
import shutil


def ConnectToTransmission() -> transmissionrpc.Client:
    """Connect to transmission using current user's settings."""
    settings_file_path = (
        Path(click.get_app_dir("transmission-daemon"), "settings.json").expanduser().resolve()
    )
    settings = json.load(open(settings_file_path))

    host, port, username, password = 'localhost', settings['rpc-port'], None, None
    tc = transmissionrpc.Client(host, port, username, password, timeout=120)
    return tc


TorrentInformation = dict[str, Any]


def DumpTorrentMetadata(
    torrent_info: TorrentInformation, output_path: Path, use_name: bool = False
) -> Path:
    assert 'torrentFile' in torrent_info
    ti = torrent_info.copy()

    for unnecessary_attr in {'id', 'downloadDir', 'percentDone'}:
        del ti[unnecessary_attr]

    name = torrent_info['name']
    transmission_torrent_file = ti['torrentFile']
    hash = ti['hash']

    # TODO: make sure name is filesystem-safe
    if use_name:
        filename_base = name
    else:
        filename_base = hash

    dest_torrent_filename = filename_base + '.torrent'
    metadata_filename = filename_base + '.json'

    # Fix filename
    ti['torrentFile'] = dest_torrent_filename

    # TODO: permissions may be too restrictive
    dest_torrent_full_path = Path(
        shutil.copy2(transmission_torrent_file, output_path / dest_torrent_filename)
    )

    with Path(output_path / metadata_filename).open('a') as fp:
        fp.write(json.dumps(ti))

    return dest_torrent_full_path


# end from tsmu.py
import functools


@functools.cache
def CacheTransmissionTorrents(
    tc: transmissionrpc.Client,
) -> dict[tuple[str, str], TorrentInformation]:
    logger.info("Getting torrent information")
    out = dict()
    for t in tc.get_torrents():
        out[(t.name, t.downloadDir)] = {
            "id": t.id,
            "hash": t.hashString,
            "name": t.name,
            "downloadDir": t.downloadDir,
            "magnetLink": t.magnetLink,
            "percentDone": t.percentDone,
            "torrentFile": t.torrentFile,
        }
    logger.info(f"Done getting torrent information, count={len(out)}")
    return out


def ReAddTorrent(tc: transmissionrpc.Client, torrent_info: TorrentInformation, readd_path: Path):
    """Readd a torrent given by torrent_info to a path given by readd_path."""
    READD_FOLDER = Path("~/readded-torrents/").expanduser()
    READD_FOLDER.mkdir(exist_ok=True)

    backup_up_torrent_file = DumpTorrentMetadata(torrent_info, READD_FOLDER)

    logger.info(
        f"Readd name={torrent_info['name']} hash={torrent_info['hash']} from={torrent_info.get('downloadDir')} to new_path={readd_path}"
    )

    tc.remove_torrent(torrent_info['hash'])
    tc.add_torrent(str(backup_up_torrent_file), download_dir=readd_path)


def main(root_path: Path = Path(".")):
    tc = ConnectToTransmission()
    torrentsByName = CacheTransmissionTorrents(tc)

    locationsByTorrentName = dict()

    MOVE_PATH = Path("/home/xjjk/Downloads/torrents/Automatic.Music/202203.12.done/eleven.done")

    for name, location in torrentsByName.keys():
        if '202203.12.done' not in location:
            continue
        if 'incomplete' in location:
            continue
        if '202203.12.done/two' in location:
            continue
        if location == str(MOVE_PATH):
            continue

        locations = locationsByTorrentName.get(name, [])
        locations.append(location)
        locationsByTorrentName[name] = locations

    count, err_count = 0, 0
    for name, locations in locationsByTorrentName.items():
        if len(locations) == 1:
            l = locations[0]

            # Ignore not-done torrents for now
            pct_done = torrentsByName[(name, l)]["percentDone"]
            if pct_done != 1:
                logger.info(f"Skipping {name=}, as it's not done")
                continue

            if count > 3000:
                logger.info("Hit limit, fast-skipping")
                continue

            actual = Path(l) / name
            xxh = Path(l) / (name + ".auto.xxh")
            if not xxh.exists():
                logger.info(f"{xxh} doesn't exist")
                xxh = Path(l) / (name + ".xxh")
            if not actual.exists() or not xxh.exists():
                logger.error(f"Something wrong with {name}")
                err_count += 1
                continue

            ok = False
            with contextlib_chdir(actual.parent):
                cmd = ['ionice', '-c', '3', 'xxhsum', '-c', str(xxh)]
                cp = subprocess.run(cmd, capture_output=True, universal_newlines=True)
                if cp.returncode == 0:
                    ok = True
                else:
                    logger.error(f"{actual} does not match")
                    bad_lines = []
                    for line in cp.stdout.splitlines():
                        if ': OK' not in line:
                            bad_lines.append(line.strip())
                    for line in bad_lines:
                        logger.error(line)
                    logger.info(f"Remove {xxh} and creating again for {actual.name}")
                    # Remove bad file
                    xxh.unlink()
                    # Create again
                    cmd = f"Create-SHA1-for-directory.sh {quote(actual.name)}| rg xxhsum | sh"
                    cp = subprocess.run(
                        cmd, capture_output=True, shell=True, universal_newlines=True
                    )
                    continue
            if ok:
                logger.info(f"{name=} is safe to move")
                locations = locationsByTorrentName[name]
                assert len(locations) == 1
                ti = torrentsByName[(name, l)]
                hash = ti['hash']
                logger.info(f"Moving {name=} {hash=} from {l}")
                tc.move_torrent_data(hash, str(MOVE_PATH))
                shutil.move(xxh, str(MOVE_PATH))
                count += count
    logger.info(f"{count=} {err_count=}")

    return


if __name__ == '__main__':
    typer.run(main)
