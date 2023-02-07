#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess

# Logging
from pathlib import Path
from typing import Any, Optional

import click
import typer

# Logging
import tsmu.log

logger = tsmu.log.SetupInteractiveScriptLogging()

## chdir context manager (in Python 3.11?)

try:
    from contextlib import chdir as contextlib_chdir
except ImportError:
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

import shutil

import transmissionrpc


def ConnectToTransmission() -> transmissionrpc.Client:
    """Connect to transmission using current user's settings."""
    settings_file_path = (
        Path(click.get_app_dir("transmission-daemon"), "settings.json").expanduser().resolve()
    )
    settings = json.load(open(settings_file_path))

    host, port, username, password = "localhost", settings["rpc-port"], None, None
    tc = transmissionrpc.Client(host, port, username, password)
    return tc


TorrentInformation = dict[str, Any]


def DumpTorrentMetadata(
    torrent_info: TorrentInformation, output_path: Path, use_name: bool = False
) -> Path:
    assert "torrentFile" in torrent_info
    ti = torrent_info.copy()

    for unnecessary_attr in {"id", "downloadDir", "percentDone"}:
        if "id" in ti:
            del ti[unnecessary_attr]

    name = torrent_info["name"]
    transmission_torrent_file = ti["torrentFile"]
    hash = ti["hash"]

    # TODO: make sure name is filesystem-safe
    if use_name:
        filename_base = name
    else:
        filename_base = hash

    dest_torrent_filename = filename_base + ".torrent"
    metadata_filename = filename_base + ".json"

    # Fix filename
    ti["torrentFile"] = dest_torrent_filename

    # TODO: permissions may be too restrictive
    dest_torrent_full_path = Path(
        shutil.copy2(transmission_torrent_file, output_path / dest_torrent_filename)
    )

    with Path(output_path / metadata_filename).open("a") as fp:
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
            # "id": t.id,
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
        f"Readd name={torrent_info['name']}\n      hash={torrent_info['hash']}\n      from={torrent_info.get('downloadDir')}\n        to={readd_path}"
    )

    tc.remove_torrent(torrent_info["hash"])
    tc.add_torrent(str(backup_up_torrent_file), download_dir=readd_path)


def FindXXH(path: Path) -> Optional[Path]:
    candidate_xxh = {
        path.parent / (path.name + ".auto.xxh"),
        path.parent / (path.name + ".xxh"),
    }
    xxh = None
    for c in candidate_xxh:
        if c.exists():
            xxh = c
            return xxh
    return False


