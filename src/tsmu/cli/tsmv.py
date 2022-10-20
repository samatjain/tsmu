#!/usr/bin/env python3

import sys
from pathlib import Path
from pprint import pprint  # NOQA

import click

# Logging
import tsmu.log
from tsmu.util import ConnectToTransmission, ParseRanges, TransmissionId, VerifyTorrent

logger = tsmu.log.SetupInteractiveScriptLogging()


@click.command()
@click.option("-t", "--torrent", "tid", help="transmission torrent id or infohash", required=True)
@click.option("-v", "--verbose", default=False, is_flag=True)
def cli(tid: str, verbose: bool = False):
    """Verify a torrent in transmission, waiting until verification is complete."""
    any_fail = False
    for r in ParseRanges(tid):
        if verbose:
            rv = VerifyTorrent(r, statusCb=logger.info)
            print()  # print explicit newline
        else:
            rv = VerifyTorrent(r)
        if not rv:
            any_fail = True
    sys.exit(0) if not any_fail else sys.exit(1)


if __name__ == "__main__":
    cli()
