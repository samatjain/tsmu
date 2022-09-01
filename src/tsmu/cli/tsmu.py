#!/usr/bin/env python3

from __future__ import annotations

import enum
import functools
import io
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from pprint import pprint  # NOQA
from shlex import quote as shquote
from typing import Any, Callable, Dict, Final, Generator, List, Optional, Set

import click
import pygments
import pygments.formatters.terminal
import pygments.lexers
import transmissionrpc
import transmissionrpc.utils


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


TorrentInformation = Dict[str, Any]


def Dump(
    tc: transmissionrpc.Client, field_names: Optional[List[str]] = None, include_files: bool = False
) -> Generator[TorrentInformation, None, None]:
    if field_names and include_files:
        field_names += ["files", "priorities", "wanted"]
    for t in tc.get_torrents(arguments=field_names):
        torrent_info = {
            "id": t.id,
            "name": t.name,
            "location": t.downloadDir,
            "status": t.status,
            "percentDone": t.percentDone,
        }

        if include_files:
            torrent_info["files"] = [fi["name"] for fi in t.files().values()]

        # add remaining arguments, ignoring those we handled already
        for fn in field_names:
            if fn in {"files", "downloadDir"}:
                continue
            if fn == "errorString":
                if t.errorString and len(t.errorString) > 0:
                    torrent_info["errorString"] = t.errorString
                continue
            torrent_info[fn] = getattr(t, fn)

        yield torrent_info


################################################################################

###
# from https://github.com/andy-gh/pygrid/blob/master/prettyjson.py

import types


def prettyjson(obj, indent=2, maxlinelength=80):
    """Renders JSON content with indentation and line splits/concatenations to fit maxlinelength.
    Only dicts, lists and basic types are supported"""

    items, _ = getsubitems(obj, itemkey="", islast=True, maxlinelength=maxlinelength)
    res = indentitems(items, indent, indentcurrent=0)
    return res


def getsubitems(obj, itemkey, islast, maxlinelength):
    items = []
    can_concat = (
        True  # assume we can concatenate inner content unless a child node returns an expanded list
    )

    isdict = isinstance(obj, dict)
    islist = isinstance(obj, list)
    istuple = isinstance(obj, tuple)

    # building json content as a list of strings or child lists
    if isdict or islist or istuple:
        if isdict:
            opening, closing, keys = ("{", "}", iter(obj.keys()))
        elif islist:
            opening, closing, keys = ("[", "]", range(0, len(obj)))
        elif istuple:
            opening, closing, keys = (
                "[",
                "]",
                range(0, len(obj)),
            )  # tuples are converted into json arrays

        if itemkey != "":
            opening = itemkey + ": " + opening
        if not islast:
            closing += ","

        # Get list of inner tokens as list
        count = 0
        subitems = []
        itemkey = ""
        for k in keys:
            count += 1
            islast_ = count == len(obj)
            itemkey_ = ""
            if isdict:
                itemkey_ = basictype2str(k)
            inner, can_concat_ = getsubitems(
                obj[k], itemkey_, islast_, maxlinelength
            )  # inner = (items, indent)
            subitems.extend(inner)  # inner can be a string or a list
            can_concat = (
                can_concat and can_concat_
            )  # if a child couldn't concat, then we are not able either

        # atttempt to concat subitems if all fit within maxlinelength
        if can_concat:
            totallength = 0
            for item in subitems:
                totallength += len(item)
            totallength += len(subitems) - 1  # spaces between items
            if totallength <= maxlinelength:
                str = ""
                for item in subitems:
                    str += item + " "  # add space between items, comma is already there
                str = str.strip()
                subitems = [str]  # wrap concatenated content in a new list
            else:
                can_concat = False

        # attempt to concat outer brackets + inner items
        if can_concat:
            if len(opening) + totallength + len(closing) <= maxlinelength:
                items.append(opening + subitems[0] + closing)
            else:
                can_concat = False

        if not can_concat:
            items.append(opening)  # opening brackets
            items.append(subitems)  # Append children to parent list as a nested list
            items.append(closing)  # closing brackets

    else:
        # basic types
        strobj = itemkey
        if strobj != "":
            strobj += ": "
        strobj += basictype2str(obj)
        if not islast:
            strobj += ","
        items.append(strobj)

    return items, can_concat


