#!/usr/bin/env python3

import datetime
import os
import subprocess
from pathlib import Path

import dramatiq
import xdg.BaseDirectory
from dramatiq.broker import Broker
from dramatiq.brokers.redis import RedisBroker

from tsmu.util import (
    CheckIfDownloadDirIsCorrect,
    ConnectToTransmission,
    IsInWarmDirectory,
    TransmissionId,
    VerifyTorrent,
)

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

# REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_PASSWORD = None


def LoadConfiguration() -> None:
    global REDIS_PASSWORD
    config_path = Path(xdg.BaseDirectory.load_first_config("tsmu")) / "tsmu.toml"
    with config_path.open("rb") as fp:
        parsed_toml = tomllib.load(fp)

    REDIS_PASSWORD = parsed_toml["redis"]["password"]


LoadConfiguration()


def SetupBroker() -> Broker:
    # See https://github.com/redis/redis-py/blob/f704281cf4c1f735c06a13946fcea42fa939e3a5/redis/client.py#L855 for connecton string syntax
    rb = RedisBroker(url=f"unix://default:{REDIS_PASSWORD}@/run/redis/redis-server.sock?db=0")
    dramatiq.set_broker(rb)
    return rb


SetupBroker()


@dramatiq.actor(time_limit=(6 * 60 * 60 * 100))
def TransmissionVerify(tid: TransmissionId, name: str, download_dir: Path) -> None:
    """Verify, and wait, for a transmission torrent to finish verification."""
    download_dir = Path(download_dir) if not isinstance(download_dir, Path) else download_dir
    TransmissionVerify.logger.info(f"Verifying {name=} {tid=} download_dir={str(download_dir)}")

    if IsInWarmDirectory(download_dir):
        TransmissionVerify.logger.info(f"Skipping {name=} {tid=}, is in a target directory already")
        return

    if not tid:
        return
    ok = VerifyTorrent(tid)
    if ok:
        ComputeXxh.send(tid, name, str(download_dir))
        return

    TransmissionVerify.logger.error(f'Error checking {name=} {tid=}, leaving as-is')
    return


@dramatiq.actor(time_limit=(6 * 60 * 60 * 100))
def ComputeXxh(tid: TransmissionId, name: str, download_dir: Path) -> None:
    download_dir = Path(download_dir) if not isinstance(download_dir, Path) else download_dir

    target_dir = download_dir / name
    ComputeXxh.logger.info(f"Computing checksums for {name=} {target_dir=}")
    if not target_dir.exists():
        if not CheckIfDownloadDirIsCorrect(tid, download_dir):
            ComputeXxh.logger.error(f"Something wrong w/ {name=} {download_dir=}, leaving as-is")
        else:
            ComputeXxh.logger.error(f"{target_dir=} does not exist? Reverifying")
            TransmissionVerify.send(tid, name, download_dir)
        return

    if target_dir.is_dir():
        xxh_cmd = f"(cd {str(download_dir)} && ionice -c 3 find '{name}' -type f -exec xxhsum {{}} \; > {str(download_dir)}/'{name}'.auto.xxh)"
    else:
        xxh_cmd = f"(cd {str(download_dir)} && ionice -c 3 xxhsum '{name}' > '{name}'.auto.xxh)"

    subprocess.run(xxh_cmd, shell=True, check=True)

    MoveTorrent.send(tid, name, str(download_dir))


@dramatiq.actor
def MoveTorrent(tid: TransmissionId, name: str, download_dir: Path, is_dupe: bool = False) -> None:
    download_dir = Path(download_dir) if not isinstance(download_dir, Path) else download_dir
    should_move = not IsInWarmDirectory(download_dir)

    moved_download_path = download_dir

    warm_dir = download_dir.parent / "02-warm"
    use_warm_over_baked = warm_dir.exists()

    if should_move:
        # New "hot" format, from 01-hot -> $FOLDER_NAME
        date_tag = datetime.datetime.now().strftime("%Y%m.%U")
        if download_dir.name.endswith("01-hot"):
            moved_download_path = download_dir.parent / "02-baked" / date_tag
        elif download_dir.name.endswith("_hot"):
            moved_download_path = download_dir.parent / "_baked" / date_tag
        # $FOLDER_NAME.incomplete -> $FOLDER_NAME.done
        elif ".incomplete" in download_dir.name:
            moved_download_path = download_dir.parent / str(download_dir.name).replace(
                ".incomplete", ".done"
            )
        # $FOLDER_NAME -> $FOLDER_NAME.done
        else:
            moved_download_path = download_dir.parent / (str(download_dir.name) + ".done")

        assert should_move and (moved_download_path != download_dir)

        # If we already have downloaded a torrent of this name, put into "dupes" folder

        target_xxh = download_dir / (name + ".auto.xxh")
        moved_target_dir = moved_download_path / name
        while moved_target_dir.exists():
            moved_download_path = moved_download_path / "dupes"
            moved_target_dir = moved_download_path / name
        moved_target_xxh = moved_download_path / (name + ".auto.xxh")

        moved_download_path.mkdir(parents=True, exist_ok=True)

        tc = ConnectToTransmission()
        if os.stat(moved_download_path).st_dev == os.stat(download_dir).st_dev:
            MoveTorrent.logger.info(
                f'Moving {name=} from="{str(download_dir)}" to="{str(moved_download_path)}"'
            )
            tc.move_torrent_data(tid, str(moved_download_path))
            try:
                target_xxh.rename(moved_target_xxh)
            except FileNotFoundError:
                MoveTorrent.logger.error("Unable to to move %s, ignoring", str(target_xxh))
        else:
            MoveTorrent.logger.error("Move across devices not supported")

    return
