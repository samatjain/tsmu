#!/usr/bin/env python3
import os
from pathlib import Path
import logging

from typing import Any, Optional

import json
import click
import shlex
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
    tc = transmissionrpc.Client(host, port, username, password)
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
    READD_FOLDER = Path("~/readded-torrents/").expanduser()
    READD_FOLDER.mkdir(exist_ok=True)

    backup_up_torrent_file = DumpTorrentMetadata(torrent_info, READD_FOLDER)

    logger.info(
        f"Readd name={torrent_info['name']} hash={torrent_info['hash']} from={torrent_info.get('downloadDir')} to new_path={readd_path}"
    )

    tc.remove_torrent(torrent_info['hash'])
    tc.add_torrent(str(backup_up_torrent_file), download_dir=readd_path)


def FindPath(name: str) -> Optional[Path]:
    import typing

    quoted_name = shlex.quote(name)

    class LocationOnHost(typing.NamedTuple):
        host: str
        location: Path

    locations = {
        LocationOnHost("fa.local", Path("/archive/torrents/revtt-games/")),
        LocationOnHost("fa.local", Path("/archive/torrents/Games.Scene/")),
        LocationOnHost("nu.local", Path("/home/xjjk/Mount/ds1817c/torrents/revtt-games/")),
        # LocationOnHost("fa.local", Path("/archive/torrents/Movies.Scene/")),
        # LocationOnHost("fa.local", Path("/archive/torrents/revtt-1080p/")),
        # LocationOnHost("fa.local", Path("/home/xjjk/Mount/rs2421a/revtt-1080p/")),
    }

    path_on_remote = None

    for location in locations:
        # Check for it on fa
        cmd = f"ssh {location.host} fdfind -td {quoted_name} {str(location.location)} | rg -iv sample | rg -v proof"
        cp = subprocess.run(cmd, capture_output=True, shell=True, universal_newlines=True)
        if cp.stdout is None or len(cp.stdout) == 0:
            continue

        stdout = cp.stdout.splitlines()

        if len(stdout) == 0:
            logger.error(f"Should not have gotten here for {name=}, {stdout=}")
            continue
        if len(stdout) > 1:
            logger.error(f"Too many found locations for {name=}, {stdout=}")
            continue

        import more_itertools

        path_on_remote = Path(more_itertools.first(stdout))
        logger.info(f"Found {name=} on {location.host}:{path_on_remote}")
        return location.host, path_on_remote

    return None


def main(root_path: Path = Path("."), dry_run: bool = True):
    tc = ConnectToTransmission()
    torrentsByName = CacheTransmissionTorrents(tc)

    for name, download_dir in torrentsByName.keys():
        hash = torrentsByName[(name, download_dir)]["hash"]
        pct_done = torrentsByName[(name, download_dir)]["percentDone"]

        # skip done torrents
        if pct_done == 1:
            continue

        path_on_remote = FindPath(name)
        path_local = Path(download_dir) / name

        if not path_on_remote:
            logger.info(f"Cannot find {name=}")
            continue

        host, path_on_remote = path_on_remote

        path_on_remote_str, path_on_local_str = (
            shlex.quote(str(path_on_remote)) + "/",
            shlex.quote(str(path_local)) + "/",
        )
        rsync_cmd = f"rs {host}:{path_on_remote_str} {path_on_local_str}"

        if not dry_run:
            tc.stop_torrent(hash)
            cp = subprocess.run(rsync_cmd, shell=True)

            tc.verify_torrent(hash)
            tc.start_torrent(hash)

        pass

    sys.exit(0)

    for de in os.scandir(root_path):
        if not de.is_dir():
            continue

        dupe = Path(de.path).absolute().resolve()

        non_dupe = Path("../") / de.name
        non_dupe = non_dupe.absolute().resolve()
        # logger.info(f"Found {dupe}, candidate dupe at {non_dupe}")

        # check dupe w/ non_dupe xxh
        non_dupe_xxh = non_dupe.parent / (non_dupe.name + ".auto.xxh")
        dupe_xxh = dupe.parent / (dupe.name + ".auto.xxh")

        ok = False

        with contextlib_chdir(dupe.parent):
            cmd = ['xxhsum', '-c', str(non_dupe_xxh)]
            cp = subprocess.run(cmd, capture_output=True, universal_newlines=True)
            if cp.returncode == 0:
                ok = True
            else:
                logger.error(f"{dupe} does not match")
                bad_lines = []
                for line in cp.stdout.splitlines():
                    if ': OK' not in line:
                        bad_lines.append(line.strip())
                for line in bad_lines:
                    logger.error(line)
                continue

        with contextlib_chdir(non_dupe.parent):
            cmd = ['xxhsum', '-c', str(dupe_xxh)]
            cp = subprocess.run(cmd, capture_output=True, universal_newlines=True)
            if cp.returncode == 0:
                ok = True
            else:
                logger.error(f"{dupe} does not match")
                bad_lines = []
                for line in cp.stdout.splitlines():
                    if ': OK' not in line:
                        bad_lines.append(line.strip())
                for line in bad_lines:
                    logger.error(line)
                continue

        if ok:
            logger.info(f"Safe to remove {dupe}")

            # this is wrong, we don't want by name, we want by name and downloadDir
            ti = torrentsByName[(dupe.name, str(dupe.parent))]
            ReAddTorrent(tc, ti, non_dupe.parent)

            logger.info(f"Removing {dupe} and {dupe_xxh}")
            shutil.rmtree(dupe)
            dupe_xxh.unlink()

    return


if __name__ == '__main__':
    typer.run(main)