def basictype2str(obj):
    from json.encoder import py_encode_basestring

    if isinstance(obj, str):
        strobj = py_encode_basestring(obj)
        # strobj = "\"" + str(obj) + "\""
    elif isinstance(obj, bool):
        strobj = {True: "true", False: "false"}[obj]
    else:
        strobj = str(obj)
    return strobj


def indentitems(items, indent, indentcurrent):
    """Recursively traverses the list of json lines, adds indentation based on the current depth"""
    res = ""
    indentstr = " " * indentcurrent
    for item in items:
        if isinstance(item, list):
            res += indentitems(item, indent, indentcurrent + indent)
        else:
            res += indentstr + item + "\n"
    return res


################################################################################


BASE_FIELD_NAMES: Final[List[str]] = [
    "id",
    "name",
    "downloadDir",
    "status",
    "percentDone",
    "errorString",
]


class InterpretedPercentDone(enum.Enum):
    """Map a percentage to how we want to interpret that percentage.

    unspecified is for filtering; it means we don't care about the percentage.
    For the rest:

    • unspecified: for filtering, means don't care about interpreting
    • notstarted: percentDone=0
    • done: percentDone=100
    • incomplete: percentDone=0 and percentDone<100
    """

    # fmt: off
    unspecified = enum.auto()  # anything
    notstarted = enum.auto()   # 0
    done = enum.auto()         # 100
    incomplete = enum.auto()   # 0 and <100
    # fmt: on

    @staticmethod
    def predicate(pdt: InterpretedPercentDone, percent_done: float) -> bool:
        """Does percent_done meet the criteria of pdt?"""
        if pdt is InterpretedPercentDone.unspecified:
            return True
        elif pdt is InterpretedPercentDone.done and percent_done == 1:
            return True
        elif pdt is InterpretedPercentDone.notstarted and percent_done == 0:
            return True
        elif pdt is InterpretedPercentDone.incomplete and percent_done != 1:
            return True
        return False

    @staticmethod
    def ConvertForClick(
        ctx: click.Context, param: click.Parameter, value: str
    ) -> InterpretedPercentDone:
        if value not in InterpretedPercentDone.__members__:
            print("error")
            return None
        if value is not None:
            return InterpretedPercentDone[value]


class TorrentStatus(enum.Enum):
    """Not implemented."""

    check_pending = enum.auto()
    checking = enum.auto()
    downloading = enum.auto()
    stopped = enum.auto()
    seeding = enum.auto()

    @staticmethod
    def deserialize(s: str) -> TorrentStatus:
        # handle space in "check pending"
        if s == "check pending":
            return TorrentStatus.check_pending
        if s not in TorrentStatus.__members__:
            print("error")
            return None
        return TorrentStatus[s]


# Given a torrent, return true/false about it
FilterPredicate = Callable[[TorrentInformation], bool]
FilterPredicateAction = Callable[[TorrentInformation], None]


def _filter(
    filter_predicate: FilterPredicate,
    include_files: bool = False,
    ids: bool = False,
    field_names: List[str] = [],
    action: Optional[FilterPredicateAction] = None,
) -> None:
    tc = ConnectToTransmission()
    field_names += BASE_FIELD_NAMES
    merged: List[TorrentInformation] = [
        t
        for t in Dump(tc, field_names=field_names, include_files=include_files)
        if filter_predicate(t)
    ]
    if action:
        for t in merged:
            action(t)
        return
    if ids:
        ids_str = [str(t["id"]) for t in merged]
        click.echo(",".join(ids_str))
    else:  # full JSON
        jd = prettyjson(merged, indent=2)
        click.echo(
            pygments.highlight(
                jd, pygments.lexers.JsonLexer(), pygments.formatters.terminal.TerminalFormatter()
            )
        )


@click.group()
def cli() -> None:
    pass


