#!/usr/bin/env python3
"""
rns_map.py  -  Reticulum live network map backend.

Architecture
------------
This process attaches to a running rnsd instance as a shared-instance client
(RNS.Reticulum() with no arguments). It does NOT own any interfaces itself.
rnsd must be started first using the reticulum-config/config in this directory.

Four announce handlers are registered, one per application aspect, so each
node type is identified and colour-coded correctly in the frontend.

Nodes and per-minute activity buckets are persisted in a local SQLite database
(nodes.db) so the map survives service restarts.

HTTP + WebSocket served on PORT 8085:
  GET  /          -> static/index.html  (the dartboard UI)
  GET  /ws        -> WebSocket upgrade  (live announce events)
  GET  /activity  -> JSON array of per-minute activity buckets (last 24h)
  POST /reset     -> wipe nodes table and broadcast reset event to all clients
"""

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path

import RNS
from aiohttp import web
import aiohttp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).parent          # ~/rns-map/
STATIC_DIR = BASE_DIR / "static"            # ~/rns-map/static/
DB_PATH    = BASE_DIR / "nodes.db"          # SQLite database file
RNS_CONFIG = BASE_DIR / "reticulum-config"  # passed to rnsd, not used here
PORT       = 8085                           # HTTP/WS listen port

BUCKET_SECS = 60            # Activity history granularity: 1-minute buckets
MAX_BUCKETS = 24 * 60       # Keep 24 hours of activity history

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_loop           = None          # asyncio event loop reference (set in main())
_ws_clients     = set()         # currently connected WebSocket clients
_nodes          = {}            # in-memory node cache: {hash_hex: node_dict}
_db_lock        = threading.Lock()  # serialise SQLite writes from threads
_announce_count = 0             # running count of announces received

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def db_init():
    """Create tables if they don't exist yet."""
    with sqlite3.connect(str(DB_PATH)) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                hash       TEXT PRIMARY KEY,
                name       TEXT,
                app_type   TEXT,
                hops       INTEGER,
                first_seen REAL,
                last_seen  REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                bucket_ts  INTEGER,
                app_type   TEXT,
                count      INTEGER DEFAULT 0,
                PRIMARY KEY (bucket_ts, app_type)
            )
        """)
        c.commit()

def db_load():
    """Load all persisted nodes into the in-memory cache on startup."""
    with sqlite3.connect(str(DB_PATH)) as c:
        for row in c.execute(
            "SELECT hash, name, app_type, hops, first_seen, last_seen FROM nodes"
        ):
            _nodes[row[0]] = {
                "hash":       row[0],
                "name":       row[1],
                "app_type":   row[2],
                "hops":       row[3],
                "first_seen": row[4],
                "last_seen":  row[5],
            }

def db_upsert_node(node):
    """Insert or replace a node record. Called from a background thread."""
    with _db_lock:
        with sqlite3.connect(str(DB_PATH)) as c:
            c.execute("""
                INSERT OR REPLACE INTO nodes
                (hash, name, app_type, hops, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                node["hash"], node["name"], node["app_type"],
                node["hops"], node["first_seen"], node["last_seen"],
            ))
            c.commit()