def main(
    root_path: Path = Path("."), transmission: bool = True, candidate_path: Path | None = None
):
    root_path = root_path.absolute().resolve()
    logger.info(f"Scanning path={root_path.absolute()}")
    if candidate_path:
        candidate_path = candidate_path.absolute().resolve()
        logger.info(f"Also checking path {candidate_path} for dupe candidates")
        assert candidate_path.exists()
    if transmission:
        tc = ConnectToTransmission()
        torrentsByName = CacheTransmissionTorrents(tc)
    else:
        tc, torrentsByName = None, dict()

    for de in os.scandir(root_path):
        if not de.is_dir():
            continue

        dupe = Path(de.path).absolute().resolve()

        candidate_paths = [
            Path("../../../") / de.name,
            Path("../../") / de.name,
            Path("../") / de.name,
        ]
        if candidate_path:
            candidate_paths.insert(0, candidate_path / de.name)

        non_dupe = None
        for c in candidate_paths:
            c = c.absolute().resolve()
            # logger.info(f"Checking {str(c)}")
            if c.exists():
                non_dupe = c
                break
        if not non_dupe:
            logger.warning(f'Unable to find candidate dupe for "{de.name}"')
            continue

        non_dupe = non_dupe.absolute().resolve()
        # logger.info(f"Found {dupe}, candidate dupe at {non_dupe}")

        # check dupe w/ non_dupe xxh
        non_dupe_xxh = FindXXH(non_dupe)
        if not non_dupe_xxh:
            logger.warning(f'Unable to find non-dupe checksums for "{de.name}"')
            continue
        dupe_xxh = FindXXH(dupe)
        if not dupe_xxh:
            logger.warning(f'Unable to find dupe checksums for "{de.name}"')
            continue

        def CheckXXHAgainstDirectory(xxh: Path, cwd: Path, name: str) -> bool:
            if not cwd.is_dir():
                return False
            if not xxh.is_file():
                return False

            with contextlib_chdir(cwd):
                cmd = ["ionice", "-c", "3", "xxhsum", "-c", str(xxh)]
                cp = subprocess.run(cmd, capture_output=True, universal_newlines=True)
                if cp.returncode == 0:
                    return True
                else:
                    stdout = cp.stdout
                    logger.error(f"{name} does not match")
                    bad_lines = []
                    missing_files = re.findall(
                        "Could not open or read '(.*?)': No such file or directory", stdout
                    )
                    for mf in missing_files:
                        logger.info(f"We could copy {xxh.parent / mf} to {cwd / name} to fix this")

                    # We fixed missing files… so let's recompute checksums and try again
                    if len(missing_files) > 0:
                        logger.info(f"Found missing files: {missing_files=}")

                        rsync_src = str(xxh.parent / name) + "/"
                        rsync_dst = str(cwd / name) + "/"
                        assert Path(rsync_src).exists()
                        assert Path(rsync_dst).exists()
                        rsync_src, rsync_dst = shlex.quote(rsync_src), shlex.quote(rsync_dst)
                        rsync_cmd = f"rsync -aPv -c --ignore-existing {rsync_src} {rsync_dst}"
                        subprocess.run(rsync_cmd, shell=True)
                        release_name = shlex.quote(dupe.name)
                        xxhsum_recompute_cmd = f"(cd {cwd} && ionice -c 3 find {release_name} -type f -exec xxhsum {{}} \; > {cwd}/{release_name}.auto.xxh) &"
                        subprocess.run(xxhsum_recompute_cmd, shell=True)
                        logger.info(f"Rechecking {name=}")
                        return CheckXXHAgainstDirectory(xxh, cwd, name)
                    for line in stdout.splitlines():
                        # Just handled this above
                        if "No such file or directory" in line:
                            continue
                        if ": OK" not in line:
                            bad_lines.append(line.strip())
                    for line in bad_lines:
                        logger.error(line)
                    return False

        #        with contextlib_chdir(dupe.parent):
        #            cmd = ['ionice', '-c', '3', 'xxhsum', '-c', str(non_dupe_xxh)]
        #            cp = subprocess.run(cmd, capture_output=True, universal_newlines=True)
        #            if cp.returncode == 0:
        #                ok = True
        #            else:
        #                stdout = cp.stdout
        #                logger.error(f"{dupe} does not match")
        #                bad_lines = []
        #                missing_files = re.findall("Could not open or read '(.*?)': No such file or directory", stdout)
        #                for mf in missing_files:
        #                    logger.info(f"We could copy {non_dupe_xxh.parent / mf} to {dupe} to fix this")
        #                for line in stdout.splitlines():
        #                    if ': OK' not in line:
        #                        bad_lines.append(line.strip())
        #                for line in bad_lines:
        #                    logger.error(line)
        #                continue
        #
        #        with contextlib_chdir(non_dupe.parent):
        #            cmd = ['xxhsum', '-c', str(dupe_xxh)]
        #            cp = subprocess.run(cmd, capture_output=True, universal_newlines=True)
        #            if cp.returncode == 0:
        #                ok = True
        #            else:
        #                stdout = cp.stdout
        #                logger.error(f"{dupe} does not match")
        #                bad_lines = []
        #                missing_files = re.findall("Could not open or read '(.*?)': No such file or directory", stdout)
        #                for mf in missing_files:
        #                    logger.info(f"We could copy {dupe_xxh.parent / mf} to {non_dupe} to fix this")
        #                for line in stdout.splitlines():
        #                    if ': OK' not in line:
        #                        bad_lines.append(line.strip())
        #                for line in bad_lines:
        #                    logger.error(line)
        #                continue

        # if ok:
        if CheckXXHAgainstDirectory(
            non_dupe_xxh, dupe.parent, dupe.name
        ) and CheckXXHAgainstDirectory(dupe_xxh, non_dupe.parent, dupe.name):
            logger.info(f"Safe to remove {dupe}")

            if transmission:
                # this is wrong, we don't want by name, we want by name and downloadDir
                ti: TorrentInformation | None = None
                try:
                    ti = torrentsByName[(dupe.name, str(dupe.parent))]
                except KeyError as e:
                    logger.warning(f"Unable to find dupe torrent in client: {e}. Removing anyway")
                if ti:
                    ReAddTorrent(tc, ti, non_dupe.parent)

            # logger.info(f"Removing {dupe} and {dupe_xxh}")
            rm_target = "%s{,%s}" % (dupe.name, dupe_xxh.name.replace(dupe.name, ""))
            logger.info(f"Removing {dupe.parent}/{rm_target}")
            shutil.rmtree(dupe)
            dupe_xxh.unlink()
        else:
            pass
            # logger.info(f"Not the same: {str(dupe_xxh)} and {str(non_dupe_xxh)}")

    return


def run():
    typer.run(main)


if __name__ == "__main__":
    run()
