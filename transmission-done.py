#!/usr/bin/env python3
"""
Setup this script w/:

    transmission-remote --torrent-done-script ~/transmission-done.py
"""
import datetime
import functools
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import FrozenSet

import click

transmission_env_variables: FrozenSet[str] = frozenset(
    {
        'TR_APP_VERSION',
        'TR_TIME_LOCALTIME',
        'TR_TORRENT_DIR',
        'TR_TORRENT_HASH',
        'TR_TORRENT_ID',
        'TR_TORRENT_NAME',
    }
)

output_dict = {e: os.getenv(e) for e in transmission_env_variables}
if tr_torrent_id := output_dict.get('TR_TORRENT_ID'):
    output_dict['TR_TORRENT_ID'] = int(tr_torrent_id)
# if 'TR_TORRENT_ID' in output_dict and output_dict['TR_TORRENT_ID']:
#    output_dict['TR_TORRENT_ID'] = int(output_dict['TR_TORRENT_ID'])


@functools.cache
def DetermineTransmissionPort() -> int:
    settings_file_path = (
        Path(click.get_app_dir("transmission-daemon"), "settings.json").expanduser().resolve()
    )
    settings = json.load(settings_file_path.open())
    port = int(settings['rpc-port'])
    return port


if current_download_path := Path(output_dict.get('TR_TORRENT_DIR')):
    # if 'TR_TORRENT_DIR' in output_dict and output_dict['TR_TORRENT_DIR']:
    # current_download_path = Path(output_dict['TR_TORRENT_DIR'])

    target_name = output_dict['TR_TORRENT_NAME']
    target_name = shlex.quote(target_name)

    should_move = True

    if (
        "02-baked" in current_download_path.parts
        or '.done' in current_download_path.name
        or 'dupes' in current_download_path.parts
    ):
        should_move = False

    if should_move:
        # New "hot" format, from 01-hot -> $FOLDER_NAME
        if current_download_path.name.endswith("01-hot") or current_download_path.name.endswith(
            "_hot"
        ):
            date_tag = datetime.datetime.now().strftime('%Y%m.%U')
            moved_download_path = current_download_path.parent / "02-baked" / date_tag
        # $FOLDER_NAME.incomplete -> $FOLDER_NAME.done
        elif '.incomplete' in current_download_path.name:
            moved_download_path = current_download_path.parent / str(
                current_download_path.name
            ).replace('.incomplete', '.done')
        # $FOLDER_NAME -> $FOLDER_NAME.done
        else:
            moved_download_path = current_download_path.parent / (
                str(current_download_path.name) + ".done"
            )

        target_dir = moved_download_path / output_dict['TR_TORRENT_NAME']

        # If we already have downloaded a torrent of this name, put into "dupes" folder
        while target_dir.exists():
            moved_download_path = moved_download_path / "dupes"
            target_dir = moved_download_path / output_dict['TR_TORRENT_NAME']

        # output_dict['MovedDirectory'] = str(moved_download_path)
        moved_download_path.mkdir(parents=True, exist_ok=True)

        move_torrent_cmd = [
            'transmission-remote',
            str(DetermineTransmissionPort()),
            '-t',
            str(output_dict['TR_TORRENT_ID']),
            '--move',
            str(moved_download_path),
        ]
        subprocess.run(move_torrent_cmd)
        time.sleep(15)

    verify_cmd = [
        'transmission-remote',
        str(DetermineTransmissionPort()),
        '-t',
        str(output_dict['TR_TORRENT_ID']),
        '--verify',
    ]
    subprocess.run(verify_cmd)

    if target_dir.is_dir():
        xxh_cmd = f"(cd {moved_download_path} && ionice -c 3 find {target_name} -type f -exec xxhsum {{}} \; > {moved_download_path}/{target_name}.auto.xxh) &"
    else:
        xxh_cmd = f"(cd {moved_download_path} && ionice -c 3 xxhsum {target_name} > {target_name}.auto.xxh) &"
    output_dict['xxh'] = xxh_cmd

    subprocess.run(xxh_cmd, shell=True)

    # output_dict['MoveTorrent'] = ' '.join(move_torrent_cmd)


with Path("~/transmission-done.log.json").expanduser().open('a') as fp:
    fp.write(json.dumps(output_dict))
    fp.write("\n")
