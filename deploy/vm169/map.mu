#!/home/user/nomadnet-env/bin/python3
# =============================================================================
#  map.mu / relay-map.mu  -  node maps for NomadNet visitors
#
#  One script, two pages. It picks its settings from its own file name:
#
#   map.mu        LoRa map: rns-map on :8085 keeps only nodes whose path goes
#                 out through vm169's RNode.
#   relay-map.mu  t6-relay map: rns-map on :8086 keeps only nodes reached
#                 through the ct167 relay (friends on 4242, LAN test clients
#                 on 4243). No LoRa nodes.
#
#  Both read the same data as the web dartboards, from rns-map's /api/nodes.
#  Kept short on purpose: every byte of these pages crosses the LoRa link.
# =============================================================================

import json, os, time, urllib.request

PAGES = {
    "map.mu": {
        "api":     "http://127.0.0.1:8085/api/nodes",
        "title":   "LoRa map (vm169):",
        "intro":   "Nodes heard by radio only, grouped by hops from vm169",
        "offset":  0,   # hops counted from vm169
        "direct":  "heard directly",
    },
    "relay-map.mu": {
        "api":     "http://127.0.0.1:8086/api/nodes",
        "title":   "t6-relay map (vm169):",
        "intro":   "Nodes connected via the t6 relay (ct167), no LoRa nodes,\n"
                   "grouped by hops from ct167",
        "offset":  1,   # vm169 -> ct167 is one hop; count from ct167 instead
        "direct":  "connected directly to ct167",
    },
}
PAGE = PAGES.get(os.path.basename(__file__), PAGES["map.mu"])

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


print("`l`Ffd0{}`f".format(PAGE["title"]))
print("`F0f2" + "─" * 40)
for line in PAGE["intro"].split("\n"):
    print("`F888{}`f".format(line))
print("")

try:
    with urllib.request.urlopen(PAGE["api"], timeout=5) as r:
        data = json.load(r)
except Exception:
    print("`Ff00Map service not answering right now.`f")
    raise SystemExit

now   = time.time()
nodes = [n for n in data["nodes"] if now - n["last_seen"] <= MAX_AGE]
for n in nodes:
    # 0 only happens on the relay map: destinations on ct167 itself (its lxmd)
    n["hops"] = max(n["hops"] - PAGE["offset"], 0)

if not nodes:
    print("`F888No nodes heard in the last 7 days.`f")

for hops in sorted({n["hops"] for n in nodes}):
    ring = [n for n in nodes if n["hops"] == hops]
    if hops == 0:
        label = "On ct167 itself"
    elif hops == 1:
        label = "1 hop - " + PAGE["direct"]
    else:
        label = "{} hops".format(hops)
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
