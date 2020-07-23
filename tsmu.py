#!/usr/bin/env python3

from __future__ import annotations

import enum
import functools
import json
import sys
from pathlib import Path
from pprint import pprint
from shlex import quote as shquote
from typing import Callable, Final, List

import click
import pygments, pygments.lexers, pygments.formatters.terminal

import transmissionrpc, transmissionrpc.utils


def ConnectToTransmission() -> transmissionrpc.Client:
    settings_file_path = Path('~/.config/transmission-daemon/settings.json').expanduser().resolve()
    settings = json.load(open(settings_file_path))

    host, port, username, password = 'localhost', settings['rpc-port'], None, None
    tc = transmissionrpc.Client(host, port, username, password)
    return tc


def Dump(tc: transmissionrpc.Client, arguments=None, include_files: bool = False):
    if arguments and include_files:
        arguments += ['files', 'priorities', 'wanted']
    for t in tc.get_torrents(arguments=arguments):
        if include_files:
            files = [fi['name'] for fi in t.files().values()]
        else:
            files = []
        yield {
            "id": t.id,
            "name": t.name,
            "location": t.downloadDir,
            "status": t.status,
            "percentDone": t.percentDone,
            "files": files
        }


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
    can_concat = True      # assume we can concatenate inner content unless a child node returns an expanded list

    isdict = isinstance(obj, dict)
    islist = isinstance(obj, list)
    istuple = isinstance(obj, tuple)

    # building json content as a list of strings or child lists
    if isdict or islist or istuple:
        if isdict: opening, closing, keys = ("{", "}", iter(obj.keys()))
        elif islist: opening, closing, keys = ("[", "]", range(0, len(obj)))
        elif istuple: opening, closing, keys = ("[", "]", range(0, len(obj)))    # tuples are converted into json arrays

        if itemkey != "": opening = itemkey + ": " + opening
        if not islast: closing += ","

        # Get list of inner tokens as list
        count = 0
        subitems = []
        itemkey = ""
        for k in keys:
            count += 1
            islast_ = count == len(obj)
            itemkey_ = ""
            if isdict: itemkey_ = basictype2str(k)
            inner, can_concat_ = getsubitems(obj[k], itemkey_, islast_, maxlinelength)    # inner = (items, indent)
            subitems.extend(inner)                      # inner can be a string or a list
            can_concat = can_concat and can_concat_     # if a child couldn't concat, then we are not able either

        # atttempt to concat subitems if all fit within maxlinelength
        if (can_concat):
            totallength = 0
            for item in subitems:
                totallength += len(item)
            totallength += len(subitems)-1     # spaces between items
            if (totallength <= maxlinelength):
                str = ""
                for item in subitems:
                    str += item + " "      # add space between items, comma is already there
                str = str.strip()
                subitems = [ str ]         # wrap concatenated content in a new list
            else:
                can_concat = False

        # attempt to concat outer brackets + inner items
        if (can_concat):
            if (len(opening) + totallength + len(closing) <= maxlinelength):
                items.append(opening + subitems[0] + closing)
            else:
                can_concat = False

        if (not can_concat):
            items.append(opening)       # opening brackets
            items.append(subitems)      # Append children to parent list as a nested list
            items.append(closing)       # closing brackets

    else:
        # basic types
        strobj = itemkey
        if strobj != "": strobj += ": "
        strobj += basictype2str(obj)
        if not islast: strobj += ","
        items.append(strobj)

    return items, can_concat


def basictype2str(obj):
    if isinstance (obj, str):
        strobj = "\"" + str(obj) + "\""
    elif isinstance(obj, bool):
        strobj = { True: "true", False: "false" }[obj]
    else:
        strobj = str(obj)
    return strobj


def indentitems(items, indent, indentcurrent):
    """Recursively traverses the list of json lines, adds indentation based on the current depth"""
    res = ""
    indentstr = " " * indentcurrent
    for item in items:
        if (isinstance(item, list)):
            res += indentitems(item, indent, indentcurrent + indent)
        else:
            res += indentstr + item + "\n"
    return res

################################################################################


BASE_ARGUMENTS: Final[List[str]] = ['id', 'name', 'downloadDir', 'status', 'percentDone']

class PercentDone(enum.Enum):
    unspecified = enum.auto()  # anything
    notstarted = enum.auto()   # 0
    done = enum.auto()         # 100
    incomplete = enum.auto()   # 0 and <100

    @staticmethod
    def predicate(pdt: PercentDone, percent_done: float) -> bool:
        if pdt is PercentDone.unspecified:
            return True
        elif pdt is PercentDone.done and percent_done == 1:
            return True
        elif pdt is PercentDone.notstarted and percent_done == 0:
            return True
        elif pdt is PercentDone.incomplete and percent_done != 1:
            return True


class TorrentStatus(enum.Enum):
    """Not implemented."""
    stopped = enum.auto()
    seeding = enum.auto()


FilterPredicate = Callable[[transmissionrpc.Torrent], bool]