@cli.command("dump")
@click.option("--ids", is_flag=True, help="Only print IDs")
@click.option("--include-files", is_flag=True)
@click.option(
    "-c",
    "--complete",
    help="",
    default="unspecified",
    type=click.Choice(InterpretedPercentDone.__members__.keys()),
    callback=InterpretedPercentDone.ConvertForClick,
)
def dump_cli(
    ids: bool = False,
    include_files: bool = False,
    complete: InterpretedPercentDone = InterpretedPercentDone.unspecified,
) -> None:
    """Dump all torrents. Filters allowed."""

    def DumpFilterPredicate(
        t: TorrentInformation,
        pd: InterpretedPercentDone = InterpretedPercentDone.notstarted,
    ) -> bool:
        """FilterPredicate for Dump."""
        percent_done = t["percentDone"]
        if InterpretedPercentDone.predicate(pd, percent_done):
            return True

        return False

    fp = functools.partial(DumpFilterPredicate, pd=complete)
    _filter(fp, include_files, ids)


@cli.command("fn")
@click.argument("filter_string")
@click.option("--ids", is_flag=True, help="Only print IDs")
@click.option("--include-files", is_flag=True)
@click.option(
    "-c",
    "--complete",
    help="",
    default="unspecified",
    type=click.Choice(InterpretedPercentDone.__members__.keys()),
    callback=InterpretedPercentDone.ConvertForClick,
)
def fn(
    filter_string: str,
    ids: bool = False,
    include_files: bool = False,
    complete: InterpretedPercentDone = InterpretedPercentDone.unspecified,
) -> None:
    """Filter by name. Case insensitive."""

    if filter_string.startswith("./"):
        filter_string = filter_string[2:]

    if filter_string.endswith("/"):
        filter_string = filter_string[:-1]

    def TorrentNameFilterPredicate(
        s: str,
        t: TorrentInformation,
        pd: InterpretedPercentDone = InterpretedPercentDone.notstarted,
    ) -> bool:
        """FilterPredicate for filter by name."""
        percent_done = t["percentDone"]
        if s.lower() in t["name"].lower() and InterpretedPercentDone.predicate(pd, percent_done):
            return True

        return False

    fp = functools.partial(TorrentNameFilterPredicate, filter_string, pd=complete)
    _filter(fp, include_files, ids)


@cli.command("fp")
@click.argument("filter_string")
@click.option("--ids", is_flag=True)
@click.option("--include-files", is_flag=True)
@click.option(
    "-c",
    "--complete",
    help="",
    default="unspecified",
    type=click.Choice(InterpretedPercentDone.__members__.keys()),
    callback=InterpretedPercentDone.ConvertForClick,
)
def fp(
    filter_string: str,
    ids: bool = False,
    include_files: bool = False,
    complete: InterpretedPercentDone = InterpretedPercentDone.unspecified,
) -> None:
    """Filter by path. Case sensitive."""

    def TorrentPathFilterPredicate(
        s: str,
        t: transmissionrpc.torrent,
        pd: InterpretedPercentDone = InterpretedPercentDone.notstarted,
    ) -> bool:
        """FilterPredicate for filter by path."""
        percent_done = t["percentDone"]
        if s in t["location"] and InterpretedPercentDone.predicate(pd, percent_done):
            return True

        return False

    fp = functools.partial(TorrentPathFilterPredicate, filter_string, pd=complete)
    _filter(fp, include_files, ids)


@cli.command("fpd")
@click.argument("filter_string")
@click.option("--ids", is_flag=True)
@click.option("--include-files", is_flag=True)
@click.option(
    "--names/--no-names",
    default=True,
    help="Dump torrents and metadata using torrent names, otherwise info hash",
)
@click.option(
    "-c",
    "--complete",
    help="",
    default="unspecified",
    type=click.Choice(InterpretedPercentDone.__members__.keys()),
    callback=InterpretedPercentDone.ConvertForClick,
)
def fpd(
    filter_string: str,
    ids: bool = False,
    include_files: bool = False,
    names: bool = True,
    complete: InterpretedPercentDone = InterpretedPercentDone.unspecified,
) -> None:
    """Filter by path, dump torrent information. Case sensitive. Path should be absolute."""

    def TorrentPathFilterPredicate(
        s: str,
        t: TorrentInformation,
        pd: InterpretedPercentDone = InterpretedPercentDone.notstarted,
    ) -> bool:
        """FilterPredicate for filter by path."""
        percent_done = t["percentDone"]
        if s in t["location"] and InterpretedPercentDone.predicate(pd, percent_done):
            return True

        return False

    filter_string_path = Path(filter_string)
    assert filter_string_path.exists()

    dumped = []
    field_names = [
        "hashString",
        "magnetLink",
        "torrentFile",
    ]

    def DumpAction(t: TorrentInformation):
        dumped.append(
            {
                "id": t["id"],
                "hash": t["hashString"],
                "name": t["name"],
                "downloadDir": t["location"],
                "magnetLink": t["magnetLink"],
                "percentDone": t["percentDone"],
                "torrentFile": t["torrentFile"],
            }
        )
        return

    fp = functools.partial(TorrentPathFilterPredicate, filter_string, pd=complete)
    _filter(fp, include_files, field_names=field_names, action=DumpAction)

    dump_directory = filter_string_path / f"{filter_string_path.name}.dump"
    dump_directory.mkdir(parents=True, exist_ok=True)
    print(f"Dumping into {dump_directory}")

    for ti in dumped:
        DumpTorrentMetadata(ti, dump_directory, use_name=names)
        print(ti["name"])


