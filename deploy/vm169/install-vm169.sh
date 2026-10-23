#!/bin/bash
# Install the LoRa-only rns-map on vm169. Run as root from the unpacked tarball.
set -e
SRC=$(dirname "$(readlink -f "$0")")
U=/home/user
TS=$(date +%Y%m%d-%H%M)

install -d -o user -g user $U/rns-map $U/rns-map/static
install -o user -g user -m 644 $SRC/rns-map/rns_map.py $U/rns-map/
install -o user -g user -m 644 $SRC/rns-map/static/index.html $U/rns-map/static/

if [ ! -x $U/rns-map/venv/bin/python ]; then
    su - user -c "python3 -m venv $U/rns-map/venv"
fi
su - user -c "$U/rns-map/venv/bin/pip install -q -U pip"
su - user -c "$U/rns-map/venv/bin/pip install -q rns==1.5.7 aiohttp==3.11.11 msgpack==1.1.2"

install -m 644 $SRC/rns-map/rns-map.service /etc/systemd/system/rns-map.service
systemctl daemon-reload
systemctl enable rns-map.service
systemctl restart rns-map.service

# NomadNet page + link on the index
P=$U/.nomadnetwork/storage/pages
B=$U/.nomadnetwork/storage/pagetext/index.body.mu
install -o user -g user -m 755 $SRC/map.mu $P/map.mu
if ! grep -q "/page/map.mu" $B; then
    cp -a $B $B.bak-$TS
    printf '\n`F0FD`[LoRa map`:/page/map.mu`]`f\n' >> $B
fi
sleep 8
systemctl is-active rns-map
