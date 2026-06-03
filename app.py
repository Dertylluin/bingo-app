import flet as ft
import json
import os
import threading
import time

# ── Servidor de producción o Localhost ──────────────────────────────────────
SERVER = "wss://bingo-app-k1gl.onrender.com"

print(f"Conectando a: {SERVER}")
# ─────────────────────────────────────────────────────────────────────────────

# ── Paleta de colores ─────────────────────────────────────────────────────────
C_BG        = "#0f0f1a"   
C_SURFACE   = "#1a1a2e"   
C_PRIMARY   = "#7c3aed"   
C_ACCENT    = "#f59e0b"   
C_SUCCESS   = "#10b981"   
C_NEUTRAL   = "#2d2d4e"   
C_TEXT      = "#f1f5f9"   
C_MUTED     = "#64748b"   
C_ERROR     = "#ef4444"   
# ─────────────────────────────────────────────────────────────────────────────

def card(content, padding=15, bgcolor=C_SURFACE, radius=16):
    return ft.Container(
        content=content,
        bgcolor=bgcolor,
        border_radius=radius,
        padding=padding,
    )

def main(page: ft.Page):
    page.title = "🎓 Bingo Graduación"
    page.bgcolor = C_BG
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 16

    # Importación local para evitar conflictos en sub-hilos
    import asyncio
    import websockets

    # ── Estado de la aplicación ───────────────────────────────────────────────
    state = {
        "ws": None,
        "room": None,
        "player": None,       
        "username": "",
        "tasks": [],
        "selected": set(),
        "size": 3,
        "connected": False,
        "loop": None  # Aquí guardaremos el bucle de eventos del hilo de red
    }

    # ── Refs de UI ─────────────────────────────────────────────────────────────
    status_icon  = ft.Text("🔴", size=18)
    status_label = ft.Text("Sin conexión", size=14, color=C_MUTED)

    ranking_col  = ft.Column(spacing=6)
    players_col  = ft.Column(spacing=4)
    grid_col     = ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6)
    board_inputs = ft.Column(spacing=8)

    username_tf  = ft.TextField(label="Tu nombre", border_color=C_PRIMARY, focused_border_color=C_ACCENT, color=C_TEXT, bgcolor=C_NEUTRAL, border_radius=12)
    room_tf = ft.TextField(label="Código de sala", border_color=C_PRIMARY, focused_border_color=C_ACCENT, color=C_TEXT, bgcolor=C_NEUTRAL, border_radius=12, capitalization=ft.TextCapitalization.CHARACTERS)
    new_room_tf = ft.TextField(label="Nombre nueva sala", border_color=C_PRIMARY, focused_border_color=C_ACCENT, color=C_TEXT, bgcolor=C_NEUTRAL, border_radius=12, capitalization=ft.TextCapitalization.CHARACTERS)
    
    size_dd = ft.Dropdown(
        label="Tamaño cartón",
        options=[ft.dropdown.Option(str(i), f"{i}×{i} ({i*i} casillas)") for i in range(2, 11)],
        value="3",
        border_color=C_PRIMARY,
        focused_border_color=C_ACCENT,
        color=C_TEXT,
        bgcolor=C_NEUTRAL,
        border_radius=12,
    )

    snack_bar = ft.SnackBar(content=ft.Text(""), bgcolor=C_ERROR)
    page.overlay.append(snack_bar)

    # ── Notificaciones e Interfaz Segura ──────────────────────────────────────
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

    def set_status(icon: str, label: str):
        status_icon.value  = icon
        status_label.value = label
        page.update()

    # ── Botones 100% Estables ────────────────────────────────────────────────
    def primary_btn(btn_text, on_click_func):
        return ft.Button(
            content=ft.Text(btn_text, color=C_TEXT, weight=ft.FontWeight.BOLD),
            bgcolor=C_PRIMARY,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15),
            on_click=on_click_func,
        )

    def secondary_btn(btn_text, on_click_func, expand=False):
        return ft.Button(
            content=ft.Text(btn_text, color=C_PRIMARY, weight=ft.FontWeight.BOLD),
            bgcolor=C_BG,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), side=ft.BorderSide(2, C_PRIMARY), padding=15),
            on_click=on_click_func,
            expand=expand,
        )

    # ── Hilo de Red Dedicado (Evita congelamientos por completo) ─────────────
    def start_network_thread():
        loop = asyncio.new_event_loop()
        state["loop"] = loop
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

    start_network_thread()

    def run_async_network(coro):
        """Envía una tarea al hilo de red independiente de manera segura."""
        if state["loop"]:
            asyncio.run_coroutine_threadsafe(coro, state["loop"])

    # ── Operaciones Asíncronas de Red ─────────────────────────────────────────
    async def network_listen_loop():
        try:
            async for raw in state["ws"]:
                data = json.loads(raw)
                # Procesamos el mensaje redirigiéndolo de vuelta a la UI de Flet
                handle_message(data)
        except websockets.exceptions.ConnectionClosed:
            state["connected"] = False
            set_status("🔴", "Conexión perdida")
        except Exception as e:
            set_status("🔴", f"Error de red: {e}")

    async def connect_and_send_ws(payload: dict):
        if state["ws"]:
            try: await state["ws"].close()
            except: pass
        try:
            state["ws"] = await websockets.connect(SERVER, ping_interval=20, ping_timeout=10)
            state["connected"] = True
            set_status("🟢", f"Conectado como {state['username']}")
            
            # Escucha activa en segundo plano en el hilo de red
            asyncio.create_task(network_listen_loop())
            await state["ws"].send(json.dumps(payload))
        except Exception as ex:
            state["connected"] = False
            set_status("🔴", "Servidor desconectado")
            show_error(f"No se pudo conectar al servidor de Bingo.")

    async def send_payload_ws(payload: dict):
        if state["ws"] and state["connected"]:
            try:
                await state["ws"].send(json.dumps(payload))
            except Exception as ex:
                show_error(f"Error al enviar datos: {ex}")

    # ── Procesador de Mensajes del Servidor ───────────────────────────────────
    def handle_message(data: dict):
        t = data.get("type")

        if t == "room_created":
            state["room"] = data["room"]
            state["player"] = data["player"]      
            state["username"] = data["username"]
            set_status("🏠", f"Sala: {data['room'].upper()}")
            show_info(f"Sala «{data['room'].upper()}» creada con éxito.")

        elif t == "joined":
            state["room"] = data["room"]
            state["player"] = data["player"]      
            set_status("🚪", f"Sala: {data['room'].upper()}")
            show_info(f"Te has unido a la sala «{data['room'].upper()}»")

        elif t == "player_joined":
            update_players(data.get("players", []))
            show_info(f"🎉 {data['player']} entró a la sala")

        elif t == "tasks_saved":
            show_info("✅ ¡Cartón activado en el servidor!")

        elif t == "update":
            if "players" in data:
                update_players(data["players"])
            if "ranking" in data:
                update_ranking(data["ranking"])
                
            winner = data.get("winner")
            if winner:
                if winner == state["username"]:
                    set_status("🏆", "¡BINGO! ¡HAS GANADO!")
                else:
                    set_status("🥇", f"Ganador: {winner}")
            page.update()

        elif t == "error":
            show_error(data.get("message", "Error del servidor"))

    # ── Actualizaciones de UI ─────────────────────────────────────────────────
    def update_ranking(ranking: list):
        ranking_col.controls.clear()
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(ranking):
            is_me = r["player"] == state["username"]
            medal = medals[i] if i < 3 else f"{i+1}."
            bingo_tag = "  🎉 BINGO" if r.get("bingo") else ""
            prog_text = f"{r.get('selected', 0)}/{r.get('total', 0)} casillas"

            ranking_col.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(medal, size=22),
                        ft.Column([
                            ft.Text(r["player"] + bingo_tag, size=15, weight=ft.FontWeight.BOLD if is_me else ft.FontWeight.NORMAL, color=C_ACCENT if is_me else C_TEXT),
                            ft.Text(prog_text, size=11, color=C_MUTED),
                        ], spacing=1, expand=True),
                        ft.Text(f"{r['score']} pts", size=16, weight=ft.FontWeight.BOLD, color=C_SUCCESS),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor=C_PRIMARY + "33" if is_me else C_NEUTRAL,
                    border_radius=12,
                    padding=12,
                    border=ft.Border.all(2, C_ACCENT) if is_me else None,
                )
            )
        page.update()

    def update_players(players: list):
        players_col.controls.clear()
        for p in players:
            players_col.controls.append(ft.Text(f"👤 {p}", size=13, color=C_TEXT))
        page.update()

    # ── Lógica de los Botones (Locales e Inmediatos) ───────────────────────────
    def build_board(e):
        state["size"] = int(size_dd.value)
        board_inputs.controls.clear()
        n = state["size"] ** 2
        for i in range(n):
            board_inputs.controls.append(
                ft.TextField(
                    label=f"Casilla {i + 1}",
                    dense=True,
                    border_color=C_PRIMARY,
                    focused_border_color=C_ACCENT,
                    color=C_TEXT,
                    bgcolor=C_NEUTRAL,
                    border_radius=10,
                )
            )
        page.update()

        # ── Guardar plantilla ─────────────────────────────────────────────
        # ── Guardar plantilla ─────────────────────────────────────────────
    async def save_template(e):
        try:
            if not board_inputs.controls:
                show_error("Primero genera un cartón.")
                return

            tasks = []

            for control in board_inputs.controls:
                if isinstance(control, ft.TextField):
                    tasks.append(control.value or "")

            template_data = {
                "size": str(state["size"]),
                "tasks": tasks
            }

            # Guardado local REAL
            await page.shared_preferences.set(
                "bingo_template",
                json.dumps(template_data)
            )

            show_info("💾 Plantilla guardada correctamente")

        except Exception as ex:
            show_error(f"Error guardando plantilla: {ex}")


    # ── Cargar plantilla ─────────────────────────────────────────────
    async def load_template(e):
        try:
            raw = await page.shared_preferences.get("bingo_template")

            if not raw:
                show_error("No hay plantilla guardada")
                return

            data = json.loads(raw)

            if "tasks" not in data:
                show_error("Plantilla inválida")
                return

            # Restaurar tamaño
            size_value = str(data.get("size", "3"))

            size_dd.value = size_value
            state["size"] = int(size_value)

            # Limpiar casillas anteriores
            board_inputs.controls.clear()

            # Reconstruir tablero
            for i, task in enumerate(data["tasks"]):
                board_inputs.controls.append(
                    ft.TextField(
                        value=task,
                        label=f"Casilla {i+1}",
                        dense=True,
                        border_color=C_PRIMARY,
                        focused_border_color=C_ACCENT,
                        color=C_TEXT,
                        bgcolor=C_NEUTRAL,
                        border_radius=10,
                    )
                )

            page.update()

            show_info("📂 Plantilla cargada correctamente")

        except Exception as ex:
            show_error(f"Error cargando plantilla: {ex}")
    # ── Disparadores de Red Seguros ──────────────────────────────────────────
    def click_create_room(e):
        uname = username_tf.value.strip()
        rname = new_room_tf.value.strip()
        if not uname or not rname:
            show_error("Escribe tu nombre y el nombre de la sala."); return
        state["username"] = uname
        run_async_network(connect_and_send_ws({
            "type": "create_room", "room": rname, "username": uname
        }))

    def click_join_room(e):
        uname = username_tf.value.strip()
        rname = room_tf.value.strip()
        if not uname or not rname:
            show_error("Escribe tu nombre y el código de sala."); return
        state["username"] = uname
        run_async_network(connect_and_send_ws({
            "type": "join_room", "room": rname, "username": uname
        }))

    def click_send_tasks(e):
        if not state["ws"] or not state["connected"]:
            show_error("No estás conectado a ninguna sala online."); return
        if not board_inputs.controls:
            show_error("Genera o carga casillas primero."); return
            
        tasks = [t.value.strip() if (t.value and t.value.strip()) else f"Casilla {i+1}" for i, t in enumerate(board_inputs.controls)]
        state["tasks"] = tasks
        state["selected"] = set()
        
        run_async_network(send_payload_ws({
            "type": "set_tasks", "room": state["room"], "player": state["player"], "tasks": tasks
        }))
        build_game(tasks)

    # ── Generador del Tablero Visual de Bingo ─────────────────────────────────
    def build_game(tasks: list):
        grid_col.controls.clear()
        size = state["size"]
        cell_size = max(75, min(100, (page.width or 360) // size - 10))

        for r in range(size):
            row_cells = []
            for c in range(size):
                idx = r * size + c
                if idx >= len(tasks): break
                label = tasks[idx]
                is_sel = idx in state["selected"]

                cell = ft.Container(
                    content=ft.Text(label, text_align=ft.TextAlign.CENTER, size=10, weight=ft.FontWeight.W_500, color=C_TEXT, max_lines=4, overflow=ft.TextOverflow.ELLIPSIS),
                    width=cell_size, height=cell_size,
                    bgcolor=C_SUCCESS if is_sel else C_NEUTRAL,
                    border_radius=10, alignment=ft.Alignment(0, 0), padding=5,
                    border=ft.Border.all(2, C_SUCCESS) if is_sel else ft.Border.all(1, C_PRIMARY + "55"),
                )

                def make_toggle(index=idx, cell_ref=cell):
                    def toggle_click(e):
                        if not state["ws"] or not state["connected"]:
                            show_error("Falta conexión"); return
                        if index in state["selected"]:
                            state["selected"].discard(index)
                            cell_ref.bgcolor = C_NEUTRAL
                            cell_ref.border = ft.Border.all(1, C_PRIMARY + "55")
                        else:
                            state["selected"].add(index)
                            cell_ref.bgcolor = C_SUCCESS
                            cell_ref.border = ft.Border.all(2, C_SUCCESS)
                        cell_ref.update()
                        run_async_network(send_payload_ws({
                            "type": "select", "room": state["room"], "player": state["player"], "index": index
                        }))
                    return toggle_click

                cell.on_click = make_toggle(idx, cell)
                row_cells.append(cell)
            grid_col.controls.append(ft.Row(row_cells, alignment=ft.MainAxisAlignment.CENTER, spacing=6))
        page.update()

    # ── Composición del Layout Visual ─────────────────────────────────────────
    page.add(
        ft.ListView(
            expand=True, spacing=14, padding=30,
            controls=[
                card(ft.Column([
                    ft.Text("🎓 BINGO", size=32, weight=ft.FontWeight.BOLD, color=C_ACCENT, text_align=ft.TextAlign.CENTER),
                    ft.Text("de Graduación", size=16, color=C_MUTED, text_align=ft.TextAlign.CENTER),
                    ft.Divider(color=C_PRIMARY + "55"),
                    ft.Row([status_icon, status_label], spacing=8),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6), padding=20),

                card(ft.Column([
                    ft.Text("1️⃣  Tu nombre", size=16, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    username_tf,
                ], spacing=10)),

                card(ft.Column([
                    ft.Text("2️⃣  Sala multijugador", size=16, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    ft.Row([ft.Container(new_room_tf, expand=True), primary_btn("Crear", click_create_room)], spacing=10),
                    ft.Row([ft.Container(room_tf, expand=True), secondary_btn("Unirse", click_join_room)], spacing=10),
                    ft.Text("Jugadores conectados:", size=13, color=C_MUTED),
                    players_col,
                ], spacing=10)),

                card(ft.Column([
                    ft.Text("3️⃣  Configura tu cartón", size=16, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    size_dd,
                    ft.Row([primary_btn("🔢 Generar casillas", build_board)], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([secondary_btn("💾 Guardar", save_template, expand=True), secondary_btn("📂 Cargar", load_template, expand=True)], spacing=10),
                    ft.Divider(color=C_PRIMARY + "33"),
                    board_inputs,
                    ft.Container(height=4),
                    ft.Row([primary_btn("🚀 Activar tablero", click_send_tasks)], alignment=ft.MainAxisAlignment.CENTER),
                ], spacing=10)),

                card(ft.Column([
                    ft.Text("🎯 Tu cartón", size=18, weight=ft.FontWeight.BOLD, color=C_TEXT, text_align=ft.TextAlign.CENTER),
                    ft.Text("Toca las casillas que hayas completado", size=12, color=C_MUTED, text_align=ft.TextAlign.CENTER),
                    grid_col,
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10), padding=16),

                card(ft.Column([
                    ft.Text("🏆 Ranking en vivo", size=18, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    ranking_col,
                ], spacing=8)),
            ]
        )
    )

ft.run(main)
