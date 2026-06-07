import asyncio
import websockets
import json
import time
import os

PING_INTERVAL = 20
TIMEOUT = 40

# -----------------------------
# ESTADO EN MEMORIA
# -----------------------------
rooms = {}

# -----------------------------
# ROOM
# -----------------------------
def create_room(name):
    name = name.lower().strip()

    if name in rooms:
        return None

    rooms[name] = {
        "players": {},
        "start_time": time.time()
    }

    return name


# -----------------------------
# PLAYER
# -----------------------------
def add_player(room_name, ws, username):
    room = rooms[room_name]
    username = username.strip().lower()

    # reconexión simple
    for pid, p in room["players"].items():
        if p["username"] == username:
            p["ws"] = ws
            return pid

    pid = f"p{len(room['players']) + 1}"

    room["players"][pid] = {
        "username": username,
        "ws": ws,
        "selected": set(),
        "score": 0
    }

    return pid


# -----------------------------
# BROADCAST SEGURO
# -----------------------------
async def broadcast(room):
    msg = {
        "type": "update",
        "players": [
            {
                "username": p["username"],
                "score": p["score"]
            }
            for p in room["players"].values()
        ]
    }

    dead = []

    for pid, p in room["players"].items():
        try:
            await p["ws"].send(json.dumps(msg))
        except:
            dead.append(pid)

    for pid in dead:
        room["players"].pop(pid, None)


# -----------------------------
# HANDLER WS
# -----------------------------
async def handler(ws):
    room_name = None
    player_id = None

    try:
        async for msg in ws:
            data = json.loads(msg)
            t = data.get("type")

            # CREAR SALA
            if t == "create_room":
                room_name = create_room(data["room"])

                if not room_name:
                    await ws.send(json.dumps({"type": "error", "msg": "room exists"}))
                    continue

                player_id = add_player(room_name, ws, data["username"])

                await ws.send(json.dumps({
                    "type": "joined",
                    "room": room_name,
                    "player": player_id
                }))

                await broadcast(rooms[room_name])

            # UNIRSE
            elif t == "join_room":
                room_name = data["room"].lower().strip()

                if room_name not in rooms:
                    await ws.send(json.dumps({"type": "error", "msg": "room not found"}))
                    continue

                player_id = add_player(room_name, ws, data["username"])

                await ws.send(json.dumps({
                    "type": "joined",
                    "room": room_name,
                    "player": player_id
                }))

                await broadcast(rooms[room_name])

            # SELECCIÓN CASILLA
            elif t == "select":
                room = rooms[room_name]
                player = room["players"][player_id]

                idx = data["index"]

                if idx in player["selected"]:
                    player["selected"].remove(idx)
                else:
                    player["selected"].add(idx)

                player["score"] = len(player["selected"])

                await broadcast(room)

    except Exception as e:
        print("Error:", e)

    finally:
        if room_name and room_name in rooms:
            rooms[room_name]["players"].pop(player_id, None)


# -----------------------------
# START SERVER (RAILWAY SAFE)
# -----------------------------
async def main():
    port = int(os.environ.get("PORT", 8080))

    print(f"🚀 WS server running on {port}")

    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        ping_interval=PING_INTERVAL,
        ping_timeout=TIMEOUT
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