def DumpTorrentMetadata(
    torrent_info: TorrentInformation, output_path: Path, use_name: bool = False
) -> Path:
    assert "torrentFile" in torrent_info
    ti = torrent_info.copy()

    for unnecessary_attr in {"id", "downloadDir", "percentDone"}:
        del ti[unnecessary_attr]

    name = ti["name"]
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

    with Path(output_path / metadata_filename).open("w") as fp:
        fp.write(json.dumps(ti))

    return dest_torrent_full_path


@cli.command("ffl")
def ffl_cli() -> None:
    """First field as list."""
    column: List[int] = []

    for line in sys.stdin.readlines():
        lc = line.split()
        id = int(lc[0].strip("*"))
        column.append(id)

    column_as_str = (str(i) for i in column)
    click.echo(",".join(column_as_str))


@cli.command("magnets-here")
@click.argument("magnets_file", type=click.File("r"))
def magnets_here_cli(magnets_file: io.TextIOBase) -> None:
    """Add text file full of magnet links to current directory."""
    settings_file_path = (
        Path(click.get_app_dir("transmission-daemon"), "settings.json").expanduser().resolve()
    )
    settings = json.load(open(settings_file_path))
    rpc_port = settings["rpc-port"]
    for line in magnets_file.readlines():
        if line:
            line = line.strip()
        if not line:
            continue
        if line[0] == "#":
            continue
        print(f'transmission-remote {rpc_port} -w $(pwd) -a "{line}"')


@cli.command("incomplete-files")
@click.argument("torrent_id", type=int)
@click.option(
    "--parents",
    type=int,
    default=0,
    help="Number of parent directories to go up. 0 means first parent",
)
def incomplete_files_cli(torrent_id: int, parents: bool) -> None:
    """Print the parent directory of incomplete files."""
    tc = ConnectToTransmission()
    files = tc.get_files(torrent_id)[torrent_id]
    parent_paths: Set[Path] = set()  # unique parents

    for file_info in files.values():
        if file_info["size"] != file_info["completed"]:
            p = pathlib.PurePath(file_info["name"])
            parent_paths.add(p.parents[parents])

    for p in sorted(parent_paths):
        print("rm -rf " + str(p))


