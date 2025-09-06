import flet as ft
import database as db
import csv
import os
import threading


def main(page: ft.Page):
    db.init_db()
    db.ensure_color_column()
    db.ensure_products_table()

    # PROPIEDADES
    page.title = "Control de Almacen"
    page.padding = 0
    page.spacing = 0
    page.horizontal_alignment = "stretch"
    page.vertical_alignment = "stretch"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.maximized = True
    last_import_rows: list[dict] = []

    warehouse_to_delete = {"id": None, "name": ""}
    ui_state = {
        "last_warehouse_id": None,     # último almacén mostrado en "Productos"
        "pending_file": None,          # archivo pendiente de importar
        "selected_wh_id": None,        # almacén elegido para importar
    }

    # ---- Entrada de productos (estado) ----
    entry_state = {
        "warehouse_id": None,
        "lines": {},  # code -> {"name": str, "qty": int}
    }
    exit_state = {
    "warehouse_id": None,
    "lines": {},  # code -> {"name": str, "qty": int}
        }

    COLOR_CHOICES = [
        ("slate",  ["#0f172a", "#1f2937"]),
        ("indigo", ["#1e1b4b", "#312e81"]),
        ("emerald",["#064e3b", "#065f46"]),
        ("rose",   ["#7f1d1d", "#9f1239"]),
        ("amber",  ["#78350f", "#92400e"]),
        ("zinc",   ["#18181b", "#27272a"]),
    ]

    appbar_text_ref = ft.Ref[ft.Text]()

    # ===== Control único de diálogos (sin page.dialog) =====
    current_dialog = {"dlg": None}

    def open_dialog(dlg: ft.AlertDialog):
        if current_dialog["dlg"] is not None and getattr(current_dialog["dlg"], "open", False):
            current_dialog["dlg"].open = False
            page.update()
        current_dialog["dlg"] = dlg
        page.open(dlg)

    def close_dialog():
        if current_dialog["dlg"] is not None and getattr(current_dialog["dlg"], "open", False):
            current_dialog["dlg"].open = False
            page.update()
        current_dialog["dlg"] = None

    # ======= Paginación =======
    pagination_state = {"page": 0, "per_page": 100, "items": []}

    # ========================== Helpers de productos
    def fetch_products_for_warehouse(warehouse_id: int | None):
        # Todos
        def _all_products():
            items = []
            try:
                if hasattr(db, "list_products"):
                    items = db.list_products()
            except Exception:
                items = []
            return items

        if warehouse_id is None:
            return _all_products(), None

        if hasattr(db, "list_products_by_warehouse"):
            try:
                return db.list_products_by_warehouse(warehouse_id), None
            except Exception as ex:
                return _all_products(), f"No se pudo listar por almacén (usando todos): {ex}"

        return _all_products(), "Tu DB no expone list_products_by_warehouse; mostrando todos."

    def render_products_list(warehouse_id: int | None = None):
        items, warn = fetch_products_for_warehouse(warehouse_id)
        if not items and last_import_rows:
            items = last_import_rows

        norm_items = []
        for it in items:
            code = str(it.get("code") or it.get("codigo") or it.get("Código") or "")
            name = str(it.get("name") or it.get("nombre") or it.get("Nombre") or "")
            desc = str(it.get("description") or it.get("descripcion") or it.get("Descripción") or "")
            norm_items.append({"code": code, "name": name, "description": desc, "qty": it.get("qty")})
        norm_items.sort(key=lambda x: x["code"])

        pagination_state["items"] = norm_items
        pagination_state["page"] = 0

        wh_title = ""
        if warehouse_id is not None:
            ui_state["last_warehouse_id"] = warehouse_id
            try:
                ws = {w["id"]: w for w in db.list_warehouses()}
                if warehouse_id in ws:
                    wh_title = f" – {ws[warehouse_id]['name']}"
            except Exception:
                pass

        def build_table_page():
            per = pagination_state["per_page"]
            page_idx = pagination_state["page"]
            data = pagination_state["items"]
            total = len(data)
            start = page_idx * per
            end = min(start + per, total)
            rows = []
            for it in data[start:end]:
                cells = [
                    ft.DataCell(ft.Text(it["code"])),
                    ft.DataCell(ft.Text(it["name"])),
                    ft.DataCell(ft.Text(it["description"])),
                ]
                # Si estamos filtrando por almacén y hay qty, muéstrala
                if warehouse_id is not None:
                    cells.append(ft.DataCell(ft.Text(str(it.get("qty", 0)))))
                rows.append(ft.DataRow(cells=cells))

            columns = [
                ft.DataColumn(ft.Text("Código")),
                ft.DataColumn(ft.Text("Nombre")),
                ft.DataColumn(ft.Text("Descripción")),
            ]
            if warehouse_id is not None:
                columns.append(ft.DataColumn(ft.Text("Existencia")))

            table = ft.DataTable(
                columns=columns,
                rows=rows,
                column_spacing=20,
                heading_row_height=40,
                data_row_max_height=56,
            )

            total_pages = max(1, (total + per - 1) // per)
            page_label = ft.Text(f"Página {page_idx + 1} de {total_pages} • {total} producto(s)")

            def go_prev(e):
                if pagination_state["page"] > 0:
                    pagination_state["page"] -= 1
                    render_controls()

            def go_next(e):
                if (pagination_state["page"] + 1) * per < total:
                    pagination_state["page"] += 1
                    render_controls()

            pager = ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.FilledButton("Anterior", on_click=go_prev, disabled=(page_idx == 0)),
                    ft.FilledButton("Siguiente", on_click=go_next, disabled=(end >= total)),
                ],
            )

            return table, page_label, pager

        def render_controls():
            table, page_label, pager = build_table_page()
            header_text = "Productos" + wh_title
            extra = []
            if warn:
                extra.append(ft.Text(warn, size=11, color=ft.Colors.ORANGE_700))
            content_column.controls[:] = [
                ft.Container(
                    padding=ft.padding.only(8, 0, 8, 8),
                    content=ft.Column(
                        controls=[ft.Text(header_text, size=20, weight=ft.FontWeight.BOLD)] + extra,
                        spacing=4
                    ),
                ),
                ft.Container(padding=ft.padding.only(8, 0, 8, 4), content=page_label),
                ft.Container(expand=True, padding=ft.padding.all(8), content=ft.ListView(expand=True, controls=[table])),
                ft.Container(padding=ft.padding.all(8), content=pager),
            ]
            page.update()

        render_controls()

    # Helper: refrescar la vista actual de productos (si está filtrada por almacén)
    def refresh_current_products_view():
        wid = ui_state.get("last_warehouse_id")
        if wid is not None:
            render_products_list(wid)

    # -------- Render de almacenes 300x300 --------
    def render_warehouses():
        warehouses = db.list_warehouses()
        if not warehouses:
            content_column.controls[:] = [
                ft.Container(
                    padding=20,
                    content=ft.Text("Aún no hay almacenes. Ve a Almacén > Crear un almacén.", size=16)
                )
            ]
            page.update()
            return

        cards = []
        for w in warehouses:
            def _open_wh_products(e, _w=w):
                render_products_list(_w["id"])

            card_body = ft.Container(
                width=300,
                height=300,
                gradient=gradient_for(w.get("color_key") or "slate"),
                border_radius=8,
                padding=16,
                ink=True,
                on_click=_open_wh_products,
                shadow=ft.BoxShadow(spread_radius=1, blur_radius=18, color=ft.Colors.BLACK26, offset=ft.Offset(0, 6)),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.WAREHOUSE, size=68, color=ft.Colors.WHITE),
                        ft.Text(w["name"], size=18, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, color=ft.Colors.WHITE),
                        ft.Text((w.get("description") or "—"), size=12, color=ft.Colors.WHITE70, text_align=ft.TextAlign.CENTER),
                    ],
                ),
            )

            delete_btn = ft.IconButton(
                icon=ft.Icons.DELETE_FOREVER_ROUNDED,
                icon_size=20, width=25, height=25, tooltip="Eliminar almacén",
                icon_color=ft.Colors.RED_600,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5), padding=2, bgcolor=ft.Colors.WHITE),
                on_click=lambda e, _w=w: confirm_delete(_w),
            )
            card = ft.Stack(width=300, height=300, controls=[card_body, ft.Container(right=8, top=8, content=delete_btn, border_radius=5)])
            cards.append(card)

        grid = ft.GridView(expand=True, runs_count=3, max_extent=320, child_aspect_ratio=1, spacing=16, run_spacing=16, controls=cards)

        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8, 0, 8, 8), content=ft.Text("Almacenes", size=20, weight=ft.FontWeight.BOLD)),
            ft.Container(expand=True, padding=ft.padding.all(8), content=grid),
        ]
        page.update()

    # Ir directo a crear almacén desde el alerta de “no hay almacenes”
    def goto_create(e):
        close_dialog()
        open_create_dialog()

    # ========== IMPORTACIÓN con selección de ALMACÉN ==========
    def render_import_products():
        warehouses = db.list_warehouses()
        if not warehouses:
            open_dialog(alert_no_wh); return

        hint = ft.Column(
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.FILE_UPLOAD, size=60, color=ft.Colors.GREY_700),
                ft.Text("Arrastra tu archivo CSV o Excel aquí", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("o haz clic para seleccionar un archivo", size=12, color=ft.Colors.GREY_600),
                ft.FilledButton("Cargar archivo", icon=ft.Icons.UPLOAD_FILE,
                    on_click=lambda e: file_picker.pick_files(allow_multiple=False, allowed_extensions=["csv","CSV","xlsx","XLSX","xls","XLS"])),
                ft.Text("Campos requeridos: Código, Nombre, Descripción", size=11, color=ft.Colors.GREY_700),
            ],
        )

        drop_zone = ft.Container(
            width=520, height=280, bgcolor=ft.Colors.GREY_100,
            border=ft.border.all(2, ft.Colors.GREY_300), border_radius=12, ink=True,
            on_click=lambda e: file_picker.pick_files(allow_multiple=False, allowed_extensions=["csv","xlsx","xls"]),
            content=hint, alignment=ft.alignment.center,
        )

        content_column.controls[:] = [ft.Container(expand=True, alignment=ft.alignment.center, content=drop_zone)]
        page.update()

    def open_create_dialog():
        name_tf.value = ""; descr_tf.value = ""
        dlg_create.open = True
        page.open(dlg_create)

    def save_warehouse():
        name = (name_tf.value or "").strip()
        desc = (descr_tf.value or "").strip()
        if not name:
            page.open(ft.SnackBar(ft.Text("El nombre es obligatorio."))); return
        try:
            db.add_warehouse(name=name, description=desc, color_key=color_dd.value)
            page.open(ft.SnackBar(ft.Text(f"Almacén '{name}' creado.")))
            dlg_create.open = False; page.update(); close_dialog()
            render_warehouses(); page.update()
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"Error: {ex}")))

    # ==== Handlers de menú ====
    def handle_submenu_open(e: ft.ControlEvent): pass
    def handle_submenu_close(e: ft.ControlEvent): pass
    def handle_submenu_hover(e: ft.ControlEvent): pass

    def handle_menu_item_click(e: ft.ControlEvent):
        cmd = getattr(e.control, "data", None)
        label = e.control.content.value if hasattr(e.control, "content") else ""

        if cmd == "warehouses_view" or label == "Ver almacenes":
            render_warehouses()
        elif cmd == "warehouse_new" or label == "Crear un almacen":
            open_create_dialog()
        elif label == "Entrada de productos":
            open_entry_dialog()
        elif cmd == "products_import" or label == "Agregar Lista de Productos":
            render_import_products()
        elif cmd == "products_view" or label == "Ver productos":
            ui_state["last_warehouse_id"] = None
            render_products_list(None)
        else:
            page.open(ft.SnackBar(content=ft.Text(f"{label} was clicked!")))

        if appbar_text_ref.current:
            appbar_text_ref.current.value = label
            page.update()

    # ======= Helpers de importación / duplicados =========
    def _normalize(s: str) -> str: return (s or "").strip()

    def _existing_codes_set():
        codes = set()
        try:
            if hasattr(db, "list_products"):
                for p in db.list_products():
                    c = _normalize(str(p.get("code") or p.get("codigo") or ""))
                    if c: codes.add(c)
        except Exception: pass
        return codes

    def _map_headers(headers: list[str]):
        def _norm(h: str):
            h = (h or "").strip().lower()
            for a,b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u")]: h = h.replace(a,b)
            return h
        norm = [_norm(h) for h in headers]
        def find(*c): 
            for k in c:
                if k in norm: return norm.index(k)
            return -1
        i_code = find("codigo","código","code","sku","clave")
        i_name = find("nombre","name","producto")
        i_desc = find("descripcion","descripción","description","detalle")
        if i_code < 0 or i_name < 0:
            raise ValueError("Encabezados requeridos: Código y Nombre (Descripción opcional).")
        return i_code, i_name, i_desc

    def parse_products_from_file(file_meta) -> list[dict]:
        path = file_meta.path
        if not path or not os.path.exists(path):
            raise RuntimeError("No se pudo acceder al archivo seleccionado.")
        ext = os.path.splitext(path)[1].lower()
        rows = []

        if ext == ".csv":
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                dr = csv.reader(f); headers = next(dr, None)
                if not headers: raise ValueError("El CSV no contiene encabezados.")
                i_code, i_name, i_desc = _map_headers(headers)
                for r in dr:
                    if not r or len(r) <= max(i_code, i_name): continue
                    code = _normalize(r[i_code] if i_code >=0 and i_code < len(r) else "")
                    name = _normalize(r[i_name] if i_name >=0 and i_name < len(r) else "")
                    desc = _normalize(r[i_desc] if i_desc >=0 and i_desc < len(r) else "")
                    if not (code and name): continue
                    rows.append({"code": code, "name": name, "description": desc})
        elif ext in (".xlsx", ".xls"):
            try:
                from openpyxl import load_workbook
            except Exception:
                raise ImportError("Para archivos Excel instala: pip install openpyxl")
            wb = load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            header_cells = next(ws.iter_rows(min_row=1, max_row=1))
            headers = [("" if c.value is None else str(c.value)) for c in header_cells]
            i_code, i_name, i_desc = _map_headers(headers)
            for row in ws.iter_rows(min_row=2):
                vals = [("" if c.value is None else str(c.value)) for c in row]
                if not vals or len(vals) <= max(i_code, i_name): continue
                code = _normalize(vals[i_code] if i_code >=0 and i_code < len(vals) else "")
                name = _normalize(vals[i_name] if i_name >=0 and i_name < len(vals) else "")
                desc = _normalize(vals[i_desc] if i_desc >=0 and i_desc < len(vals) else "")
                if not (code and name): continue
                rows.append({"code": code, "name": name, "description": desc})
        else:
            raise ValueError("Formato no soportado. Usa CSV o Excel (.xlsx/.xls).")

        if not rows:
            raise ValueError("No se encontraron filas válidas (requiere al menos Código y Nombre).")
        return rows

    # ======= Importación con selección de almacén =====
    def import_rows_with_progress(rows: list[dict], warehouse_id: int):
        existing = _existing_codes_set()
        preprocessed = [{"code": _normalize(r["code"]), "name": _normalize(r["name"]), "description": _normalize(r.get("description",""))} for r in rows]
        total = len(preprocessed)
        prog = ft.ProgressBar(value=0, width=400)
        lbl  = ft.Text(f"0 / {total} productos", size=12)

        dlg_prog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Cargando productos..."),
            content=ft.Column([prog, lbl], spacing=10, width=420, height=60),
            shape=ft.RoundedRectangleBorder(radius=5),
            shadow_color=ft.Colors.BLACK38,
            actions=[],
        )
        open_dialog(dlg_prog)

        def _link_to_warehouse(code: str, wid: int):
            if hasattr(db, "is_product_linked"):
                try:
                    if db.is_product_linked(code, wid): return
                except Exception: pass
            if hasattr(db, "link_product_to_warehouse"):
                db.link_product_to_warehouse(code, wid); return
            db.upsert_product(code=code, name=None, description=None, warehouse_id=wid)

        def worker():
            ok = dup = link_ok = err = 0
            for i, r in enumerate(preprocessed, start=1):
                try:
                    code_key = r["code"]
                    if code_key not in existing:
                        db.upsert_product(code=r["code"], name=r["name"], description=r.get("description",""), warehouse_id=None)
                        existing.add(code_key); ok += 1
                    _link_to_warehouse(code_key, warehouse_id); link_ok += 1
                except Exception:
                    err += 1
                prog.value = i / total; lbl.value = f"{i} / {total} productos"; page.update()

            dlg_prog.open = False; page.update(); close_dialog()
            msg = f"Importación: {ok} nuevos"
            if dup: msg += f", {dup} ya existían"
            if link_ok: msg += f", {link_ok} asociados"
            if err: msg += f", {err} con error"
            page.open(ft.SnackBar(ft.Text(msg)))
            render_products_list(warehouse_id)

        threading.Thread(target=worker, daemon=True).start()

    def process_selected_file_with_warehouse(file_meta, warehouse_id: int):
        try:
            rows = parse_products_from_file(file_meta)
        except ImportError as ie:
            page.open(ft.SnackBar(ft.Text(str(ie)))); return
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"Error al leer archivo: {ex}"))); return
        import_rows_with_progress(rows, warehouse_id)

    # ---------- FilePicker ----------
    def on_file_picked(e: ft.FilePickerResultEvent):
        if not e.files: return
        f = e.files[0]
        ui_state["pending_file"] = f
        refresh_pick_wh_dialog_and_open()

    # ====== Diálogo: Seleccionar almacén para importar ======
    def refresh_pick_wh_dialog_and_open():
        warehouses = db.list_warehouses()
        if not warehouses:
            open_dialog(alert_no_wh); return
        wh_options = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses]
        wh_dd.options = wh_options
        wh_dd.value = wh_options[0].key if wh_options else None
        ui_state["selected_wh_id"] = int(wh_dd.value) if wh_dd.value else None
        open_dialog(dlg_pick_wh)

    def on_pick_wh_changed(e):
        val = wh_dd.value
        ui_state["selected_wh_id"] = int(val) if val is not None else None

    def on_pick_wh_confirm(e):
        if ui_state["pending_file"] is None or ui_state["selected_wh_id"] is None:
            page.open(ft.SnackBar(ft.Text("Selecciona un almacén válido."))); return
        dlg_pick_wh.open = False; page.update(); close_dialog()
        process_selected_file_with_warehouse(ui_state["pending_file"], ui_state["selected_wh_id"])
        ui_state["pending_file"] = None

    def on_pick_wh_cancel(e):
        dlg_pick_wh.open = False; page.update(); close_dialog()
        ui_state["pending_file"] = None; ui_state["selected_wh_id"] = None

    # -------- ENTRADA DE PRODUCTOS (alert) --------
    entry_wh_dd = ft.Dropdown(label="Almacén", width=360)
    entry_code_tf = ft.TextField(
        label="Código / Escáner",
        autofocus=True,
        width=360,
        on_submit=lambda e: entry_add_code(e.control.value),
        keyboard_type=ft.KeyboardType.NUMBER
    )
    entry_lines_col = ft.Column(spacing=8, width=520, tight=True, scroll=ft.ScrollMode.ADAPTIVE)

    def _entry_refresh_warehouse_options():
        ws = db.list_warehouses()
        entry_wh_dd.options = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in ws]
        if ws:
            entry_wh_dd.value = str(ws[0]["id"])
            entry_state["warehouse_id"] = ws[0]["id"]
        else:
            entry_wh_dd.value = None
            entry_state["warehouse_id"] = None

    def entry_on_wh_change(e):
        entry_state["warehouse_id"] = int(entry_wh_dd.value) if entry_wh_dd.value else None
        entry_state["lines"].clear()
        entry_render_lines()

    entry_wh_dd.on_change = entry_on_wh_change

    def entry_render_lines():
        rows = []
        for code, data in entry_state["lines"].items():
            qty_tf = ft.TextField(
                value=str(data["qty"]), width=70, text_align=ft.TextAlign.RIGHT,
                on_change=lambda e, _c=code: entry_update_qty(_c, e.control.value),
            )
            rows.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[ft.Text(f"{code} – {data['name']}", size=13), ft.Row(controls=[ft.Text("Cant."), qty_tf])],
                )
            )
        entry_lines_col.controls = rows
        page.update()

    def entry_update_qty(code: str, val: str):
        try:
            n = int(val);  n = 1 if n <= 0 else n
        except: n = 1
        if code in entry_state["lines"]:
            entry_state["lines"][code]["qty"] = n

    def entry_add_code(raw_code: str):
        code = (raw_code or "").strip()
        entry_code_tf.value = ""; page.update()
        if not code: return
        wid = entry_state["warehouse_id"]
        if not wid:
            page.open(ft.SnackBar(ft.Text("Selecciona un almacén."))); return
        try:
            prods = db.list_products_by_warehouse(wid)
            mp = {p["code"]: p for p in prods}
            if code not in mp:
                page.open(ft.SnackBar(ft.Text("El código no pertenece a este almacén."))); return
            name = mp[code]["name"]
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"No se pudo validar producto: {ex}"))); return

        entry_state["lines"].setdefault(code, {"name": name, "qty": 0})
        entry_state["lines"][code]["qty"] += 1
        entry_render_lines()

    def entry_confirm(e):
        wid = entry_state["warehouse_id"]
        if not wid or not entry_state["lines"]:
            page.open(ft.SnackBar(ft.Text("No hay productos que registrar."))); return
        total_items = 0
        for code, data in entry_state["lines"].items():
            qty = int(data["qty"] or 0)
            if qty > 0:
                db.increment_stock(code, wid, qty, note="Entrada manual")
                total_items += qty

        # Cierra el diálogo
        dlg_entry.open = False
        page.update()
        close_dialog()

        # 🔄 Refresca la vista de productos si estás viendo ese almacén
        if ui_state.get("last_warehouse_id") == wid:
            render_products_list(wid)   # vuelve a consultar qty y actualiza la tabla
            page.update()

        # Feedback y limpieza
        page.open(ft.SnackBar(ft.Text(
            f"Entrada registrada: {len(entry_state['lines'])} productos, {total_items} unidades."
        )))
        entry_state["lines"].clear()

    def entry_clear(e):
        entry_state["lines"].clear()
        entry_render_lines()

    def open_entry_dialog():
        if not db.list_warehouses():
            open_dialog(alert_no_wh); return
        _entry_refresh_warehouse_options()
        entry_state["lines"].clear()
        entry_render_lines()
        page.open(dlg_entry)

    def exit_on_wh_change(e):
        exit_state["warehouse_id"] = int(exit_wh_dd.value) if exit_wh_dd.value else None
        exit_render_lines()

    def exit_render_lines():
        print(exit_state["lines"])
        rows = []
        for code, data in exit_state["lines"].items():
            qty_tf = ft.TextField(
                value=str(data["qty"]), width=70, text_align=ft.TextAlign.RIGHT,
                on_change=lambda e, _c=code: exit_update_qty(_c, e.control.value),
            )
            rows.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[ft.Text(f"{code} – {data['name']}", size=13), ft.Row(controls=[ft.Text("Cant."), qty_tf])],
                )
            )

        # Solo actualiza los controles sin borrar los previos
        exit_lines_col.controls[:] = rows
        page.update()


    def exit_update_qty(code: str, val: str):
        try:
            n = int(val)
            n = 1 if n <= 0 else n  # Asegura que la cantidad sea mayor que 0
        except:
            n = 1  # Si la conversión falla, por defecto se asigna cantidad 1

        if code in exit_state["lines"]:
            exit_state["lines"][code]["qty"] = n

        exit_render_lines()  # Actualiza la vista


    def exit_add_code(raw_code: str):
        code = (raw_code or "").strip()
        exit_code_tf.value = ""  # Limpiar el campo de código para seguir escaneando
        page.update()  # Actualizar la página

        if not code:
            return

        # Verificar el almacén seleccionado
        wid = exit_state["warehouse_id"]
        if not wid:
            page.open(ft.SnackBar(ft.Text("Selecciona un almacén.")))
            return

        try:
            # Obtener los productos del almacén
            prods = db.list_products_by_warehouse(wid)
            mp = {p["code"]: p for p in prods}

            # Verificar si el código escaneado pertenece al almacén
            if code not in mp:
                page.open(ft.SnackBar(ft.Text("El código no pertenece a este almacén.")))
                return

            name = mp[code]["name"]
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"No se pudo validar producto: {ex}")))
            return

        # Si el código ya está en la lista de productos, incrementa la cantidad
        if code in exit_state["lines"]:
            exit_state["lines"][code]["qty"] += 1
        else:
            # Si el código no está, añádelo con cantidad 1
            exit_state["lines"][code] = {"name": name, "qty": 1}

        # Actualiza la vista de productos en el alert
        exit_render_lines()  # Llama a la función para renderizar los productos en el dialog






    def exit_confirm(e):
        wid = exit_state["warehouse_id"]
        if not wid or not exit_state["lines"]:
            page.open(ft.SnackBar(ft.Text("No hay productos que registrar."))); return
        total_items = 0
        for code, data in exit_state["lines"].items():
            qty = int(data["qty"] or 0)
            if qty > 0:
                db.decrement_stock(code, wid, qty, note="Salida manual")
                total_items += qty

        # Cierra el diálogo
        dlg_exit.open = False
        page.update()
        close_dialog()

        # 🔄 Refresca la vista de productos si estás viendo ese almacén
        if ui_state.get("last_warehouse_id") == wid:
            render_products_list(wid)   # vuelve a consultar qty y actualiza la tabla
            page.update()

        # Feedback y limpieza
        page.open(ft.SnackBar(ft.Text(
            f"Salida registrada: {len(exit_state['lines'])} productos, {total_items} unidades."
        )))
        exit_state["lines"].clear()

    def exit_clear(e):
        exit_state["lines"].clear()
        exit_render_lines()

    def _exit_refresh_warehouse_options():
        ws = db.list_warehouses()
        exit_wh_dd.options = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in ws]
        if ws:
            exit_wh_dd.value = str(ws[0]["id"])
            exit_state["warehouse_id"] = ws[0]["id"]
        else:
            exit_wh_dd.value = None
            exit_state["warehouse_id"] = None

    def open_exit_dialog(e):  # Añadir 'e' para aceptar el evento
        if not db.list_warehouses():
            open_dialog(alert_no_wh); return
        _exit_refresh_warehouse_options()
        exit_state["lines"].clear()
        exit_render_lines()
        page.open(dlg_exit)



    

    # ---------- UI base / common ----------
    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.append(file_picker)

    exit_wh_dd = ft.Dropdown(label="Almacén", width=360)
    exit_code_tf = ft.TextField(
        label="Código / Escáner",
        autofocus=True,
        width=360,
        on_submit=lambda e: exit_add_code(e.control.value),
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=lambda e: exit_on_wh_change(e.control.value),
    )
    exit_lines_col = ft.Column(spacing=8, width=520, tight=True, scroll=ft.ScrollMode.ADAPTIVE)

    dlg_exit = ft.AlertDialog(
        modal=True,
        title=ft.Text("Salida de productos"),
        content=ft.Column(
            width=560, spacing=12,
            controls=[
                exit_wh_dd,
                exit_code_tf,
                ft.Divider(),
                ft.Text("Productos en esta salida:", size=12, color=ft.Colors.GREY_700),
                exit_lines_col,
            ], height=400, scroll=ft.ScrollMode.AUTO
        ), shape=ft.RoundedRectangleBorder(radius=5),
        actions=[
            ft.TextButton("Vaciar", on_click=exit_clear),
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_exit, "open", False), page.update(), close_dialog())),
            ft.FilledButton("Confirmar", on_click=exit_confirm),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    content_column = ft.Column(expand=True, scroll=None, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    color_dd = ft.Dropdown(label="Color de tarjeta", width=400, value="slate",
                           options=[ft.dropdown.Option(k, text=k.capitalize()) for k,_ in COLOR_CHOICES])
    content_area = ft.Container(top=56, left=0, right=0, bottom=0, padding=ft.padding.only(20, 20, 20, 20), content=content_column)
    name_tf = ft.TextField(label="Nombre del almacén", autofocus=True, width=400)
    descr_tf = ft.TextField(label="Descripción (opcional)", width=400, height=100)

    dlg_delete = ft.AlertDialog(
        modal=True,
        title=ft.Text("Eliminar almacén"),
        content=ft.Text("Esta acción eliminará el almacén y sus datos relacionados (vínculos/stock). ¿Deseas continuar?"),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_delete, "open", False), page.update(), close_dialog())),
            ft.FilledButton("Eliminar", on_click=lambda e: do_delete_warehouse()),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    dlg_create = ft.AlertDialog(
        modal=True,
        title=ft.Text("Crear un almacén"),
        shape=ft.RoundedRectangleBorder(radius=5),
        content=ft.Column([name_tf, color_dd], tight=True, spacing=10, width=400),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_create, "open", False), page.update(), close_dialog()),
                          style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
            ft.FilledButton("Guardar", on_click=lambda e: save_warehouse(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # Diálogo para elegir almacén al importar
    wh_dd = ft.Dropdown(label="Selecciona un almacén", width=360, on_change=on_pick_wh_changed)
    dlg_pick_wh = ft.AlertDialog(
        modal=True,
        title=ft.Text("¿A qué almacén se agregarán estos productos?"),
        content=ft.Column([wh_dd], spacing=10, width=380, tight=True),
        actions=[ft.TextButton("Cancelar", on_click=on_pick_wh_cancel), ft.FilledButton("Confirmar", on_click=on_pick_wh_confirm)],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # Diálogo de ENTRADA DE PRODUCTOS
    dlg_entry = ft.AlertDialog(
        modal=True,
        title=ft.Text("Entrada de productos"),
        content=ft.Column(
            width=560, spacing=12,
            controls=[
                entry_wh_dd,
                entry_code_tf,
                ft.Divider(),
                ft.Text("Productos en esta entrada:", size=12, color=ft.Colors.GREY_700),
                entry_lines_col,
            ], height=400, scroll=ft.ScrollMode.AUTO
        ), shape=ft.RoundedRectangleBorder(radius=5),
        actions=[
            ft.TextButton("Vaciar", on_click=entry_clear),
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_entry, "open", False), page.update(), close_dialog())),
            ft.FilledButton("Confirmar", on_click=entry_confirm),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    alert_no_wh = ft.AlertDialog(
        modal=True,
        title=ft.Text("No hay almacenes"),
        content=ft.Text("Debes crear al menos un almacén antes de continuar."),
        actions=[ft.FilledButton("Crear un almacén", on_click=goto_create)],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def gradient_for(key: str):
        mp = {k:v for k,v in COLOR_CHOICES}; colors = mp.get(key, mp["slate"])
        return ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=colors)

    def confirm_delete(w):
        warehouse_to_delete["id"] = w["id"]; warehouse_to_delete["name"] = w["name"]
        open_dialog(dlg_delete)

    def do_delete_warehouse():
        try:
            db.delete_warehouse_cascade(warehouse_to_delete["id"])
            page.open(ft.SnackBar(ft.Text(f"Almacén '{warehouse_to_delete['name']}' eliminado.")))
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"Error: {ex}")))
        finally:
            dlg_delete.open = False; page.update(); close_dialog(); render_warehouses()

    # Menubar
    menubar = ft.MenuBar(
        style=ft.MenuStyle(
            alignment=ft.alignment.top_left, bgcolor=ft.Colors.WHITE,
            mouse_cursor={ft.ControlState.HOVERED: ft.MouseCursor.WAIT, ft.ControlState.DEFAULT: ft.MouseCursor.ZOOM_OUT},
            shape=ft.RoundedRectangleBorder(radius=0),
        ),
        controls=[
            ft.SubmenuButton(
                content=ft.Text("Inicio"),
                on_open=handle_submenu_open, on_close=handle_submenu_close,
                controls=[
                    ft.MenuItemButton(content=ft.Text("Dashboard"), leading=ft.Icon(ft.Icons.DASHBOARD),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                ],
            ),
            ft.SubmenuButton(
                content=ft.Text("Almacén"),
                on_open=handle_submenu_open, on_close=handle_submenu_close,
                controls=[
                    ft.MenuItemButton(content=ft.Text("Ver almacenes"), leading=ft.Icon(ft.Icons.INVENTORY),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                    ft.MenuItemButton(content=ft.Text("Crear un almacen"), leading=ft.Icon(ft.Icons.WAREHOUSE),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                    ft.MenuItemButton(content=ft.Text("Entrada de productos"), leading=ft.Icon(ft.Icons.QR_CODE),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                    ft.MenuItemButton(content=ft.Text("Salida de productos"), leading=ft.Icon(ft.Icons.EXIT_TO_APP),
                                  style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                       shape=ft.RoundedRectangleBorder(radius=0)),
                                  on_click=open_exit_dialog),
                    ft.MenuItemButton(content=ft.Text("Importar lista de almacenes"), leading=ft.Icon(ft.Icons.LIST_ALT),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                ],
            ),
            ft.SubmenuButton(
                content=ft.Text("Productos"),
                on_open=handle_submenu_open, on_close=handle_submenu_close,
                controls=[
                    ft.MenuItemButton(content=ft.Text("Ver productos"), data="products_view", leading=ft.Icon(ft.Icons.INVENTORY_SHARP),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                    ft.MenuItemButton(content=ft.Text("Agregar Lista de Productos"), data="products_import", leading=ft.Icon(ft.Icons.FILE_OPEN),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                ],
            ),
            ft.SubmenuButton(
                content=ft.Text("Operadores"),
                on_open=handle_submenu_open, on_close=handle_submenu_close,
                controls=[
                    ft.MenuItemButton(content=ft.Text("Ver operadores"), leading=ft.Icon(ft.Icons.PERSON),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                    ft.MenuItemButton(content=ft.Text("Agregar operador"), leading=ft.Icon(ft.Icons.PERSON_4_SHARP),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                ],
            ),
            ft.SubmenuButton(
                content=ft.Text("Buscar"),
                on_open=handle_submenu_open, on_close=handle_submenu_close,
                controls=[
                    ft.MenuItemButton(content=ft.Text("Buscar un producto"), leading=ft.Icon(ft.Icons.SEARCH),
                                      style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
                                                           shape=ft.RoundedRectangleBorder(radius=0)),
                                      on_click=handle_menu_item_click),
                ],
            ),
        ],
    )

    top_bar = ft.Container(content=menubar, padding=0, left=0, right=0, top=0)

    page.add(
        ft.SafeArea(
            content=ft.Stack(controls=[top_bar, content_area]),
            top=True, bottom=True, left=True, right=True, expand=True,
        )
    )
    render_warehouses()


if __name__ == "__main__":
    ft.app(target=main)