def _filter(
    filter_predicate: FilterPredicate,
    include_files: bool = False,
    ids: bool = False
):
    tc = ConnectToTransmission()
    merged = [t for t in Dump(tc, arguments=BASE_ARGUMENTS, include_files=include_files) if filter_predicate(t)]
    if ids:
        ids_str = [str(t['id']) for t in merged]
        click.echo(','.join(ids_str))
    else:  # full JSON
        jd = prettyjson(merged, indent=2)
        click.echo(pygments.highlight(jd,
                                        pygments.lexers.JsonLexer(),
                                        pygments.formatters.terminal.TerminalFormatter()))


def ConvertComplete(ctx: click.Context, param: str, value: str):
    if value not in PercentDone.__members__:
        print("error")
    if value is not None:
        return PercentDone[value]



@click.group()
def cli() -> None:
    pass


@cli.command("dump")
@click.option("--ids", is_flag=True, help="Only print IDs")
@click.option("--include-files", is_flag=True)
@click.option("-c", "--complete", help="", default="unspecified",
               type=click.Choice(PercentDone.__members__.keys()),
               callback=ConvertComplete)
def dump_cli(
    ids: bool = False,
    include_files: bool = False,
    complete: PercentDone = PercentDone.unspecified
):
    """Dump. Filters allowed."""

    def DumpFilterPredicate(
        t: transmissionrpc.torrent,
        pd: PercentDone = PercentDone.notstarted,
    ) -> bool:
        percent_done = t['percentDone']
        if PercentDone.predicate(pd, percent_done):
            return True

        return False

    fp = functools.partial(DumpFilterPredicate, pd=complete)
    _filter(fp, include_files, ids)


@cli.command("fn")
@click.argument("filter_string")
@click.option("--ids", is_flag=True, help="Only print IDs")
@click.option("--include-files", is_flag=True)
@click.option("-c", "--complete", help="", default="unspecified",
               type=click.Choice(PercentDone.__members__.keys()),
               callback=ConvertComplete)
def fn(
    filter_string: str,
    ids: bool = False,
    include_files: bool = False,
    complete: PercentDone = PercentDone.unspecified
):
    """Filter by name. Case insensitive."""

    def TorrentNameFilterPredicate(
        s: str,
        t: transmissionrpc.torrent,
        pd: PercentDone = PercentDone.notstarted,
    ) -> bool:
        percent_done = t['percentDone']
        if s.lower() in t['name'].lower() and PercentDone.predicate(pd, percent_done):
            return True

        return False

    fp = functools.partial(TorrentNameFilterPredicate, filter_string, pd=complete)
    _filter(fp, include_files, ids)


@cli.command("fp")
@click.argument("filter_string")
@click.option("--ids", is_flag=True)
@click.option("--include-files", is_flag=True)
@click.option("-c", "--complete", help="", default="unspecified",
               type=click.Choice(PercentDone.__members__.keys()),
               callback=ConvertComplete)
def fp(
    filter_string: str,
    ids: bool = False,
    include_files: bool = False,
    complete: PercentDone = PercentDone.unspecified
):
    """Filter by path. Case sensitive."""

    def TorrentPathFilterPredicate(
        s: str,
        t: transmissionrpc.torrent,
        pd: PercentDone = PercentDone.notstarted,
    ) -> bool:
        percent_done = t['percentDone']
        if s in t['location'] and PercentDone.predicate(pd, percent_done):
            return True

        return False

    fp = functools.partial(TorrentPathFilterPredicate, filter_string, pd=complete)
    _filter(fp, include_files, ids)


@cli.command("ffl")
def ffl_cli():
    """First field as list."""

    column: List[int] = []

    for line in sys.stdin.readlines():
        lc = line.split()
        id = int(lc[0].strip('*'))
        column.append(id)

    column_as_str = (str(i) for i in column)
    click.echo(','.join(column_as_str))


@cli.command("magnets-here")
@click.argument('magnets_file', type=click.File('r'))
def magnets_here_cli(magnets_file):
    """Add text file full of magnet links to current directory."""
    for line in magnets_file.readlines():
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        if line[0] == '#':
            continue
        print(f'transmission-remote -w $(pwd) -a "{line}"')


@cli.command("test")
def test_cli():
    items = '''
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
    '''

    merged = []

    with Path('tsm.json').open() as fp:
        merged = json.load(fp)

    items = items.splitlines()
    # Ignore blank lines and lines beginning with '#'
    items = [i for i in items if i and not i.startswith('#')]

    for i in merged:
        if '201901' in i['location']:
            name = i['name']
            id = i['id']

            has_problem = False
            for f in i['files']:
                if name not in f:
                    has_problem = True

            if has_problem:
                continue

            print(f'# {id}, {name}')
            #print(f'transmission-remote -t {id} --move /home/xjjk/Downloads/torrents/Automatic.Music/201901/delete')
            print(f'transmission-remote -t {id} --remove')


if __name__ == '__main__':
    cli()
