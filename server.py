import asyncio
import websockets
import json
import time
import asyncio
import os

# -----------------------------
# MAIN
# -----------------------------
async def main():
    port = int(os.environ.get("PORT", 8080))

    print(f"🚀 WS server running on {port}")

    server = await websockets.serve(
        handler,
        "0.0.0.0",
        port,
        ping_interval=PING_INTERVAL,
        ping_timeout=TIMEOUT
    )

    asyncio.create_task(heartbeat())
    asyncio.create_task(save_snapshot())

    await server.wait_closed()

# -----------------------------
# ESTADO GLOBAL
# -----------------------------
rooms = {}

PING_INTERVAL = 20
TIMEOUT = 40


# -----------------------------
# SALA
# -----------------------------
def create_room(room_name):
    room_name = room_name.lower().strip()

    if room_name in rooms:
        return None

    rooms[room_name] = {
        "players": {},
        "start_time": time.time(),
        "winner": None
    }

    return room_name


# -----------------------------
# JUGADORES
# -----------------------------
def add_player(room_name, websocket, username):
    room = rooms[room_name]
    username_clean = username.strip().lower()

    # reconexión
    for pid, p in room["players"].items():
        if p["username"].lower() == username_clean:
            p["ws"] = websocket
            p["online"] = True
            p["last_ping"] = time.time()
            print(f"🔄 Reconectado: {username_clean}")
            return pid

    # nuevo jugador
    pid = f"p{len(room['players']) + 1}"

    room["players"][pid] = {
        "username": username_clean,
        "ws": websocket,
        "tasks": [],
        "selected": [],
        "score": 0,
        "bingo": False,
        "online": True,
        "last_ping": time.time()
    }

    print(f"➕ Nuevo jugador: {username_clean}")
    return pid


# -----------------------------
# LÍNEAS
# -----------------------------
def count_lines(selected, size):
    completed = set()

    # horizontales
    for r in range(size):
        if all(r * size + c in selected for c in range(size)):
            completed.add(("row", r))

    # verticales
    for c in range(size):
        if all(r * size + c in selected for r in range(size)):
            completed.add(("col", c))

    return completed
# -----------------------------
# HELPERS
# -----------------------------
def get_players(room):
    return [
        {
            "id": pid,
            "username": p["username"],
            "score": p["score"],
            "bingo": p["bingo"],
            "online": p.get("online", True)
        }
        for pid, p in room["players"].items()
    ]


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


# -----------------------------
# BROADCAST (FIABLE)
# -----------------------------
async def broadcast(room):
    message = {
        "type": "update",
        "players": get_players(room),
        "ranking": get_ranking(room)
    }

    dead = []

    for pid, p in room["players"].items():
        try:
            ws = p.get("ws")
            if ws:
                await ws.send(json.dumps(message))
        except:
            dead.append(pid)

    for pid in dead:
        if pid in room["players"]:
            room["players"][pid]["online"] = False


# -----------------------------
# HEARTBEAT
# -----------------------------
async def heartbeat():
    while True:
        for room in rooms.values():
            for p in room["players"].values():
                try:
                    await p["ws"].send(json.dumps({"type": "ping"}))
                except:
                    p["online"] = False

        await asyncio.sleep(PING_INTERVAL)


# -----------------------------
# SNAPSHOT (FUTURO DB)
# -----------------------------
async def save_snapshot():
    while True:
        for room_name, room in rooms.items():
            snapshot = {
                "room": room_name,
                "players": get_players(room),
                "ranking": get_ranking(room),
                "time": time.time()
            }

        await asyncio.sleep(10)


# -----------------------------
# HANDLER
# -----------------------------
async def handler(websocket):
    room_name = None
    player_id = None

    try:
        async for msg in websocket:
            data = json.loads(msg)
            action = data.get("type")

            # CREATE ROOM
            if action == "create_room":
                room_name = create_room(data["room"])
                username = data["username"]

                if not room_name:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Sala existe"
                    }))
                    continue

                player_id = add_player(room_name, websocket, username)

                await websocket.send(json.dumps({
                    "type": "joined",
                    "room": room_name,
                    "player": player_id,
                    "players": get_players(rooms[room_name])
                }))

                await broadcast(rooms[room_name])

            # JOIN ROOM
            elif action == "join_room":
                room_name = data["room"].lower().strip()
                username = data["username"]

                if room_name not in rooms:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No existe sala"
                    }))
                    continue

                player_id = add_player(room_name, websocket, username)

                await websocket.send(json.dumps({
                    "type": "joined",
                    "room": room_name,
                    "player": player_id,
                    "players": get_players(rooms[room_name])
                }))

                await broadcast(rooms[room_name])

            # SET TASKS
            elif action == "set_tasks":
                room = rooms[data["room"]]
                player = room["players"][data["player"]]

                player["tasks"] = data["tasks"]
                player["selected"] = set()
                player["score"] = 0
                player["completed_lines"] = set()

                await websocket.send(json.dumps({"type": "tasks_saved"}))
                await broadcast(room)

            # SELECT
            elif action == "select":
                room = rooms[data["room"]]
                player = room["players"][data["player"]]

                idx = data["index"]

                if idx in player["selected"]:
                    player["selected"].remove(idx)
                else:
                    player["selected"].add(idx)

                size = int(len(player["tasks"]) ** 0.5)

                completed_now = count_lines(
                player["selected"],
                size
                )   

                elapsed = time.time() - room["start_time"]

                score = len(player["selected"])

                for line in completed_now:

                    if elapsed < 1800:       # < 30 min
                        score += 5

                    elif elapsed < 3600:     # 30-60 min
                        score += 2

                    else:                    # > 60 min
                        score += 1

                player["score"] = score

                await broadcast(room)
            # PONG
            elif action == "pong":
                if room_name and player_id:
                    rooms[room_name]["players"][player_id]["last_ping"] = time.time()

    except Exception as e:
        print("❌ Error:", e)

    finally:
        if room_name and room_name in rooms and player_id:
            rooms[room_name]["players"].pop(player_id, None)
            print(f"🔌 desconectado {player_id}")





if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    asyncio.run(main())
    
