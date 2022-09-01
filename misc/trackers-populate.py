#!/usr/bin/env python3

# Get this list from `tsmu rarbg-trackers`
trackers = {
    'http://explodie.org:6969/announce',
    'http://tracker.tfile.co:80/announce',
    'http://tracker.trackerfix.com:80/announce',
    'udp://9.rarbg.me:2720',
    'udp://9.rarbg.me:2730',
    'udp://9.rarbg.me:2740',
    'udp://9.rarbg.me:2750',
    'udp://9.rarbg.me:2760',
    'udp://9.rarbg.me:2770',
    'udp://9.rarbg.me:2780',
    'udp://9.rarbg.me:2790',
    'udp://9.rarbg.me:2800',
    'udp://9.rarbg.me:2810',
    'udp://9.rarbg.me:2820',
    'udp://9.rarbg.me:2830',
    'udp://9.rarbg.me:2840',
    'udp://9.rarbg.me:2850',
    'udp://9.rarbg.me:2860',
    'udp://9.rarbg.me:2870',
    'udp://9.rarbg.me:2880',
    'udp://9.rarbg.me:2890',
    'udp://9.rarbg.me:2900',
    'udp://9.rarbg.me:2910',
    'udp://9.rarbg.me:2920',
    'udp://9.rarbg.me:2930',
    'udp://9.rarbg.me:2940',
    'udp://9.rarbg.me:2950',
    'udp://9.rarbg.me:2960',
    'udp://9.rarbg.me:2970',
    'udp://9.rarbg.me:2980',
    'udp://9.rarbg.me:2990',
    'udp://9.rarbg.to:2710',
    'udp://9.rarbg.to:2720',
    'udp://9.rarbg.to:2730',
    'udp://9.rarbg.to:2740',
    'udp://9.rarbg.to:2750',
    'udp://9.rarbg.to:2760',
    'udp://9.rarbg.to:2770',
    'udp://9.rarbg.to:2780',
    'udp://9.rarbg.to:2790',
    'udp://9.rarbg.to:2800',
    'udp://9.rarbg.to:2810',
    'udp://9.rarbg.to:2820',
    'udp://9.rarbg.to:2830',
    'udp://9.rarbg.to:2840',
    'udp://9.rarbg.to:2850',
    'udp://9.rarbg.to:2860',
    'udp://9.rarbg.to:2870',
    'udp://9.rarbg.to:2880',
    'udp://9.rarbg.to:2890',
    'udp://9.rarbg.to:2900',
    'udp://9.rarbg.to:2910',
    'udp://9.rarbg.to:2920',
    'udp://9.rarbg.to:2930',
    'udp://9.rarbg.to:2940',
    'udp://9.rarbg.to:2950',
    'udp://9.rarbg.to:2960',
    'udp://9.rarbg.to:2970',
    'udp://9.rarbg.to:2980',
    'udp://9.rarbg.to:2990',
    'udp://bt.xxx-tracker.com:2710',
    'udp://denis.stalker.upeer.me:6969',
    'udp://eddie4.nl:6969',
    'udp://exodus.desync.com:6969',
    'udp://explodie.org:6969',
    'udp://ipv4.tracker.harry.lu:80',
    'udp://ipv6.tracker.harry.lu:80',
    'udp://open.demonii.si:1337',
    'udp://open.stealth.si:80',
    'udp://opentor.org:2710',
    'udp://retracker.lanta-net.ru:2710',
    'udp://torrentclub.tech:6969',
    'udp://tracker.coppersurfer.tk:6969',
    'udp://tracker.cyberia.is:6969',
    'udp://tracker.fatkhoala.org:13710',
    'udp://tracker.fatkhoala.org:13720',
    'udp://tracker.fatkhoala.org:13730',
    'udp://tracker.fatkhoala.org:13740',
    'udp://tracker.fatkhoala.org:13750',
    'udp://tracker.fatkhoala.org:13760',
    'udp://tracker.fatkhoala.org:13770',
    'udp://tracker.fatkhoala.org:13780',
    'udp://tracker.fatkhoala.org:13790',
    'udp://tracker.fatkhoala.org:13800',
    'udp://tracker.internetwarriors.net:1337',
    'udp://tracker.justseed.it:1337',
    'udp://tracker.leechers-paradise.org:6969',
    'udp://tracker.mg64.net:6969',
    'udp://tracker.moeking.me:6969',
    'udp://tracker.open-internet.nl:6969',
    'udp://tracker.openbittorrent.com:80',
    'udp://tracker.opentrackr.org:1337',
    'udp://tracker.pirateparty.gr:6969',
    'udp://tracker.port443.xyz:6969',
    'udp://tracker.slowcheetah.org:14710',
    'udp://tracker.slowcheetah.org:14720',
    'udp://tracker.slowcheetah.org:14730',
    'udp://tracker.slowcheetah.org:14740',
    'udp://tracker.slowcheetah.org:14750',
    'udp://tracker.slowcheetah.org:14760',
    'udp://tracker.slowcheetah.org:14770',
    'udp://tracker.slowcheetah.org:14780',
    'udp://tracker.slowcheetah.org:14790',
    'udp://tracker.slowcheetah.org:14800',
    'udp://tracker.tallpenguin.org:15710',
    'udp://tracker.tallpenguin.org:15720',
    'udp://tracker.tallpenguin.org:15730',
    'udp://tracker.tallpenguin.org:15740',
    'udp://tracker.tallpenguin.org:15750',
    'udp://tracker.tallpenguin.org:15760',
    'udp://tracker.tallpenguin.org:15770',
    'udp://tracker.tallpenguin.org:15780',
    'udp://tracker.tallpenguin.org:15790',
    'udp://tracker.tallpenguin.org:15800',
    'udp://tracker.thinelephant.org:12710',
    'udp://tracker.thinelephant.org:12720',
    'udp://tracker.thinelephant.org:12730',
    'udp://tracker.thinelephant.org:12740',
    'udp://tracker.thinelephant.org:12750',
    'udp://tracker.thinelephant.org:12760',
    'udp://tracker.thinelephant.org:12770',
    'udp://tracker.thinelephant.org:12780',
    'udp://tracker.thinelephant.org:12790',
    'udp://tracker.thinelephant.org:12800',
    'udp://tracker.tiny-vps.com:6969',
    'udp://tracker.torrent.eu.org:451',
    'udp://tracker.zer0day.to:1337',
}

# torrent IDs to add trackers
# e.g. from `tsm 9092 -l | rg -i mp3-daily | rg -v '100%' | tsmu ffl``
TRANSMISSION_TORRENTS = "12234"

torrent_range = TRANSMISSION_TORRENTS.split(',')
# OR: comment out this if not using
torrent_range = range(49, 15383)

for tid in torrent_range:
    for t in trackers:
        print(f"transmission-remote -t {tid} --tracker-add {t}")
