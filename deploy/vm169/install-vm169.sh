#!/bin/bash
# Install both rns-map instances on vm169. Run as root from the unpacked tarball.
#
# Tarball layout (flat): rns_map.py, static/index.html, and everything in
# deploy/vm169/ (both .service files, map.mu, this script).
#
#   rns-map        :8085  LoRa only (RNode)          NomadNet /page/map.mu
#   rns-map-relay  :8086  t6-relay (ct167), no LoRa  NomadNet /page/relay-map.mu
set -e
SRC=$(dirname "$(readlink -f "$0")")
U=/home/user
TS=$(date +%Y%m%d-%H%M)

install -d -o user -g user $U/rns-map $U/rns-map/static
install -o user -g user -m 644 $SRC/rns_map.py $U/rns-map/
install -o user -g user -m 644 $SRC/static/index.html $U/rns-map/static/

if [ ! -x $U/rns-map/venv/bin/python ]; then
    su - user -c "python3 -m venv $U/rns-map/venv"
fi
su - user -c "$U/rns-map/venv/bin/pip install -q -U pip"
su - user -c "$U/rns-map/venv/bin/pip install -q rns==1.5.7 aiohttp==3.11.11 msgpack==1.1.2"

for unit in rns-map rns-map-relay; do
    install -m 644 $SRC/$unit.service /etc/systemd/system/$unit.service
done
systemctl daemon-reload
for unit in rns-map rns-map-relay; do
    systemctl enable $unit.service
    systemctl restart $unit.service
done

# NomadNet pages (one script, two names) + links on the index
P=$U/.nomadnetwork/storage/pages
B=$U/.nomadnetwork/storage/pagetext/index.body.mu
install -o user -g user -m 755 $SRC/map.mu $P/map.mu
install -o user -g user -m 755 $SRC/map.mu $P/relay-map.mu
[ -e $B.bak-$TS ] || cp -a $B $B.bak-$TS
grep -q "/page/map.mu" $B || \
    printf '\n`F0FD`[LoRa map`:/page/map.mu`]`f\n' >> $B
grep -q "/page/relay-map.mu" $B || \
    printf '\n`F0FD`[t6-relay map`:/page/relay-map.mu`]`f\n' >> $B

sleep 8
systemctl is-active rns-map rns-map-relay
