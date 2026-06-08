import asyncio
import websockets
import json
import time
import os

PING_INTERVAL = 20
TIMEOUT = 40

GAME_DURATION = 4 * 60 * 60  # 4 horas

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
        "start_time": time.time(),
        "size": None,  # <-- IMPORTANTE (dinámico)
        "first_line_done": False,
        "first_bingo_done": False
    }

    return name


# -----------------------------
# PLAYER
# -----------------------------
def add_player(room_name, ws, username):
    room = rooms[room_name]
    username = username.strip().lower()

    for pid, p in room["players"].items():
        if p["username"] == username:
            p["ws"] = ws
            return pid

    pid = f"p{len(room['players']) + 1}"

    room["players"][pid] = {
        "username": username,
        "ws": ws,
        "selected": set(),
        "score": 0,
        "lines_awarded": set(),
        "bingo_awarded": False,
        "cells_marked": 0
    }

    return pid


# -----------------------------
# HELPERS
# -----------------------------
def get_lines(size):
    lines = []

    # filas
    for r in range(size):
        lines.append(frozenset(r * size + c for c in range(size)))

    # columnas
    for c in range(size):
        lines.append(frozenset(r * size + c for r in range(size)))

    # diagonales
    lines.append(frozenset(i * (size + 1) for i in range(size)))
    lines.append(frozenset((i + 1) * (size - 1) for i in range(size)))

    return lines


def get_time_factor(start_time):
    elapsed = time.time() - start_time
    factor = 1 - (elapsed / GAME_DURATION)
    return max(0.2, factor)


# -----------------------------
# BROADCAST
# -----------------------------
async def broadcast(room):
    players_list = [
        {
            "player": p["username"],
            "score": p["score"],
            "selected": len(p["selected"])
        }
        for p in room["players"].values()
    ]

    msg = {
        "type": "update",
        "players": players_list,
        "ranking": sorted(players_list, key=lambda x: x["score"], reverse=True),
        "time": int(time.time() - room["start_time"])
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
# HANDLER
# -----------------------------
async def handler(ws):
    room_name = None
    player_id = None

    try:
        async for msg in ws:
            data = json.loads(msg)
            t = data.get("type")

            # ---------------- CREATE ROOM
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

            # ---------------- JOIN ROOM
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

            # ---------------- SET SIZE (IMPORTANTE)
            elif t == "set_tasks":
                room = rooms[room_name]
                room["size"] = int(data["size"])
                print("SIZE RECIBIDO:", room["size"])
            # ---------------- SELECT
            # PUNTUACIONES
            elif t == "select":
                print("SELECT RECIBIDO:", data)
                print("SELECT RECIBIDO:", data)
                CELL_POINTS = 100
                LINE_POINTS = 500
                FIRST_LINE_BONUS = 500
                BINGO_POINTS = 2000
                FIRST_BINGO_BONUS = 2000

                room = rooms[room_name]
                player = room["players"][player_id]

                idx = data["index"]

                # -----------------------------
                # TIEMPO ACTUAL
                # -----------------------------
                time_factor = get_time_factor(room["start_time"])
                multiplier = 1 + time_factor

                # -----------------------------
                # TOGGLE CASILLA
                # -----------------------------
                if idx in player["selected"]:
                    player["selected"].remove(idx)

                else:
                    player["selected"].add(idx)

                    earned = int(CELL_POINTS * multiplier)
                    player["score"] += earned

                # -----------------------------
                # TAMAÑO
                # -----------------------------
                size = room.get("size") or 3

                # -----------------------------
                # LÍNEAS
                # SOLO FILAS Y COLUMNAS
                # -----------------------------
                lines = []

                for r in range(size):
                    lines.append(
                        frozenset(r * size + c for c in range(size))
                    )

                for c in range(size):
                    lines.append(
                        frozenset(r * size + c for r in range(size))
                    )

                # -----------------------------
                # NUEVAS LÍNEAS
                # -----------------------------
                for i, line in enumerate(lines):

                    if (
                        line.issubset(player["selected"])
                        and i not in player["lines_awarded"]
                    ):

                        earned = int(LINE_POINTS * multiplier)

                        player["score"] += earned

                        player["lines_awarded"].add(i)

                        # primer jugador global
                        if not room["first_line_done"]:

                            earned = int(FIRST_LINE_BONUS * multiplier)

                            player["score"] += earned

                            room["first_line_done"] = True

                # -----------------------------
                # BINGO
                # -----------------------------
                all_cells = set(range(size * size))

                if (
                    all_cells.issubset(player["selected"])
                    and not player["bingo_awarded"]
                ):

                    earned = int(BINGO_POINTS * multiplier)

                    player["score"] += earned

                    if not room["first_bingo_done"]:

                        earned = int(FIRST_BINGO_BONUS * multiplier)

                        player["score"] += earned

                        room["first_bingo_done"] = True

                    player["bingo_awarded"] = True
                    print("BINGO AWARD:", player["bingo_awarded"])
                print("PLAYER DESPUES:", player["score"])
                await broadcast(room)

    except Exception as e:
        print("ERROR:", e)

    finally:
        if room_name and room_name in rooms:
            rooms[room_name]["players"].pop(player_id, None)


# -----------------------------
# START SERVER
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