@cli.command("readd-stopped")
@click.argument("filter_string")
@click.option("--dry-run/--no-dry-run", default=True)
@click.option("--rsync-from-parent", is_flag=True, default=False)
@click.option("--rsync-from-dupes", is_flag=True, default=False)
def readd_stopped_cli(
    filter_string: str,
    dry_run: bool = True,
    rsync_from_parent: bool = False,
    rsync_from_dupes: bool = False,
) -> None:
    """Readd all torrents that have been stopped because disk was full.

    Pass "all" as an argument to readd-everything; otherwise, a filter to the
    path, not unlike the fp command.

    Instead of printing the normal output, for dupes directories
    --rsync-from-parent will print an rsync command attempting to copy the same
    files from the parent directory.

    This command will not do anything unless --no-dry-run is passed."""
    READD_FOLDER = Path("~/readded-torrents/").expanduser()
    READD_FOLDER.mkdir(exist_ok=True)

    tc = ConnectToTransmission()
    rows = []
    for t in tc.get_torrents():
        if t.error != 3:
            continue
        error_str = t.errorString
        if "No data found" in error_str:
            download_dir, magnet_link, torrent_file, = (
                t.downloadDir,
                t.magnetLink,
                t.torrentFile,
            )
            rows.append(
                {
                    "id": t.id,
                    "hash": t.hashString,
                    "name": t.name,
                    "downloadDir": t.downloadDir,
                    "magnetLink": t.magnetLink,
                    "percentDone": t.percentDone,
                    "torrentFile": torrent_file,
                }
            )

    for row in rows:
        name, hash, download_dir, magnet_link, transmission_torrent_file = (
            row["name"],
            row["hash"],
            row["downloadDir"],
            row["magnetLink"],
            row["torrentFile"],
        )
        # if 'rarbg-1080p' not in download_dir:
        # if 'revtt-1080p' not in download_dir:
        # if 'revtt-games' not in download_dir:
        # if 'rarbg-4K.HDR' not in download_dir:
        # if 'MP3-daily' not in download_dir:
        # if 'XXX' not in download_dir:
        # if '202112.51' not in download_dir:
        if filter_string != "all" and filter_string not in download_dir:
            continue
        backed_up_torrent_file = DumpTorrentMetadata(row, READD_FOLDER)
        # copied_file = shutil.copy2(transmission_torrent_file, READD_FOLDER)
        # metadata_file = READD_FOLDER / (hash + ".json")
        # with open(metadata_file, 'w') as fp:
        #    fp.write(json.dumps(row))
        # backed_up_torrent_file = Path(copied_file)

        if rsync_from_parent:
            out = f'rsync -aPv ../"{name}" . '
            print(out)
        if rsync_from_dupes:
            out = f'rsync -aPv dupes/"{name}" . '
            print(out)
        else:
            out = f"""
Readding hash={hash},
        name="{name}",
        downloadDir={download_dir}
        torrentFile={backed_up_torrent_file}""".strip()
            print(out)

        if not dry_run:
            while True:
                if os.getloadavg()[0] > 2.0:
                    print("Load is too high, waiting…")
                    time.sleep(5)
                    continue
                tc.remove_torrent(hash)
                tc.add_torrent(str(backed_up_torrent_file), download_dir=download_dir)
                break

    if dry_run:
        print("In dry-run mode, not doing anything. Re-run w/ --no-dry-run to take action.")

        # print(name, download_dir, backed_up_torrent_file)


@cli.command("rarbg-trackers")
def rarbg_trackers_cli() -> None:
    """List all trackers for rarbg torrents."""

    trackers = set()

    def RarbgFilterPredicate(t: TorrentInformation):
        for tracker in t["trackers"]:
            if "rarbg" in tracker["announce"]:
                return True
        return False

    trackers = set()

    def RarbgTrackersCollectAction(t: TorrentInformation):
        for tracker in t["trackers"]:
            tracker_url = tracker["announce"]
            if tracker_url.startswith("udp://") and tracker_url.endswith("/announce"):
                tracker_url = tracker_url[:-9]
            trackers.add(tracker_url)

    _filter(RarbgFilterPredicate, field_names=["trackers"], action=RarbgTrackersCollectAction)
    # _filter(RarbgFilterPredicate, field_names=['trackers'])

    pprint(trackers)


