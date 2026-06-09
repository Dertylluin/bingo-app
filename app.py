import flet as ft
import json
import os
import threading
import time

SERVER = "wss://robust-ambition-production-0220.up.railway.app"
print(f"Conectando a: {SERVER}")

C_BG        = "#0f0f1a"   
C_SURFACE   = "#1a1a2e"   
C_PRIMARY   = "#7c3aed"   
C_ACCENT    = "#f59e0b"   
C_SUCCESS   = "#10b981"   
C_NEUTRAL   = "#2d2d4e"   
C_TEXT      = "#f1f5f9"   
C_MUTED     = "#64748b"   
C_ERROR     = "#ef4444" 


def card(content, padding=15, bgcolor=C_SURFACE, radius=16):
    return ft.Container(
        content=content,
        bgcolor=bgcolor,
        border_radius=radius,
        padding=padding,
    )


def main(page: ft.Page):
    page.title = "🎓 Bingo de la Graduacion"
    page.bgcolor = C_BG
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 16

    import asyncio
    import websockets
    import uuid

    # ── Estado ────────────────────────────────────────────────────────────────
    state = {
        "ws": None,
        "room": None,
        "player": None,
        "username": "",
        "tasks": [],
        "selected": set(),
        "size": 3,
        "connected": False,
        "loop": None,
        "cells": {},
        "client_id": None,
    }

    # ── Refs de UI ────────────────────────────────────────────────────────────
    timer_text   = ft.Text("⏱ 0s", size=16, color=C_ACCENT)
    status_icon  = ft.Text("●", size=18, color=C_ERROR)
    status_label = ft.Text("Sin conexion", size=14, color=C_MUTED)
    refresh_btn  = ft.FilledButton("🔄 Recargar", on_click=lambda e: page.update())

    ranking_col  = ft.ListView(spacing=6, auto_scroll=False, expand=True)
    players_col  = ft.Column(spacing=4)
    grid_col     = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
    )
    board_inputs = ft.Column(spacing=8)

    username_tf = ft.TextField(
        label="Tu nombre", border_color=C_PRIMARY,
        focused_border_color=C_ACCENT, color=C_TEXT,
        bgcolor=C_NEUTRAL, border_radius=12,
    )
    room_tf = ft.TextField(
        label="Codigo de sala", border_color=C_PRIMARY,
        focused_border_color=C_ACCENT, color=C_TEXT,
        bgcolor=C_NEUTRAL, border_radius=12,
        capitalization=ft.TextCapitalization.CHARACTERS,
    )
    new_room_tf = ft.TextField(
        label="Nombre nueva sala", border_color=C_PRIMARY,
        focused_border_color=C_ACCENT, color=C_TEXT,
        bgcolor=C_NEUTRAL, border_radius=12,
        capitalization=ft.TextCapitalization.CHARACTERS,
    )
    size_dd = ft.Dropdown(
        label="Tamano carton",
        options=[ft.dropdown.Option(str(i), f"{i}x{i} ({i*i} casillas)") for i in range(2, 11)],
        value="3",
        border_color=C_PRIMARY, focused_border_color=C_ACCENT,
        color=C_TEXT, bgcolor=C_NEUTRAL, border_radius=12,
    )

    snack_bar = ft.SnackBar(content=ft.Text(""), bgcolor=C_ERROR)
    page.overlay.append(snack_bar)

    # ── Notificaciones ────────────────────────────────────────────────────────
    def show_error(msg: str):
        snack_bar.content = ft.Text(msg, color=C_TEXT)
        snack_bar.bgcolor = C_ERROR
        snack_bar.open = True
        page.update()

    def show_info(msg: str):
        snack_bar.content = ft.Text(msg, color=C_TEXT)
        snack_bar.bgcolor = C_PRIMARY
        snack_bar.open = True
        page.update()

    def set_status(icon_color: str, label: str):
        status_icon.color  = icon_color
        status_label.value = label
        page.update()

    # ── Botones ───────────────────────────────────────────────────────────────
    def primary_btn(text, on_click):
        return ft.FilledButton(
            content=ft.Text(text, color=C_TEXT, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12), padding=15
            ),
            on_click=on_click,
        )

    def secondary_btn(text, on_click, expand=False):
        return ft.OutlinedButton(
            content=ft.Text(text, color=C_PRIMARY, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                side=ft.BorderSide(2, C_PRIMARY), padding=15,
            ),
            on_click=on_click,
            expand=expand,
        )

    # ── Hilo de red dedicado ──────────────────────────────────────────────────
    def start_network_thread():
        loop = asyncio.new_event_loop()
        state["loop"] = loop
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

    start_network_thread()

    def run_async_network(coro):
        if state["loop"]:
            asyncio.run_coroutine_threadsafe(coro, state["loop"])

    # ── Red ───────────────────────────────────────────────────────────────────
    async def network_listen_loop():
        try:
            async for raw in state["ws"]:
                handle_message(json.loads(raw))
        except websockets.exceptions.ConnectionClosed:
            state["connected"] = False
            set_status(C_ERROR, "Conexion perdida")
        except Exception as ex:
            set_status(C_ERROR, f"Error de red: {ex}")

    async def connect_and_send_ws(payload: dict):
        if state["ws"]:
            try:
                await state["ws"].close()
            except Exception:
                pass
        try:
            state["ws"] = await websockets.connect(
                SERVER, ping_interval=20, ping_timeout=10
            )
            state["connected"] = True
            # Lanzar el loop de escucha en el mismo hilo de red
            state["loop"].create_task(network_listen_loop())
            await state["ws"].send(json.dumps(payload))
        except Exception as ex:
            set_status(C_ERROR, f"No se pudo conectar: {ex}")

    async def send_payload_ws(payload: dict):
        if state["ws"] and state["connected"]:
            try:
                await state["ws"].send(json.dumps(payload))
            except Exception as ex:
                show_error(f"Error al enviar: {ex}")

    # ── Persistencia de sesion ────────────────────────────────────────────────
    # FIX PRINCIPAL: guardamos client_id + datos de sesion en shared_preferences
    async def persist_session():
        """Guarda el estado actual de sesion para sobrevivir F5."""
        await page.shared_preferences.set("client_id",  state["client_id"] or "")
        await page.shared_preferences.set("s_room",     state["room"]      or "")
        await page.shared_preferences.set("s_player",   state["player"]    or "")
        await page.shared_preferences.set("s_username", state["username"]  or "")

    async def load_and_reconnect():
        """
        Se llama UNA vez al arrancar la pagina.
        1. Carga (o genera) el client_id persistido.
        2. Intenta reconectar al servidor con ese client_id.
        """
        # -- Cargar / crear client_id ------------------------------------------
        cid = await page.shared_preferences.get("client_id")
        if not cid:
            cid = str(uuid.uuid4())
            await page.shared_preferences.set("client_id", cid)
        state["client_id"] = cid

        # -- Restaurar datos de sesion locales ---------------------------------
        state["room"]     = await page.shared_preferences.get("s_room")     or None
        state["player"]   = await page.shared_preferences.get("s_player")   or None
        state["username"] = await page.shared_preferences.get("s_username") or ""

        if state["username"]:
            username_tf.value = state["username"]
            page.update()

        print(f"[INIT] client_id={cid}  room={state['room']}  player={state['player']}")

        # -- Intentar reconexion al servidor -----------------------------------
        # Solo tiene sentido si el servidor aun tiene la sala en memoria
        run_async_network(
            connect_and_send_ws({
                "type": "reconnect",
                "client_id": cid,
            })
        )

    # ── Procesador de mensajes ────────────────────────────────────────────────
    def handle_message(data: dict):
        print("MSG:", data.get("type"), data)
        t = data.get("type")

        if t == "joined":
            state["room"]   = data["room"]
            state["player"] = data["player"]
            if data.get("client_id"):
                state["client_id"] = data["client_id"]
            # Persistir sesion cada vez que (re)entramos a una sala
            run_async_network(persist_session())
            set_status(C_SUCCESS, f"Sala: {data['room'].upper()}")
            show_info(f"Unido a la sala {data['room'].upper()}")

        elif t == "update":
            update_players(data.get("players", []))
            update_ranking(data.get("ranking", []))
            selected_map = data.get("selected", {})
            my_selected  = selected_map.get(state["player"], [])
            state["selected"] = set(my_selected)
            if state.get("tasks"):
                build_game(state["tasks"])
            # Actualizar timer
            timer_text.value = f"{data.get('time', 0)}s"
            page.update()

        elif t == "error":
            show_error(data.get("message", data.get("msg", "Error del servidor")))

        elif t == "reconnected":
            # El servidor nos reconocio: restaurar estado completo
            state["room"]     = data["room"]
            state["player"]   = data["player"]
            state["selected"] = set(data.get("selected", []))
            state["size"]     = data.get("size") or state["size"]
            state["tasks"]    = data.get("tasks") or []

            # Persistir por si acaso
            run_async_network(persist_session())

            set_status(C_SUCCESS, f"Sala: {state['room'].upper()} (reconectado)")

            if state["tasks"]:
                build_game(state["tasks"])
            else:
                show_info("Reconectado. Vuelve a activar tu carton.")

        elif t == "tasks_saved":
            show_info("Carton activado en el servidor!")

    # ── Actualizar UI ─────────────────────────────────────────────────────────
    def update_ranking(ranking: list):
        ranking_col.controls.clear()
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(ranking):
            name    = r.get("player", "?")
            score   = r.get("score", 0)
            is_me   = name == state["username"].lower()
            medal   = medals[i] if i < 3 else f"{i+1}."
            ranking_col.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(medal, size=20, weight=ft.FontWeight.BOLD,
                                color=C_ACCENT),
                        ft.Column([
                            ft.Text(
                                name, size=15,
                                weight=ft.FontWeight.BOLD if is_me else ft.FontWeight.NORMAL,
                                color=C_ACCENT if is_me else C_TEXT,
                            ),
                            ft.Text(f"{score} pts", size=11, color=C_MUTED),
                        ], expand=True),
                        ft.Text(f"{score} pts", size=16,
                                weight=ft.FontWeight.BOLD, color=C_SUCCESS),
                    ]),
                    bgcolor=C_PRIMARY + "33" if is_me else C_NEUTRAL,
                    border_radius=12, padding=12,
                    border=ft.Border.all(2, C_ACCENT) if is_me else None,
                )
            )
        page.update()

    def update_players(players: list):
        players_col.controls.clear()
        for p in players:
            name = p.get("player", p) if isinstance(p, dict) else p
            players_col.controls.append(
                ft.Text(f"- 👤{name}", size=13, color=C_TEXT)
            )
        page.update()

    # ── Acciones de UI ────────────────────────────────────────────────────────
    def build_board(e):
        state["size"] = int(size_dd.value)
        board_inputs.controls.clear()
        for i in range(state["size"] ** 2):
            board_inputs.controls.append(
                ft.TextField(
                    label=f"Casilla {i+1}",
                    border_color=C_PRIMARY, focused_border_color=C_ACCENT,
                    color=C_TEXT, bgcolor=C_NEUTRAL, border_radius=10,
                )
            )
        page.update()

    async def save_template(e):
        if not board_inputs.controls:
            show_error("Primero genera un carton."); return
        tasks = [c.value or "" for c in board_inputs.controls if isinstance(c, ft.TextField)]
        await page.shared_preferences.set(
            "bingo_template",
            json.dumps({"size": str(state["size"]), "tasks": tasks}),
        )
        show_info("Plantilla guardada")

    async def load_template(e):
        raw = await page.shared_preferences.get("bingo_template")
        if not raw:
            show_error("No hay plantilla guardada"); return
        data = json.loads(raw)
        if "tasks" not in data:
            show_error("Plantilla invalida"); return
        size_dd.value = str(data.get("size", "3"))
        state["size"] = int(size_dd.value)
        board_inputs.controls.clear()
        for i, task in enumerate(data["tasks"]):
            board_inputs.controls.append(
                ft.TextField(
                    value=task, label=f"Casilla {i+1}", dense=True,
                    border_color=C_PRIMARY, focused_border_color=C_ACCENT,
                    color=C_TEXT, bgcolor=C_NEUTRAL, border_radius=10,
                )
            )
        page.update()
        show_info("Plantilla cargada")

    def update_cell(index: int, selected: bool):
        cell = state["cells"].get(index)
        if not cell: return
        cell.bgcolor = C_SUCCESS if selected else C_NEUTRAL
        cell.border  = ft.Border.all(2, C_SUCCESS) if selected else ft.Border.all(1, C_PRIMARY + "55")
        page.update()

    # ── Clicks de red ─────────────────────────────────────────────────────────
    def click_create_room(e):
        uname = username_tf.value.strip()
        rname = new_room_tf.value.strip()
        if not uname or not rname:
            show_error("Escribe tu nombre y el nombre de sala."); return
        state["username"] = uname
        run_async_network(connect_and_send_ws({
            "type": "create_room", "room": rname,
            "username": uname, "client_id": state["client_id"],
        }))

    def click_join_room(e):
        uname = username_tf.value.strip()
        rname = room_tf.value.strip()
        if not uname or not rname:
            show_error("Escribe tu nombre y el codigo de sala."); return
        state["username"] = uname
        run_async_network(connect_and_send_ws({
            "type": "join_room", "room": rname,
            "username": uname, "client_id": state["client_id"],
        }))

    def click_send_tasks(e):
        if not state["ws"] or not state["connected"]:
            show_error("No estas conectado."); return
        if not board_inputs.controls:
            show_error("Genera o carga casillas primero."); return
        tasks = [
            (t.value.strip() if t.value and t.value.strip() else f"Casilla {i+1}")
            for i, t in enumerate(board_inputs.controls)
        ]
        state["tasks"]    = tasks
        state["selected"] = set()
        run_async_network(send_payload_ws({
            "type": "set_tasks", "room": state["room"],
            "player": state["player"], "tasks": tasks, "size": state["size"],
        }))
        build_game(tasks)

    # ── Tablero visual ────────────────────────────────────────────────────────
    def build_game(tasks: list):
        if not tasks: return
        grid_col.controls.clear()
        state["cells"] = {}
        size      = state["size"]
        cell_size = max(75, min(100, (page.width or 360) // size - 10))

        for r in range(size):
            row_cells = []
            for c in range(size):
                idx    = r * size + c
                if idx >= len(tasks): break
                label  = tasks[idx]
                is_sel = idx in state["selected"]
                cell   = ft.Container(
                    content=ft.Text(
                        label, text_align=ft.TextAlign.CENTER,
                        size=10, weight=ft.FontWeight.W_500,
                        color=C_TEXT, max_lines=4,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    width=cell_size, height=cell_size,
                    bgcolor=C_SUCCESS if is_sel else C_NEUTRAL,
                    border_radius=10, alignment=ft.Alignment(0, 0), padding=5,
                    border=ft.Border.all(2, C_SUCCESS) if is_sel else ft.Border.all(1, C_PRIMARY + "55"),
                )
                state["cells"][idx] = cell

                def make_toggle(index):
                    def toggle_click(ev):
                        if index in state["selected"]:
                            state["selected"].discard(index)
                            update_cell(index, False)
                        else:
                            state["selected"].add(index)
                            update_cell(index, True)
                        run_async_network(send_payload_ws({
                            "type": "select", "room": state["room"],
                            "player": state["player"], "index": index,
                        }))
                    return toggle_click

                cell.on_click = make_toggle(idx)
                row_cells.append(cell)
            grid_col.controls.append(
                ft.Row(row_cells, alignment=ft.MainAxisAlignment.CENTER, spacing=6)
            )
        page.update()

    # ── Layout ────────────────────────────────────────────────────────────────
    page.add(
        ft.ListView(
            expand=True, spacing=14, padding=30,
            controls=[
                card(ft.Column([
                    ft.Text("BINGO", size=32, weight=ft.FontWeight.BOLD,
                            color=C_ACCENT, text_align=ft.TextAlign.CENTER),
                    ft.Text("de Graduacion", size=16, color=C_MUTED,
                            text_align=ft.TextAlign.CENTER),
                    ft.Divider(color=C_PRIMARY + "55"),
                    ft.Row([status_icon, status_label, timer_text, refresh_btn], spacing=8),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6), padding=20),

                card(ft.Column([
                    ft.Text("1  Tu nombre", size=16,
                            weight=ft.FontWeight.BOLD, color=C_TEXT),
                    username_tf,
                ], spacing=10)),

                card(ft.Column([
                    ft.Text("2  Sala multijugador", size=16,
                            weight=ft.FontWeight.BOLD, color=C_TEXT),
                    ft.Row([ft.Container(new_room_tf, expand=True),
                            primary_btn("Crear", click_create_room)], spacing=10),
                    ft.Row([ft.Container(room_tf, expand=True),
                            secondary_btn("Unirse", click_join_room)], spacing=10),
                    ft.Text("Jugadores conectados:", size=13, color=C_MUTED),
                    players_col,
                ], spacing=10)),

                card(ft.Column([
                    ft.Text("3  Configura tu carton", size=16,
                            weight=ft.FontWeight.BOLD, color=C_TEXT),
                    size_dd,
                    ft.Row([primary_btn("Generar casillas", build_board)],
                           alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([
                        secondary_btn("Guardar plantilla", save_template, expand=True),
                        secondary_btn("Cargar plantilla", load_template, expand=True),
                    ], spacing=10),
                    ft.Divider(color=C_PRIMARY + "33"),
                    board_inputs,
                    ft.Container(height=4),
                    ft.Row([primary_btn("Activar tablero", click_send_tasks)],
                           alignment=ft.MainAxisAlignment.CENTER),
                ], spacing=10)),

                card(ft.Column([
                    ft.Text("Tu carton", size=18, weight=ft.FontWeight.BOLD,
                            color=C_TEXT, text_align=ft.TextAlign.CENTER),
                    ft.Text("Toca las casillas completadas", size=12,
                            color=C_MUTED, text_align=ft.TextAlign.CENTER),
                    ft.Container(
                        content=ft.Column(
                            controls=[ft.Row(controls=[grid_col],
                                            scroll=ft.ScrollMode.AUTO)],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=500,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10), padding=16),

                card(ft.Column([
                    ft.Text("Ranking en vivo", size=18,
                            weight=ft.FontWeight.BOLD, color=C_TEXT),
                    ft.Container(
                        content=ranking_col, height=250,
                        padding=10, border_radius=12, bgcolor=C_SURFACE,
                    ),
                ], spacing=8)),
            ],
        )
    )

    # ── ARRANQUE: cargar client_id y reconectar ───────────────────────────────
    # FIX: usamos page.run_task() para ejecutar código async en el arranque
    # correctamente dentro del contexto de Flet, SIN asyncio.create_task()
    page.run_task(load_and_reconnect)


ft.app(target=main, port=int(os.environ.get("PORT", 8080)), host="0.0.0.0")

