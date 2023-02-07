#!/usr/bin/env python3

import json
import time
from pathlib import Path
from typing import Any, Callable, Generator

import click
import transmissionrpc

TransmissionId = str


def ParseRanges(s: str) -> Generator[TransmissionId, None, None]:
    """
    >>> list(ParseRanges("123"))
    ['123']
    >>> list(ParseRanges("123,347"))
    ['123', '347']
    >>> list(ParseRanges("123-124"))
    ['123', '124']
    >>> list(ParseRanges("123-124,347"))
    ['123', '124', '347']
    >>> list(ParseRanges("123-124, 347"))
    ['123', '124', '347']
    """
    for comma_range in s.split(","):
        comma_range = comma_range.strip()
        if "-" not in comma_range:
            # Could be a infohash, or transmission torrent ID
            yield comma_range
            continue

        dash_range = comma_range.split("-")
        assert len(dash_range) == 2
        r1, r2 = int(dash_range[0]), int(dash_range[1]) + 1
        for i in range(r1, r2):
            yield str(i)


def ConnectToTransmission() -> transmissionrpc.Client:
    """Connect to transmission using current user's settings."""
    settings_file_path = (
        Path(click.get_app_dir("transmission-daemon"), "settings.json").expanduser().resolve()
    )
    settings = json.load(open(settings_file_path))

    host, port, username, password = "localhost", settings["rpc-port"], None, None
    tc = transmissionrpc.Client(host, port, username, password)
    tc.timeout = 90  # Increase timeout to 90s
    return tc


def CheckIfDownloadDirIsCorrect(
    tid: TransmissionId, download_dir: Path, tc: transmissionrpc.Client | None = None
) -> bool:
    tc = ConnectToTransmission() if not tc else tc
    torrent = tc.get_torrent(tid)
    if torrent.downloadDir != download_dir:
        return False
    return True


def IsInWarmDirectory(download_dir: Path) -> bool:
    """Are we in a warm or "done" directory, i.e. somewhere from where we are not moving?"""
    if (
        "02-baked" in download_dir.parts
        or "02-warm" in download_dir.parts
        or ".done" in download_dir.name
        or "dupes" in download_dir.parts
    ):
        return True
    return False


def VerifyTorrent(
    tid: TransmissionId,
    tc: transmissionrpc.Client | None = None,
    statusCb: Callable[str, Any] = lambda x: x,
) -> bool:
    tc = ConnectToTransmission() if not tc else tc
    torrent = tc.get_torrent(tid)
    statusCb(f'Verifying name="{torrent.name}"\n          hash="{torrent.hashString}"')

    # if we haven't started verifying, don't try to start again
    if torrent.status != "check pending":
        tc.verify_torrent(tid)
    while True:
        torrent = tc.get_torrent(tid)
        if torrent.status in ("checking", "check pending"):
            statusCb(
                f'Waiting to check, or check in progress. status="{torrent.status}" progress={torrent.recheckProgress}'
            )
            time.sleep(2)
            continue

        if torrent.error == 3:
            statusCb(
                f'Torrent name="{torrent.name}" hash="{torrent.hashString}" had local error={torrent.errorString}'
            )
            return False
        if torrent.percentDone == 1 and torrent.haveValid and not torrent.haveUnchecked:
            statusCb(f'Successfully verified name="{torrent.name}" hash="{torrent.hashString}"')
            return True

        statusCb(
            f'Failed to verify name="{torrent.name}" hash="{torrent.hashString}", progress at {torrent.percentDone}'
        )
        return False
