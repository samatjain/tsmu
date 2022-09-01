#!/usr/bin/env python3
"""
cd /home/xjjk/Mount/fs1018b/MP3-daily/
fd -td -d3 -x basename | rg MP3-daily | sort > ~/MP3-daily-have.txt
"""

import json
import subprocess

from pathlib import Path


def main():
    for line in Path("~/MP3-daily-have.txt").expanduser().read_text().splitlines():
        line = line.strip()

        if "MP3-daily-2020" not in line:
            continue

        cmd = f"~xjjk/tsmu.py fn {line}"
        completed_process = subprocess.run(
            cmd, shell=True, capture_output=True, universal_newlines=True
        )

        if not completed_process.stdout:
            continue

        output = completed_process.stdout
        if "[]" in output:
            continue

        parsed_json = json.loads(output)
        tid = parsed_json[0]["id"]

        cmd = f"transmission-remote -t {tid} --remove-and-delete"
        print(f"Already have {line}")
        print(cmd)
        subprocess.run(cmd, shell=True)


if __name__ == '__main__':
    main()
