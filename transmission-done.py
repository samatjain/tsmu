#!/usr/bin/env python3
"""
Setup this script w/:

    transmission-remote --torrent-done-script ~/transmission-done.py
"""
import os
import json
import time
import shlex
import subprocess

from pathlib import Path

import click


transmission_env_variables = [
    'TR_APP_VERSION',
    'TR_TIME_LOCALTIME',
    'TR_TORRENT_DIR',
    'TR_TORRENT_HASH',
    'TR_TORRENT_ID',
    'TR_TORRENT_NAME',
]

output_dict = {e: os.getenv(e) for e in transmission_env_variables}
if tr_torrent_id := output_dict.get('TR_TORRENT_ID'):
    output_dict['TR_TORRENT_ID'] = int(tr_torrent_id)
# if 'TR_TORRENT_ID' in output_dict and output_dict['TR_TORRENT_ID']:
#    output_dict['TR_TORRENT_ID'] = int(output_dict['TR_TORRENT_ID'])


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
    if 'done' not in current_download_path.name:
        if '.incomplete' in current_download_path.name:
            moved_download_path = current_download_path.parent / str(
                current_download_path.name
            ).replace('.incomplete', '.done')
        else:
            moved_download_path = current_download_path.parent / (
                str(current_download_path.name) + ".done"
            )
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
        time.sleep(10)

    verify_cmd = [
        'transmission-remote',
        str(DetermineTransmissionPort()),
        '-t',
        str(output_dict['TR_TORRENT_ID']),
        '--verify',
    ]
    subprocess.run(verify_cmd)

    target_name = output_dict['TR_TORRENT_NAME']
    target_name = shlex.quote(target_name)

    target_dir = moved_download_path / output_dict['TR_TORRENT_NAME']

    if target_dir.is_dir():
        xxh_cmd = f"(cd {moved_download_path} && find {target_name} -type f -exec xxhsum {{}} \; > {moved_download_path}/{target_name}.auto.xxh) &"
    else:
        xxh_cmd = f"(cd {moved_download_path} && xxhsum {target_name} > {target_name}.auto.xxh) &"
    output_dict['xxh'] = xxh_cmd

    subprocess.run(xxh_cmd, shell=True)

    # output_dict['MoveTorrent'] = ' '.join(move_torrent_cmd)


with Path("~/transmission-done.log.json").expanduser().open('a') as fp:
    fp.write(json.dumps(output_dict))
    fp.write("\n")
