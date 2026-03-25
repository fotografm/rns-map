# rns-map

A live Reticulum network visualiser. Listens for announces on a Reticulum mesh
network and displays nodes in real time on an interactive dartboard-style map,
colour-coded by application type (LXMF, Nomadnet, Propagation, Audio).

Built for Ubuntu 22.04 with an RNode LoRa interface. The web UI is
mobile-responsive and served locally — no internet connection required after
installation.

---

## How it works

```
RNode (LoRa hardware)
        |
      rnsd  <-- systemd service, owns the RNode interface
        |
   rns_map.py  <-- attaches as a shared-instance client (RNS.Reticulum())
        |           does NOT own any interfaces itself
        |
   aiohttp HTTP/WS server on port 8085
        |
   browser  <--  static/index.html (SVG dartboard, live WebSocket feed)
```

**rns-map is a client of rnsd — it never owns or starts its own RNS interfaces.**
rnsd must be running before rns-map starts. rns-map simply listens for
announces that rnsd receives and forwards them to the web UI.

---

## Requirements

- Ubuntu 22.04 (other Debian-based distros likely work)
- Python 3.10+
- An RNode LoRa device (or any other Reticulum-supported interface)
- `rnsd` running as a systemd service with at least one active interface
- The installing user must have permission to write to `/etc/systemd/system/`

---

## Which installation scenario applies to you?

Before following any steps below, answer this question:

**Do you already have Reticulum (`rnsd`) installed and running on this machine,**
**for example as part of a MeshChat or Nomadnet setup?**

- **Yes** → follow [Scenario A](#scenario-a--rnsd-already-running)
- **No** → follow [Scenario B](#scenario-b--fresh-install-no-existing-reticulum)

---

## Scenario A — rnsd already running

This is the most common case. If you already run MeshChat, Nomadnet, or any
other Reticulum application on this machine, rnsd is already handling your
hardware interface. rns-map will attach to it automatically.

**Do NOT set up a second rnsd. Do NOT copy config.example.**
Two rnsd instances trying to own the same hardware interface will conflict
and both will fail.

**1. Clone the repo:**

```bash
git clone https://github.com/fotografm/rns-map.git ~/rns-map
```

**2. Run the install script:**

```bash
bash ~/rns-map/install.sh
```

**3. Start the service:**

```bash
sudo systemctl start rns-map
journalctl -u rns-map -f
```

You should see:

```
[rns-map] Loaded N nodes from DB
[rns-map] Announce handlers registered
[rns-map] Serving on http://0.0.0.0:8085
```

**4. Open in browser:**

```
http://<your-machine-ip>:8085
```

That's it. rns-map will start populating as announces arrive from your
existing RNS network.

---

## Scenario B — Fresh install, no existing Reticulum

You need to set up rnsd first, then rns-map.

**1. Clone the repo:**

```bash
git clone https://github.com/fotografm/rns-map.git ~/rns-map
```

**2. Set up the Reticulum config:**

```bash
cp ~/rns-map/reticulum-config/config.example ~/rns-map/reticulum-config/config
nano ~/rns-map/reticulum-config/config
```

Edit the config to match your hardware. At minimum you need to set the correct
`port` for your RNode (check `ls /dev/ttyUSB*` or `ls /dev/ttyACM*`), and set
the correct `frequency` for your region. See the comments in `config.example`
for guidance.

**3. Install Reticulum and create an rnsd systemd service.**

Install the RNS package into rns-map's venv (install.sh will create it):

```bash
python3 -m venv ~/rns-map/venv
~/rns-map/venv/bin/pip install "rns==1.1.3"
```

Create `/etc/systemd/system/rnsd.service`:

```
[Unit]
Description=Reticulum Network Stack Daemon
After=network.target

[Service]
Type=simple
User=user
ExecStart=/home/user/rns-map/venv/bin/rnsd --config /home/user/rns-map/reticulum-config
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start rnsd:

```bash
sudo systemctl daemon-reload
sudo systemctl enable rnsd
sudo systemctl start rnsd
journalctl -u rnsd -f
```

Wait until you see rnsd reporting it has initialised the interface before
continuing.

**4. Run the install script:**

```bash
bash ~/rns-map/install.sh
```

**5. Start rns-map:**

```bash
sudo systemctl start rns-map
journalctl -u rns-map -f
```

**6. Open in browser:**

```
http://<your-machine-ip>:8085
```

---

## Common pitfalls

**The map loads but no nodes ever appear**
rnsd may not be receiving any announces yet — this is normal on a quiet
network. LoRa announces can be infrequent. Leave the map open for 10–15
minutes. If you have Nomadnet or MeshChat running on the same machine they
will generate announces immediately on startup.

**rns-map starts but immediately crashes with a connection error**
rnsd is not running or has not finished starting up. Check with
`systemctl status rnsd`. rns-map's systemd service has a 10-second restart
delay built in — it will retry automatically.

**Port 8085 is already in use**
Another service is using port 8085. Edit `rns_map.py` and change `PORT = 8085`
to a free port, then restart the service.

**Permission denied on /dev/ttyUSB0**
Your user is not in the `dialout` group. Fix with:
```bash
sudo usermod -aG dialout user
```
Then log out and back in, or reboot.

**Two rnsd instances clashing (Scenario A users who also ran config.example)**
If you accidentally started a second rnsd, stop and disable it:
```bash
sudo systemctl stop rnsd
sudo systemctl disable rnsd
```
Then restart the original rnsd and rns-map.

**git push asks for a password and rejects my GitHub password**
GitHub no longer accepts account passwords for git operations. You must use a
Personal Access Token. See:
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token

**The web UI shows a red dot and "reconnecting" in the status bar**
The WebSocket connection to rns-map has dropped. This usually means rns-map
crashed or was restarted. Check `journalctl -u rns-map -f`. The browser will
reconnect automatically once the service is back up.

---

## Dependencies (pinned)

| Package  | Version |
|----------|---------|
| rns      | 1.1.3   |
| aiohttp  | 3.9.5   |
| msgpack  | 1.1.2   |

---

## Service management

```bash
sudo systemctl status rns-map
sudo systemctl restart rns-map
sudo systemctl stop rns-map
journalctl -u rns-map -f
```

---

## API endpoints

| Method | Path        | Description                        |
|--------|-------------|------------------------------------|
| GET    | `/`         | Serves the web UI (index.html)     |
| GET    | `/ws`       | WebSocket — live announce events   |
| GET    | `/activity` | JSON: per-minute announce counts   |
| POST   | `/reset`    | Wipe node database, reset the map  |

---

## WebSocket message types

All messages are JSON.

**`state`** — sent once on connect, full node list:
```json
{"type": "state", "nodes": [...]}
```

**`announce`** — new or updated node:
```json
{"type": "announce", "node": {"hash": "...", "name": "...", "app_type": "lxmf", "hops": 2, "first_seen": 1234567890.0, "last_seen": 1234567890.0}, "ts": 1234567890.0}
```

**`reset`** — node DB has been wiped:
```json
{"type": "reset"}
```

---

## Node types

| Colour | Type        | Aspect filter        |
|--------|-------------|----------------------|
| Cyan   | LXMF        | `lxmf.delivery`      |
| Green  | Nomadnet    | `nomadnetwork.node`  |
| Orange | Propagation | `lxmf.propagation`   |
| Purple | Audio       | `call.audio`         |

---

## Hop rings

| Ring    | Meaning      |
|---------|--------------|
| Centre  | Direct (0 hops) |
| Ring 1  | 1 hop        |
| Ring 2  | 2 hops       |
| Ring 3  | 3+ hops      |

---

## Licence

MIT