@cli.command()
@click.option("--dry-run/--no-dry-run", default=True)
def fix_fa_corruption(dry_run: bool = True) -> None:
    tc = ConnectToTransmission()
    rows = []
    downloadDirs = set()
    screwed_up_torrents = []

    READD_FOLDER = Path("~/readded-torrents/").expanduser()
    READD_FOLDER.mkdir(exist_ok=True)

    fields = ["torrentFile", "magnetLink", "hashString"]
    fields += BASE_FIELD_NAMES

    for t in tc.get_torrents(arguments=fields):

        if t.percentDone != 1 and t.status == "stopped":
            if t.downloadDir == "/archive/torrents/rarbg-1080p/202201.02.incomplete":
                screwed_up_torrents.append(t)

    max_count = 25
    count = 0
    for t in screwed_up_torrents:
        if count > max_count:
            return

        name = shlex.quote(t.name)
        if name.endswith(".mkv"):
            cmd = f"cd /archive/torrents/revtt-1080p/ && fdfind -F {name}"
        else:
            cmd = f"cd /archive/torrents/revtt-1080p/ && fdfind -F -td {name}"
        rv = subprocess.run(
            cmd,
            capture_output=True,
            shell=True,
            universal_newlines=True,
        )
        if not rv or not rv.stdout:
            print(f"Skipping {name} ,{cmd=}")
            continue

        skip_revtt = False
        if skip_revtt and "revolution" in t.magnetLink:
            continue

        count = count + 1

        locations = [line.strip() for line in rv.stdout.splitlines()]

        if len(locations) == 1:

            loc = Path("/archive/torrents/revtt-1080p") / locations[0]
            loc = loc.parent
            # print(name, loc, t.downloadDir)
            if loc == t.downloadDir:
                print(name)

        actual_location = None
        for loc in locations:
            if "02.incomplete" in loc:
                continue
            if skip_revtt and "revtt" in loc:
                continue
            actual_location = loc

        if actual_location is None:
            print(f"Unable to find location for {name}")
            print()
            continue

        actual_location = Path("/archive/torrents/revtt-1080p") / actual_location
        actual_location = actual_location.parent

        print(
            f"""
{name} ({hash})
               hash = {t.hashString}
  torrent directory = {t.downloadDir}
   actual directory = {actual_location}
"""
        )
        # print(locations)
        torrent_info = {
            "id": t.id,
            "hash": t.hashString,
            "name": t.name,
            "downloadDir": t.downloadDir,
            "magnetLink": t.magnetLink,
            "percentDone": t.percentDone,
            "torrentFile": t.torrentFile,
        }
        backed_up_torrent_file = DumpTorrentMetadata(torrent_info, READD_FOLDER)

        if not dry_run:
            tc.remove_torrent(t.hashString)
            tc.add_torrent(str(backed_up_torrent_file), download_dir=actual_location)

        with Path("~/fix-fa-corruption.sh").expanduser().open("a") as fp:
            fp.write(f"trash {t.downloadDir}/{name}\n")

    # pprint(downloadDirs)


@cli.command("test")
def test_cli() -> None:
    items = """
    Chaka_Khan-Hello_Happiness-SINGLE-WEB-2019-ENRAGED
    German_TOP100_Single_Charts_14_01_2019-MCG
    Junior_Roy_And_Ashanti_Selah-Urban_Observations-WEB-2018-RYG
    VA-1-32_Riddim-WEB-2018-RYG
    VA-Chiney_Wine_Riddim-WEB-2018-RYG
    VA-Looking_East_Reggae_Vibration-WEB-2018-RYG
    VA-Mastermix_Party_Animals_Volume_Two-REISSUE_REMASTERED-CD-FLAC-2008-WRE
    # bad
    Mdnr-23-WEB-2019-OND
    The_Madeira-Tribal_Fires-2012-FATHEAD
    The_Suppliers-First_Shipment_S.H.I.T.M-WEB-2017-ESG
    Tiesto-Live_At_Countdown_NYE_2018-SAT-12-31-2018-DARKAUDiO
    VA-Jammin-WEB-2018-RYG
    VA-Mastermix_Party_Animals_Volume_One-REISSUE_REMASTERED-CD-FLAC-2008-WRE
    VA-Mastermix_Party_Animals_Volume_Three-REISSUE_REMASTERED-CD-FLAC-2008-WRE
    Young_Twon-Longevity-WEB-2015-ESG
    """

    merged = []

    with Path("tsm.json").open() as fp:
        merged = json.load(fp)

    items = items.splitlines()
    # Ignore blank lines and lines beginning with '#'
    items = [i for i in items if i and not i.startswith("#")]

    for i in merged:
        if "201901" in i["location"]:
            name = i["name"]
            id = i["id"]

            has_problem = False
            for f in i["files"]:
                if name not in f:
                    has_problem = True

            if has_problem:
                continue

            print(f"# {id}, {name}")
            # print(f'transmission-remote -t {id} --move /home/xjjk/Downloads/torrents/Automatic.Music/201901/delete')
            print(f"transmission-remote -t {id} --remove")


if __name__ == "__main__":
    cli()
