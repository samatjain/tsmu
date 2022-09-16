#!/usr/bin/env python3
"""
A script that moves a torrent completed in transmission-daemon to an appropriate
directory, and creates a xxhsum checksum file alongside it.

Setup this script w/:

    transmission-remote --torrent-done-script $(which transmission-done-dramatiq)
"""

import os
from typing import FrozenSet

from pathlib import Path
import json

from tsmu.workers import TransmissionVerify

transmission_env_variables: FrozenSet[str] = frozenset(
    {
        "TR_APP_VERSION",
        "TR_TIME_LOCALTIME",
        "TR_TORRENT_DIR",
        "TR_TORRENT_HASH",
        "TR_TORRENT_ID",
        "TR_TORRENT_NAME",
    }
)

output_dict = {e: os.getenv(e) for e in transmission_env_variables}
if tr_torrent_id := output_dict.get("TR_TORRENT_ID"):
    output_dict["TR_TORRENT_ID"] = int(tr_torrent_id)


def main():
    with Path("~/transmission-done-testing.log.json").expanduser().open("a") as fp:
        fp.write(json.dumps(output_dict))
        fp.write("\n")
    # hash is specifically used so we're safe across transmission-daemon
    # restarts
    TransmissionVerify.send(
        output_dict["TR_TORRENT_HASH"],
        output_dict["TR_TORRENT_NAME"],
        output_dict["TR_TORRENT_DIR"],
    )


if __name__ == "__main__":
    main()
