#!/bin/bash
set -eEuo pipefail
TRANSMISSION_PORT=9092

# call w/ fd -td -d1 -x bash fix-hot.sh

torrent_name=$1
torrent_name=$(basename "$1")
old_path=$(fdfind --absolute-path -F "$torrent_name" ../02-baked)
[[ $(echo -n "$old_path" | grep -c '^') == "1" ]] || (
	echo "Found more than 1 location for $torrent_name"
	exit 1
)

old_path=$(dirname "$old_path")

tid=$(~xjjk/tsmu.py fn "$torrent_name" --ids)
echo transmission-remote "$TRANSMISSION_PORT" -t "$tid" --move "$old_path"
