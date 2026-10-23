#!/home/user/nomadnet-env/bin/python3
# =============================================================================
#  map.mu  -  LoRa-only node map for NomadNet visitors
#
#  The same data as the rns-map dartboard on http://192.168.177.169:8085,
#  read from its /api/nodes endpoint. rns-map only keeps nodes whose path
#  goes out through vm169's RNode, so this page is LoRa only too: nodes that
#  arrive via the ct167 relay never appear.
#
#  Nodes are grouped by hops, like the rings of the dartboard. Kept short on
#  purpose: every byte of this page crosses the LoRa link.
# =============================================================================

import json, time, urllib.request

API     = "http://127.0.0.1:8085/api/nodes"
MAX_AGE = 7 * 86400     # hide nodes not heard for a week
NAME_W  = 24

KIND = {"lxmf": "chat", "nomadnet": "node", "propagation": "prop",
        "audio": "call"}


def ago(ts):
    s = int(time.time() - ts)
    if s < 3600:  return "{}m".format(s // 60)
    if s < 86400: return "{}h".format(s // 3600)
    return "{}d".format(s // 86400)


def clean(name):
    # Micron treats ` as a formatting character
    name = name.replace("`", "'")
    return name if len(name) <= NAME_W else name[:NAME_W - 1] + "~"


print("`l`Ffd0LoRa map (vm169):`f")
print("`F0f2" + "─" * 40)
print("`F888Nodes heard by radio only, grouped by hops from vm169`f")
print("")

try:
    with urllib.request.urlopen(API, timeout=5) as r:
        data = json.load(r)
except Exception:
    print("`Ff00Map service not answering right now.`f")
    raise SystemExit

now   = time.time()
nodes = [n for n in data["nodes"] if now - n["last_seen"] <= MAX_AGE]

if not nodes:
    print("`F888No LoRa nodes heard in the last 7 days.`f")

for hops in sorted({n["hops"] for n in nodes}):
    ring = [n for n in nodes if n["hops"] == hops]
    label = "1 hop - heard directly" if hops == 1 else "{} hops".format(hops)
    print("`Ffd0{}`f".format(label))
    for n in ring:
        print("  `Fddd{:<{w}}`f `F0fd{:<4}`f `F888{:>4} ago`f".format(
            clean(n["name"]), KIND.get(n["app_type"], n["app_type"]),
            ago(n["last_seen"]), w=NAME_W))
    print("")

print("`F888chat = LXMF  node = NomadNet  prop = propagation  call = audio`f")
print("`F888{} nodes - updated {}`f".format(
    len(nodes), time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))))
print("")
print("`F0FD`[Back to index`:/page/index.mu`]`f")