def db_record_activity(app_type: str):
    """
    Increment the announce counter for this app_type in the current
    1-minute bucket, then prune buckets older than MAX_BUCKETS.
    Called from a background thread.
    """
    bucket = int(time.time() // BUCKET_SECS) * BUCKET_SECS
    with _db_lock:
        with sqlite3.connect(str(DB_PATH)) as c:
            c.execute("""
                INSERT INTO activity (bucket_ts, app_type, count)
                VALUES (?, ?, 1)
                ON CONFLICT(bucket_ts, app_type) DO UPDATE SET count = count + 1
            """, (bucket, app_type))
            cutoff = bucket - MAX_BUCKETS * BUCKET_SECS
            c.execute("DELETE FROM activity WHERE bucket_ts < ?", (cutoff,))
            c.commit()

def db_get_activity():
    """
    Return the last 24h of activity as a list of dicts, one per minute bucket.
    Each dict has keys: ts, lxmf, nomadnet, propagation, audio.
    """
    cutoff = int(time.time()) - MAX_BUCKETS * BUCKET_SECS
    with sqlite3.connect(str(DB_PATH)) as c:
        rows = c.execute("""
            SELECT bucket_ts, app_type, count FROM activity
            WHERE bucket_ts >= ?
            ORDER BY bucket_ts ASC
        """, (cutoff,)).fetchall()
    # Pivot rows into one dict per bucket timestamp
    pivot = {}
    for ts, app_type, count in rows:
        if ts not in pivot:
            pivot[ts] = {"ts": ts, "lxmf": 0, "nomadnet": 0,
                         "propagation": 0, "audio": 0}
        if app_type in pivot[ts]:
            pivot[ts][app_type] = count
    return sorted(pivot.values(), key=lambda x: x["ts"])

def db_reset_nodes():
    """Delete all rows from the nodes table."""
    with _db_lock:
        with sqlite3.connect(str(DB_PATH)) as c:
            c.execute("DELETE FROM nodes")
            c.commit()

# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------

def _parse_name(app_data, fallback: str) -> str:
    """
    Extract a human-readable name from the announce app_data bytes.

    LXMF delivery announces encode app_data as msgpack: [name_bytes, stamp_cost]
    Nomadnet announces may use plain UTF-8 or a JSON dict with 'server_name'.
    Propagation nodes send a plain UTF-8 name string.
    Falls back to the first 12 hex chars of the destination hash if nothing parses.
    """
    if not app_data:
        return fallback

    # Try msgpack first (LXMF delivery format)
    try:
        import msgpack
        unpacked = msgpack.unpackb(app_data, raw=True)
        if isinstance(unpacked, (list, tuple)) and len(unpacked) >= 1:
            first = unpacked[0]
            if isinstance(first, bytes) and len(first) >= 1:
                name = first.decode("utf-8").strip()
                if name:
                    return name
    except Exception:
        pass

    # Try plain UTF-8 (propagation nodes, nomadnet)
    try:
        decoded = app_data.decode("utf-8").strip()
        if not decoded:
            return fallback
        # Nomadnet sometimes sends JSON with a server_name key
        if decoded.startswith("{") and "server_name" in decoded:
            return json.loads(decoded).get("server_name", fallback)
        if decoded.isprintable() and len(decoded) >= 1:
            return decoded
    except Exception:
        pass

    return fallback

# ---------------------------------------------------------------------------
# Hop count
# ---------------------------------------------------------------------------

def _get_hops(destination_hash: bytes, announce_packet_hash=None) -> int:
    """
    Determine the hop count for a destination hash using the RNS routing table.

    RNS.Transport.hops_to() works correctly in shared-instance client mode —
    the transport state is synchronised from rnsd and is queryable here.

    RNS.Transport.PATHFINDER_M (128) is the sentinel value meaning "no known
    path". We treat that as 1 (assume direct) rather than showing it as 128.
    Clamp the result to [0, 6] to avoid spurious large values.
    """
    try:
        hops = RNS.Transport.hops_to(destination_hash)
        # 128 = PATHFINDER_M = no known path; fall back to 1
        if hops >= 128:
            return 1
        return min(max(hops, 0), 6)
    except Exception as e:
        print("[rns-map] _get_hops error: {}".format(e), flush=True)
    return 1

# ---------------------------------------------------------------------------
# Core announce processor
# ---------------------------------------------------------------------------

def _process(app_type: str, destination_hash: bytes, announced_identity,
             app_data, kwargs):
    """
    Called by each announce handler. Builds a node dict, updates the
    in-memory cache and SQLite, then fires a WebSocket broadcast.
    Runs on the RNS announce thread (not the asyncio loop thread).
    """
    global _announce_count
    try:
        hash_hex  = destination_hash.hex()
        now       = time.time()
        name      = _parse_name(app_data, hash_hex[:12])
        hops      = min(max(_get_hops(destination_hash,
                            kwargs.get("announce_packet_hash")), 0), 6)
        _announce_count += 1

        node = {
            "hash":       hash_hex,
            "name":       name,
            "app_type":   app_type,
            "hops":       hops,
            # Preserve first_seen from existing record if the node is known
            "first_seen": _nodes.get(hash_hex, {}).get("first_seen", now),
            "last_seen":  now,
        }
        _nodes[hash_hex] = node

        # SQLite writes happen in background threads to avoid blocking the
        # RNS announce thread
        threading.Thread(target=db_upsert_node,    args=(dict(node),), daemon=True).start()
        threading.Thread(target=db_record_activity, args=(app_type,),  daemon=True).start()

        event = {"type": "announce", "node": dict(node), "ts": now}
        loop_ok = _loop is not None and _loop.is_running()
        print("[rns-map] #{} {} \"{}\" hops={} ws={}".format(
            _announce_count, app_type, name, hops, len(_ws_clients)), flush=True)

        if loop_ok:
            # Thread-safe bridge from RNS thread into the asyncio event loop
            fut = asyncio.run_coroutine_threadsafe(_broadcast(event), _loop)
            try:
                fut.result(timeout=2)
            except Exception as e:
                print("[rns-map] broadcast error: {}".format(e), flush=True)

    except Exception as e:
        print("[rns-map] _process error: {}".format(e), flush=True)

# ---------------------------------------------------------------------------
# Announce handlers (one per application aspect)
# ---------------------------------------------------------------------------

class _LXMFDeliveryHandler:
    """Handles LXMF message delivery destination announces."""
    aspect_filter = "lxmf.delivery"
    def received_announce(self, destination_hash, announced_identity, app_data, **kwargs):
        _process("lxmf", destination_hash, announced_identity, app_data, kwargs)

class _LXMFPropHandler:
    """Handles LXMF propagation node announces."""
    aspect_filter = "lxmf.propagation"
    def received_announce(self, destination_hash, announced_identity, app_data, **kwargs):
        _process("propagation", destination_hash, announced_identity, app_data, kwargs)

class _NomadHandler:
    """Handles Nomadnet node announces."""
    aspect_filter = "nomadnetwork.node"
    def received_announce(self, destination_hash, announced_identity, app_data, **kwargs):
        _process("nomadnet", destination_hash, announced_identity, app_data, kwargs)

class _AudioHandler:
    """Handles audio call destination announces."""
    aspect_filter = "call.audio"
    def received_announce(self, destination_hash, announced_identity, app_data, **kwargs):
        _process("audio", destination_hash, announced_identity, app_data, kwargs)

# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------

async def _broadcast(event: dict):
    """
    Send a JSON event to all connected WebSocket clients.
    Removes clients that have disconnected or errored.
    Must be called from within the asyncio event loop.
    """
    global _ws_clients
    if not _ws_clients:
        return
    msg  = json.dumps(event)
    dead = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_str(msg)
        except Exception as e:
            print("[rns-map] ws send error: {}".format(e), flush=True)
            dead.add(ws)
    _ws_clients -= dead

# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def handle_ws(request):
    """
    WebSocket endpoint. On connect, immediately sends a full state snapshot
    of all known nodes, then streams announce events as they arrive.
    """
    global _ws_clients
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    _ws_clients.add(ws)
    print("[rns-map] WS connected, total={}".format(len(_ws_clients)), flush=True)
    try:
        # Send current node state to the newly connected client
        await ws.send_str(json.dumps({
            "type":  "state",
            "nodes": list(_nodes.values()),
        }))
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        _ws_clients.discard(ws)
        print("[rns-map] WS disconnected, total={}".format(len(_ws_clients)), flush=True)
    return ws

async def handle_index(request):
    """Serve the main UI page."""
    return web.FileResponse(STATIC_DIR / "index.html")

async def handle_activity(request):
    """Return persisted activity buckets as JSON for the activity graph."""
    data = await asyncio.get_event_loop().run_in_executor(None, db_get_activity)
    return web.Response(
        text=json.dumps(data),
        content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )

async def handle_reset(request):
    """
    Wipe the nodes table, clear the in-memory node dict, and broadcast
    a reset event to all connected WebSocket clients.
    """
    global _nodes
    _nodes = {}
    await asyncio.get_event_loop().run_in_executor(None, db_reset_nodes)
    await _broadcast({"type": "reset"})
    print("[rns-map] Node DB reset by user request", flush=True)
    return web.Response(text='{"ok":true}', content_type="application/json")

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main():
    global _loop
    _loop = asyncio.get_running_loop()

    db_init()
    db_load()
    print("[rns-map] Loaded {} nodes from DB".format(len(_nodes)), flush=True)

    # Attach to the running rnsd as a shared-instance client.
    # RNS.Reticulum() with no arguments auto-discovers the rnsd socket.
    # rnsd must already be running before this line executes.
    RNS.Reticulum()
    for handler in (_LXMFDeliveryHandler(), _LXMFPropHandler(),
                    _NomadHandler(), _AudioHandler()):
        RNS.Transport.register_announce_handler(handler)
    print("[rns-map] Announce handlers registered", flush=True)

    app = web.Application()
    app.router.add_get ("/",         handle_index)
    app.router.add_get ("/ws",       handle_ws)
    app.router.add_get ("/activity", handle_activity)
    app.router.add_post("/reset",    handle_reset)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print("[rns-map] Serving on http://0.0.0.0:{}".format(PORT), flush=True)

    # Run forever until interrupted
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
