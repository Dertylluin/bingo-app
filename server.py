import asyncio
import websockets
import json
import time
import os
import redis

# =========================
# CONFIG
# =========================
PORT = int(os.environ["PORT"])
REDIS_URL = os.environ["REDIS_URL"]

r = redis.from_url(REDIS_URL, decode_responses=True)

PING_INTERVAL = 20
TIMEOUT = 40

print(f"🚀 WS server running on {PORT}")

# =========================
# REDIS HELPERS
# =========================
def get_room(room):
    data = r.get(f"room:{room}")
    return json.loads(data) if data else {
        "players": {},
        "start_time": time.time()
    }

def save_room(room, data):
    r.set(f"room:{room}", json.dumps(data))


# =========================
# PLAYER HELPERS
# =========================
def add_player(room_name, username):
    room = get_room(room_name)

    username = username.strip().lower()

    # reconexión
    for pid, p in room["players"].items():
        if p["username"] == username:
            return pid, room

    pid = f"p{len(room['players']) + 1}"

    room["players"][pid] = {
        "username": username,
        "tasks": [],
        "selected": [],
        "score": 0,
        "bingo": False,
        "online": True,
        "last_ping": time.time()
    }

    save_room(room_name, room)
    return pid, room


# =========================
# RANKING
# =========================
def get_ranking(room):
    players = list(room["players"].values())

    players.sort(key=lambda p: (
        p["score"],
        len(p["selected"])
    ), reverse=True)

    return [
        {
            "player": p["username"],
            "score": p["score"],
            "bingo": p["bingo"],
            "online": p.get("online", True)
        }
        for p in players
    ]


# =========================
# BROADCAST
# =========================
async def broadcast(room_name, sockets):
    room = get_room(room_name)

    message = {
        "type": "update",
        "players": [
            {"id": pid, "username": p["username"], "score": p["score"]}
            for pid, p in room["players"].items()
        ],
        "ranking": get_ranking(room)
    }

    dead = []

    for ws in sockets.get(room_name, []):
        try:
            await ws.send(json.dumps(message))
        except:
            dead.append(ws)

    for ws in dead:
        sockets[room_name].remove(ws)


# =========================
# HEARTBEAT
# =========================
async def heartbeat(sockets):
    while True:
        for room_name, ws_list in sockets.items():
            for ws in list(ws_list):
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except:
                    ws_list.remove(ws)

        await asyncio.sleep(PING_INTERVAL)


# =========================
# COUNT LINES
# =========================
def count_lines(selected, size):
    selected = set(selected)
    completed = set()

    for r in range(size):
        if all(r * size + c in selected for c in range(size)):
            completed.add(("row", r))

    for c in range(size):
        if all(r * size + c in selected for r in range(size)):
            completed.add(("col", c))

    return completed


# =========================
# HANDLER
# =========================
async def handler(websocket, path=None):
    room_name = None
    player_id = None

    sockets = handler.sockets

    try:
        async for msg in websocket:
            data = json.loads(msg)
            action = data.get("type")

            # ---------------- CREATE ROOM
            if action == "create_room":
                room_name = data["room"].lower().strip()
                username = data["username"]

                player_id, room = add_player(room_name, username)

                sockets.setdefault(room_name, []).append(websocket)

                await websocket.send(json.dumps({
                    "type": "joined",
                    "room": room_name,
                    "player": player_id,
                    "players": room["players"]
                }))

            # ---------------- JOIN ROOM
            elif action == "join_room":
                room_name = data["room"].lower().strip()
                username = data["username"]

                player_id, room = add_player(room_name, username)

                sockets.setdefault(room_name, []).append(websocket)

                await websocket.send(json.dumps({
                    "type": "joined",
                    "room": room_name,
                    "player": player_id,
                    "players": room["players"]
                }))

            # ---------------- SET TASKS
            elif action == "set_tasks":
                room = get_room(data["room"])
                player = room["players"][data["player"]]

                player["tasks"] = data["tasks"]
                player["selected"] = []
                player["score"] = 0

                save_room(data["room"], room)

            # ---------------- SELECT
            elif action == "select":
                room = get_room(data["room"])
                player = room["players"][data["player"]]

                idx = data["index"]

                if idx in player["selected"]:
                    player["selected"].remove(idx)
                else:
                    player["selected"].append(idx)

                size = int(len(player["tasks"]) ** 0.5)
                completed = count_lines(player["selected"], size)

                player["score"] = len(player["selected"]) + len(completed) * 2

                save_room(data["room"], room)

                await broadcast(data["room"], sockets)

            # ---------------- PONG
            elif action == "pong":
                pass

    except Exception as e:
        print("❌ Error:", e)

    finally:
        if room_name and room_name in sockets:
            if websocket in sockets[room_name]:
                sockets[room_name].remove(websocket)


# sockets global
handler.sockets = {}


# =========================
# MAIN
# =========================
async def main():
    server = await websockets.serve(
        handler,
        "0.0.0.0",
        PORT,
        ping_interval=PING_INTERVAL,
        ping_timeout=TIMEOUT
    )

    print("✅ Server ready")

    asyncio.create_task(heartbeat(handler.sockets))

    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
