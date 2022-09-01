#!/bin/bash
# Given torrent file strewn about a filesystem, move whereever the torrent was
# downloaded to where the torrent file is.

torrent_filename="$1"
correct_dir=$(pwd)

info_hash=$(transmission-show "$torrent_filename" | rg Hash | cut -d" " -f4)
current_dir=$(transmission-remote -t "$info_hash" --info | rg Location | cut -d" " -f4)
if [[ "$correct_dir" != "$current_dir" ]]; then
    echo transmission-remote -t "$info_hash" --move "${correct_dir}"
fi
