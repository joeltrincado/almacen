# main.py
import flet as ft
import database as db
import threading
import os, csv
import helpers as hp
import components as cmp 
import datetime


def main(page: ft.Page):
    # =========================
    #   INIT / PROPIEDADES
    # =========================
    db.init_db()
    db.ensure_color_column()
    db.ensure_products_table()

    page.title = "Control de Almacen"
    page.padding = 0
    page.spacing = 0
    page.horizontal_alignment = "stretch"
    page.vertical_alignment = "stretch"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.maximized = True

    # =========================
    #   ESTADO GLOBAL
    # =========================
    last_import_rows: list[dict] = []
    appbar_text_ref = ft.Ref[ft.Text]()
    content_column = ft.Column(expand=True, scroll=None, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    warehouse_to_delete = {"id": None, "name": ""}
    ui_state = {
        "current_view": "warehouses",
        "last_warehouse_id": None,
        "pending_file": None,
        "selected_wh_id": None,
        "replace_stock": False,
        "recent_searches": [],
    }

    entry_state = {"warehouse_id": None, "lines": {}}
    exit_state = {"warehouse_id": None, "lines": {}}
    exit_over_state = {"warehouse_id": None, "items": []}
    pagination_state = {"page": 0, "per_page": 100, "items": []}
    search_state = {
        "query": "",
        "warehouse_id": None,
        "in_stock_only": False,
        "include_descr": False,
        "low_stock_only": False,
        "low_stock_threshold": 5,
        "results": [],
    }

    COLOR_CHOICES = cmp.DEFAULT_COLOR_CHOICES  # <<--- usar la misma paleta en componentes

    # =========================
    #   HELPERS UI
    # =========================
    def notify(kind: str, message: str):
        sb = cmp.make_snackbar(kind, message)   # <<--- usar componente
        page.open(sb)

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

    def gradient_for(key: str):
        return cmp.gradient_for(key, COLOR_CHOICES)  # <<--- usar componente

    # =========================
    #   PRODUCT DETAIL DIALOG
    # =========================
    def open_product_detail(code: str, name: str):
        descr = ""
        try:
            for p in (db.list_products() or []):
                if str(p.get("code")) == code:
                    descr = str(p.get("description") or p.get("descripcion") or "")
                    break
        except Exception:
            descr = ""

        totals, per_wh, wh_names = hp.build_stock_indexes(db)
        total = int(totals.get(code, 0))
        rows = []
        for wid, cmap in per_wh.items():
            qty = int(cmap.get(code, 0))
            if qty > 0:
                rows.append(
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[ft.Text(wh_names.get(wid, "Almacén"), size=12),
                                  ft.Text(str(qty), size=12, weight=ft.FontWeight.W_600)]
                    )
                )
        if not rows:
            rows = [ft.Text("No se encuentra en ningún almacén.", size=12, italic=True, color=ft.Colors.GREY_700)]

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Producto: {code}"),
            shape=ft.RoundedRectangleBorder(radius=8),
            content=ft.Column(
                spacing=8, width=520, height=300, scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"Nombre: {name}", size=12),
                    ft.Text(f"Descripción: {descr or '—'}", size=12),
                    ft.Divider(),
                    ft.Text(f"Total existencias: {total}", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.RED_600 if total == 0 else None),
                    ft.Text("Almacenes:", size=12, color=ft.Colors.GREY_700),
                    ft.Column(rows, spacing=6),
                ],
            ),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: (setattr(dlg, "open", False), page.update(), close_dialog()))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_dialog(dlg)

    # =========================
    #   VISTAS PRINCIPALES
    # =========================
    def render_warehouses():
        ui_state["current_view"] = "warehouses"
        warehouses = db.list_warehouses()
        if not warehouses:
            # Mostrar pantalla vacía con botón
            content_column.controls[:] = [
                cmp.empty_warehouses(on_create=lambda e: open_create_dialog())
            ]
            page.update()
            return

        cards = []

        def _open_wh_products(e, w):
            render_products_list(w["id"])

        def _delete_wh(e, w):
            confirm_delete(w)

        for w in warehouses:
            cards.append(
                cmp.warehouse_card(w, on_open=_open_wh_products, on_delete=_delete_wh, color_choices=COLOR_CHOICES)  # <<---
            )

        add_card = ft.Container(
            ink=True,
            on_click=lambda e: open_create_dialog(),
            border_radius=16,
            bgcolor=ft.Colors.GREY_100,
            padding=16,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    ft.Container(
                        width=56, height=56,
                        border_radius=28,
                        bgcolor=ft.Colors.GREY_200,
                        alignment=ft.alignment.center,
                        content=ft.Icon(ft.Icons.ADD, size=28, color=ft.Colors.GREY_700),
                    ),
                    ft.Text("Agregar nuevo almacén", size=13, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_800, text_align=ft.TextAlign.CENTER),
                    ft.Text("Crea un espacio para tu inventario", size=11, color=ft.Colors.GREY_600, text_align=ft.TextAlign.CENTER),
                ],
            ),
        )
        cards.append(add_card)

        grid = ft.GridView(expand=True, runs_count=3, max_extent=320, child_aspect_ratio=1, spacing=16, run_spacing=16, controls=cards)

        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8, 0, 8, 8), content=ft.Text("Almacenes", size=20, weight=ft.FontWeight.BOLD)),
            ft.Container(expand=True, padding=ft.padding.all(8), content=grid),
        ]
        page.update()

    def render_products_list(warehouse_id: int | None = None):
        ui_state["current_view"] = "products"
        totals, per_wh, _ = hp.build_stock_indexes(db)

        items, warn = hp.fetch_products_for_warehouse(db, warehouse_id)
        if not items and last_import_rows:
            items = last_import_rows

        norm_items = []
        for it in items:
            code = str(it.get("code") or it.get("codigo") or it.get("Código") or "")
            name = str(it.get("name") or it.get("nombre") or it.get("Nombre") or "")
            total_q = int(totals.get(code, 0))
            wh_q = None
            if warehouse_id is not None:
                wh_q = int(per_wh.get(int(warehouse_id), {}).get(code, 0))
            norm_items.append({"code": code, "name": name, "total": total_q, "wh_qty": wh_q})

        if warehouse_id is None:
            for c, t in totals.items():
                if not any(x["code"] == c for x in norm_items):
                    pname = c
                    try:
                        for p in (db.list_products() or []):
                            if str(p.get("code")) == c:
                                pname = str(p.get("name") or p.get("nombre") or c)
                                break
                    except Exception:
                        pass
                    norm_items.append({"code": c, "name": pname, "total": int(t or 0), "wh_qty": None})

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
                code = it["code"]
                name = it["name"]
                total_q = int(it.get("total") or 0)
                wh_q = it.get("wh_qty")

                cells = [
                    ft.DataCell(ft.Container(content=ft.Text(code), padding=ft.padding.symmetric(6, 10))),
                    ft.DataCell(ft.Container(content=ft.Text(name), padding=ft.padding.symmetric(6, 10))),
                    ft.DataCell(ft.Container(content=ft.Text(str(total_q), color=ft.Colors.RED_600 if total_q == 0 else None),
                                             padding=ft.padding.symmetric(6, 10))),
                ]
                if warehouse_id is not None:
                    wq = int(wh_q or 0)
                    cells.append(
                        ft.DataCell(ft.Container(content=ft.Text(str(wq), color=ft.Colors.RED_600 if wq == 0 else None),
                                                 padding=ft.padding.symmetric(6, 10)))
                    )

                def on_row_click(e, c=code, n=name):
                    open_product_detail(c, n)
                    try:
                        e.control.selected = False
                        page.update()
                    except Exception:
                        pass

                rows.append(ft.DataRow(cells=cells, on_select_changed=on_row_click))

            columns = [ft.DataColumn(ft.Text("Código")), ft.DataColumn(ft.Text("Nombre")), ft.DataColumn(ft.Text("Total"))]
            if warehouse_id is not None:
                columns.append(ft.DataColumn(ft.Text("Existencia")))

            table = ft.DataTable(
                columns=columns, rows=rows, column_spacing=20, heading_row_height=40,
                data_row_max_height=56, show_checkbox_column=False
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

            pager = cmp.pager_buttons(  # <<--- usar componente
                disabled_prev=(page_idx == 0),
                disabled_next=(end >= total),
                on_prev=go_prev,
                on_next=go_next,
            )
            return table, page_label, pager

        def render_controls():
            table, page_label, pager = build_table_page()
            header_text = "Productos" + wh_title

            top_actions = []
            if warehouse_id is not None:
                top_actions = [
                    ft.FilledTonalButton("Almacenes", icon=ft.Icons.ARROW_BACK,
                                         on_click=lambda e: render_warehouses(),
                                         style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
                    ft.FilledButton("Entrada (escáner)", icon=ft.Icons.QR_CODE,
                                    on_click=lambda e, wid=warehouse_id: open_entry_for(wid),
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
                    ft.FilledButton("Salida", icon=ft.Icons.EXIT_TO_APP,
                                    on_click=lambda e, wid=warehouse_id: open_exit_for(wid),
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
                ]

            header_row = cmp.header_row(header_text, top_actions)  # <<--- usar componente

            extra = []
            if warn:
                extra.append(ft.Text(warn, size=11, color=ft.Colors.ORANGE_700))

            content_column.controls[:] = [
                ft.Container(padding=ft.padding.only(8, 0, 8, 8), content=ft.Column(controls=[header_row] + extra, spacing=6)),
                ft.Container(padding=ft.padding.only(8, 0, 8, 4), content=page_label),
                ft.Container(expand=True, padding=ft.padding.all(8), content=ft.ListView(expand=True, controls=[table])),
                ft.Container(padding=ft.padding.all(8), content=pager),
            ]
            page.update()

        render_controls()

    def _ensure_reports_dir() -> str:
        base = os.path.join(os.path.dirname(__file__), "reportes")
        os.makedirs(base, exist_ok=True)
        return base

    def _safe_slug(s: str) -> str:
        s = (s or "").strip().replace(" ", "_")
        return "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in s) or "reporte"

    def export_report_csv(doc_id: int) -> str | None:
        """Crea un CSV en ./reportes/ con el encabezado y líneas del documento."""
        head = db.get_movement_doc(doc_id)
        lines = db.list_doc_lines(doc_id)
        if not head or not lines:
            return None

        folder = _ensure_reports_dir()
        ts = (head.get("ts") or "").replace("-", "").replace(":", "").replace(" ", "T")
        fname = f"{ts}_DOC{doc_id}_{head.get('doc_type','')}_{_safe_slug(head.get('reference',''))}.csv"
        path = os.path.join(folder, fname)

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            # Encabezado
            w.writerow(["Documento", doc_id])
            w.writerow(["Fecha", head.get("ts", "")])
            w.writerow(["Tipo", head.get("doc_type", "")])
            w.writerow(["Almacén", head.get("warehouse", "")])
            w.writerow(["Referencia", head.get("reference", "")])
            w.writerow(["Contraparte", head.get("counterparty", "")])
            w.writerow(["Nota", head.get("note", "")])
            w.writerow(["Total líneas", head.get("total_lines", 0)])
            w.writerow(["Total unidades", head.get("total_qty", 0)])
            w.writerow([])
            # Detalle
            w.writerow(["#", "Código", "Nombre", "Cantidad", "Tipo", "Nota línea", "Fecha línea"])
            for i, r in enumerate(lines, 1):
                w.writerow([i, r["code"], r["name"], r["qty"], r["kind"], r.get("note",""), r.get("ts","")])
        return path

    def export_report_pdf(doc_id: int) -> str | None:
        """
        Exporta un PDF con márgenes y anchos de columna responsivos.
        Requiere: pip install reportlab
        """
        head = db.get_movement_doc(doc_id)
        lines = db.list_doc_lines(doc_id)
        if not head or not lines:
            return None

        try:
            from reportlab.lib.pagesizes import A4  # usa portrait; cambia a landscape(A4) si lo prefieres
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        except Exception as ex:
            raise RuntimeError("Falta dependencia: instala con 'pip install reportlab'") from ex

        import os
        folder = _ensure_reports_dir()
        ts = (head.get("ts") or "").replace("-", "").replace(":", "").replace(" ", "T")
        fname = f"{ts}_DOC{doc_id}_{head.get('doc_type','')}_{_safe_slug(head.get('reference',''))}.pdf"
        path = os.path.join(folder, fname)

        # Márgenes (0.5 pulgadas = 36pt)
        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            leftMargin=36, rightMargin=36,
            topMargin=36, bottomMargin=36,
            title=f"Comprobante de Movimiento • DOC #{doc_id}",
        )

        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        meta_style = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9, leading=11)
        head_style = ParagraphStyle("thead", parent=styles["Heading5"], fontSize=9, leading=11)
        cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
        cell_small = ParagraphStyle("cellSmall", parent=styles["Normal"], fontSize=8, leading=10)

        story = []
        story.append(Paragraph(f"Comprobante de Movimiento • DOC #{doc_id}", title_style))
        story.append(Spacer(1, 6))

        meta_rows = [
            ["Fecha", head.get("ts","")],
            ["Tipo", head.get("doc_type","")],
            ["Almacén", head.get("warehouse","")],
            ["Referencia", head.get("reference","") or "—"],
            ["Contraparte", head.get("counterparty","") or "—"],
            ["Nota", head.get("note","") or "—"],
            ["Total líneas", str(head.get("total_lines",0))],
            ["Total unidades", str(head.get("total_qty",0))],
        ]
        meta_tbl = Table(meta_rows, colWidths=[80, doc.width - 80])
        meta_tbl.setStyle(TableStyle([
            ("FONT", (0,0), (-1,-1), "Helvetica", 9),
            ("ALIGN", (0,0), (0,-1), "RIGHT"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(meta_tbl)
        story.append(Spacer(1, 10))

        # ---- Tabla de líneas ----
        # Distribución proporcional al ancho disponible (suma = 1.0)
        #  #   Código  Nombre  Cant.  Tipo   Nota      Fecha
        fractions = [0.06, 0.14, 0.30, 0.10, 0.12, 0.20, 0.08]
        col_widths = [doc.width * f for f in fractions]

        # Encabezados como Paragraph para evitar recortes
        header = [
            Paragraph("#", head_style),
            Paragraph("Código", head_style),
            Paragraph("Nombre", head_style),
            Paragraph("Cantidad", head_style),
            Paragraph("Tipo", head_style),
            Paragraph("Nota línea", head_style),
            Paragraph("Fecha línea", head_style),
        ]
        data = [header]

        # Filas (usa Paragraph para envolver texto)
        for i, r in enumerate(lines, 1):
            data.append([
                Paragraph(str(i), cell_small),
                Paragraph(r.get("code",""), cell_style),
                Paragraph(r.get("name","") or "—", cell_style),
                Paragraph(str(r.get("qty",0)), cell_style),
                Paragraph(r.get("kind","") or "—", cell_style),
                Paragraph(r.get("note","") or "—", cell_style),
                Paragraph(r.get("ts","") or "—", cell_style),
            ])

        tbl = Table(data, repeatRows=1, colWidths=col_widths)
        tbl.setStyle(TableStyle([
            # Cabecera
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("FONT", (0,0), (-1,0), "Helvetica-Bold", 9),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            # Cuerpo
            ("FONT", (0,1), (-1,-1), "Helvetica", 8),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            # Alineaciones específicas
            ("ALIGN", (0,1), (0,-1), "RIGHT"),   # #
            ("ALIGN", (3,1), (3,-1), "RIGHT"),   # Cantidad
            ("ALIGN", (6,1), (6,-1), "CENTER"),  # Fecha
        ]))

        story.append(tbl)
        doc.build(story)
        return path


    def export_doc_and_notify(doc_id: int, kind: str):
        """Exporta el Doc # a CSV o PDF y muestra notificación con la ruta."""
        try:
            if kind == "csv":
                p = export_report_csv(doc_id)
            else:
                p = export_report_pdf(doc_id)
            if p:
                notify("success", f"Exportado ({kind.upper()}): {p}")
            else:
                notify("warning", "No se encontró el documento o no tiene líneas.")
        except Exception as ex:
            notify("error", f"No se pudo exportar {kind.upper()}: {ex}")



    # =========================
    #   VISTA: BUSCAR
    # =========================
    search_tf_ref = ft.Ref[ft.TextField]()
    search_results_col = ft.Column(spacing=2, tight=True, height=420, scroll=ft.ScrollMode.AUTO)
    search_recent_row = ft.Row(spacing=6, wrap=True)

    def add_recent(q: str):
        qs = ui_state["recent_searches"]
        q = (q or "").strip()
        if not q:
            return
        if q in qs:
            qs.remove(q)
        qs.insert(0, q)
        if len(qs) > 8:
            qs[:] = qs[:8]

    def build_recent_chips():
        chips = []
        for q in ui_state["recent_searches"]:
            chips.append(
                ft.Chip(
                    label=ft.Text(q),
                    on_click=lambda e, _q=q: set_search_query(_q),
                    bgcolor=ft.Colors.GREY_100,
                )
            )
        if not chips:
            chips = [ft.Text("Aquí verás tus búsquedas recientes.", size=12, color=ft.Colors.GREY_600)]
        search_recent_row.controls[:] = chips

    def set_search_query(q: str):
        search_tf = search_tf_ref.current
        if search_tf:
            search_tf.value = q
        search_state["query"] = (q or "").strip()
        search_refresh_results()
        page.update()

    def search_refresh_results():
        catalog = hp.search_collect_catalog(db, search_state["warehouse_id"])
        filtered = hp.search_filter_and_score(
            catalog,
            query=search_state["query"],
            include_descr=search_state["include_descr"],
            in_stock_only=search_state["in_stock_only"],
            low_only=search_state["low_stock_only"],
            threshold=search_state["low_stock_threshold"],
            warehouse_id=search_state["warehouse_id"],
        )
        search_state["results"] = filtered[:200]

        rows = []
        wid = search_state["warehouse_id"]
        for it in search_state["results"]:
            code = it["code"]
            name = it["name"]
            total_q = int(it.get("total") or 0)
            wh_q = it.get("wh_qty")
            qty_val = int(wh_q if wid is not None else total_q)

            chip_qty = cmp.quantity_chip(qty_val)  # <<--- usar componente

            item = ft.Container(
                ink=True,
                border_radius=8,
                padding=ft.padding.symmetric(10, 12),
                on_click=lambda e, c=code, n=name: open_product_detail(c, n),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=10,
                            controls=[
                                ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=20, color=ft.Colors.GREY_700),
                                ft.Text(code, size=13, weight=ft.FontWeight.W_600),
                                ft.Text("•", size=12, color=ft.Colors.GREY_500),
                                ft.Text(name, size=13, color=ft.Colors.BLACK87, no_wrap=True),
                            ],
                        ),
                        chip_qty,
                    ],
                ),
            )
            rows.append(item)

        if not rows:
            rows = [cmp.empty_state(ft.Icons.SEARCH_OFF, "Sin resultados. Ajusta tu búsqueda o filtros.")]  # <<---

        search_results_col.controls[:] = rows
        build_recent_chips()
        page.update()

    def render_dashboard_page():
        ui_state["current_view"] = "dashboard"
        # KPIs simples con lo que ya tienes
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        kpi_col = ft.Column(spacing=10)

        def kpi(label: str, value: str, icon=ft.Icons.INSIGHTS):
            return ft.Container(
                padding=ft.padding.all(14), bgcolor=ft.Colors.GREY_50, border_radius=12,
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Column(controls=[ft.Text(label, size=12, color=ft.Colors.GREY_700),
                                        ft.Text(value, size=20, weight=ft.FontWeight.BOLD)]),
                    ft.Icon(icon, size=28, color=ft.Colors.GREY_700)
                ])
            )

        def load():
            # Entradas y salidas de HOY (usa list_movements con filtro days=1 y filtra por fecha == hoy)
            rows = db.list_movements(warehouse_id=None, code_or_alias=None, days=1, limit=10000)
            in_qty = sum(int(r["qty"]) for r in rows if r.get("kind") in ("IN","ADJ+") and str(r.get("ts","")).startswith(today))
            out_qty= sum(int(r["qty"]) for r in rows if r.get("kind") in ("OUT","ADJ-") and str(r.get("ts","")).startswith(today))

            # Productos en bajo stock (usa ya tu db.list_low_stock para primer almacén si existe)
            low_total = 0
            ws = db.list_warehouses()
            if ws:
                for w in ws:
                    try:
                        low_total += len(db.list_low_stock(w["id"], limit=999999))
                    except: pass

            # Productos sin movimiento últimos 30 días (aproximación)
            cold = 0
            try:
                last30 = db.list_movements(warehouse_id=None, code_or_alias=None, days=30, limit=100000)
                moved = {r["code"] for r in last30}
                all_codes = {p["code"] for p in (db.list_products() or [])}
                cold = len(all_codes - moved)
            except: pass

            kpi_col.controls[:] = [
                kpi("Entradas de hoy", str(in_qty), ft.Icons.LOGIN),
                kpi("Salidas de hoy", str(out_qty), ft.Icons.LOGOUT),
                kpi("Items en stock bajo (total)", str(low_total), ft.Icons.WARNING),
                kpi("Sin rotación (30 días)", str(cold), ft.Icons.AC_UNIT),
            ]
            page.update()

        header = cmp.header_row("Dashboard – Hoy", [])
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(expand=True, padding=ft.padding.all(12), content=kpi_col),
        ]; page.update(); load()


    def render_locations_page():
        ui_state["current_view"] = "locations"
        warehouses = db.list_warehouses()
        if not warehouses:
            content_column.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Crea un almacén primero.")]
            page.update(); return

        wh_dd = ft.Dropdown(label="Almacén", width=260,
                            options=[ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses],
                            value=str(warehouses[0]["id"]),
                            on_change=lambda e: load())
        code_tf = ft.TextField(label="Código ubicación (ej: A-01-01)", width=200)
        name_tf = ft.TextField(label="Nombre", width=240)
        list_col = ft.Column(spacing=6, height=380, scroll=ft.ScrollMode.AUTO)

        # Asignación rápida de ubicación por producto
        prod_code_tf = ft.TextField(label="Producto", width=160)
        location_dd = ft.Dropdown(label="Ubicación", width=220)

        def add_location(e):
            if not code_tf.value:
                notify("warning","Código requerido."); return
            try:
                db.add_location(int(wh_dd.value), code_tf.value.strip(), name_tf.value or None)
                code_tf.value=""; name_tf.value=""; notify("success","Ubicación agregada."); load()
            except Exception as ex:
                notify("error", f"No se pudo agregar: {ex}")

        def assign_location(e):
            try:
                wid = int(wh_dd.value)
                loc_id = int(location_dd.value) if location_dd.value else None
                code = (prod_code_tf.value or "").strip()
                if not (code and loc_id): notify("warning","Selecciona producto y ubicación."); return
                db.set_product_location(wid, code, loc_id)
                notify("success","Ubicación asignada.")
            except Exception as ex:
                notify("error", f"No se pudo asignar: {ex}")

        def load():
            list_col.controls[:] = []
            wid = int(wh_dd.value)
            locs = db.list_locations(wid)
            location_dd.options = [ft.dropdown.Option(str(l["id"]), text=f"{l['code']} {l.get('name') or ''}") for l in locs]
            for l in locs:
                list_col.controls.append(
                    ft.Container(padding=ft.padding.symmetric(8,10), bgcolor=ft.Colors.GREY_50, border_radius=8,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Text(f"{l['code']}", size=13, weight=ft.FontWeight.W_600),
                                    ft.Text(l.get("name") or "—", size=12, color=ft.Colors.GREY_700)
                                ]))
                )
            if not list_col.controls:
                list_col.controls[:] = [cmp.empty_state(ft.Icons.MAP, "Sin ubicaciones.")]
            page.update()

        header = cmp.header_row("Ubicaciones internas", [])
        form_add = ft.Row(wrap=True, spacing=10, controls=[wh_dd, code_tf, name_tf,
                                                        ft.FilledButton("Agregar", icon=ft.Icons.SAVE, on_click=add_location)])
        form_assign = ft.Row(wrap=True, spacing=10, controls=[prod_code_tf, location_dd,
                                                            ft.FilledTonalButton("Asignar a producto", icon=ft.Icons.LABEL,
                                                                                on_click=assign_location)])
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=form_add),
            ft.Container(padding=ft.padding.only(8,0), content=form_assign),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]; page.update(); load()


    def render_categories_units_page():
        ui_state["current_view"] = "cat_unit"

        code_tf = ft.TextField(label="Código", width=160)
        cat_tf  = ft.TextField(label="Categoría", width=180)
        unit_tf = ft.TextField(label="Unidad (pz/kg/m...)", width=200)
        factor_tf = ft.TextField(label="Factor (1 por defecto)", width=160, keyboard_type=ft.KeyboardType.NUMBER, value="1")

        list_col = ft.Column(spacing=6, height=420, scroll=ft.ScrollMode.AUTO)

        def save(e):
            try:
                f = float(factor_tf.value or "1")
                db.set_product_category_unit((code_tf.value or "").strip(), (cat_tf.value or "").strip() or None,
                                            (unit_tf.value or "").strip() or None, f)
                notify("success","Actualizado.")
                load()
            except Exception as ex:
                notify("error", f"No se pudo actualizar: {ex}")

        def load():
            list_col.controls[:] = []
            for p in db.list_products():
                list_col.controls.append(
                    ft.Container(padding=ft.padding.symmetric(8,10), bgcolor=ft.Colors.GREY_50, border_radius=8,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Text(f"{p['code']} – {p['name']}", size=13, weight=ft.FontWeight.W_600),
                                    ft.Text(f"{p.get('category') or '—'} | {p.get('unit') or '—'} x {p.get('unit_factor') or 1}", size=12, color=ft.Colors.GREY_700)
                                ]))
                )
            if not list_col.controls:
                list_col.controls[:] = [cmp.empty_state(ft.Icons.CATEGORY, "No hay productos.")]
            page.update()

        header = cmp.header_row("Categorías y unidades", [])
        form = ft.Row(wrap=True, spacing=10, controls=[code_tf, cat_tf, unit_tf, factor_tf,
                                                    ft.FilledButton("Guardar", icon=ft.Icons.SAVE, on_click=save)])
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=form),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]; page.update(); load()


    def render_suppliers_page():
        ui_state["current_view"] = "suppliers"
        name_tf = ft.TextField(label="Nombre", width=280)
        contact_tf = ft.TextField(label="Contacto", width=280)

        list_col = ft.Column(spacing=6, height=420, scroll=ft.ScrollMode.AUTO)

        def add_supplier(e):
            n = (name_tf.value or "").strip()
            if not n: notify("warning","Nombre requerido."); return
            try:
                db.add_supplier(n, contact_tf.value or None)
                name_tf.value = ""; contact_tf.value=""; notify("success","Proveedor agregado."); load()
            except Exception as ex:
                notify("error", f"No se pudo guardar: {ex}")

        def load():
            list_col.controls[:] = []
            for r in db.list_suppliers():
                list_col.controls.append(
                    ft.Container(padding=ft.padding.symmetric(8,10), bgcolor=ft.Colors.GREY_50, border_radius=8,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Text(f"{r['id']:04d} – {r['name']}", size=13, weight=ft.FontWeight.W_600),
                                    ft.Text(r.get("contact") or "—", size=12, color=ft.Colors.GREY_700)
                                ]))
                )
            if not list_col.controls:
                list_col.controls[:] = [cmp.empty_state(ft.Icons.SUPPORT_AGENT, "Sin proveedores.")]
            page.update()

        header = cmp.header_row("Proveedores", [])
        form = ft.Row(wrap=True, spacing=10, controls=[name_tf, contact_tf,
                                                    ft.FilledButton("Agregar", icon=ft.Icons.SAVE, on_click=add_supplier)])
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=form),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]; page.update(); load()

    def render_customers_page():
        ui_state["current_view"] = "customers"
        name_tf = ft.TextField(label="Nombre", width=280)
        contact_tf = ft.TextField(label="Contacto", width=280)
        list_col = ft.Column(spacing=6, height=420, scroll=ft.ScrollMode.AUTO)

        def add_customer(e):
            n = (name_tf.value or "").strip()
            if not n: notify("warning","Nombre requerido."); return
            try:
                db.add_customer(n, contact_tf.value or None)
                name_tf.value = ""; contact_tf.value=""; notify("success","Cliente agregado."); load()
            except Exception as ex:
                notify("error", f"No se pudo guardar: {ex}")

        def load():
            list_col.controls[:] = []
            for r in db.list_customers():
                list_col.controls.append(
                    ft.Container(padding=ft.padding.symmetric(8,10), bgcolor=ft.Colors.GREY_50, border_radius=8,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Text(f"{r['id']:04d} – {r['name']}", size=13, weight=ft.FontWeight.W_600),
                                    ft.Text(r.get("contact") or "—", size=12, color=ft.Colors.GREY_700)
                                ]))
                )
            if not list_col.controls:
                list_col.controls[:] = [cmp.empty_state(ft.Icons.PERSON, "Sin clientes.")]
            page.update()

        header = cmp.header_row("Clientes", [])
        form = ft.Row(wrap=True, spacing=10, controls=[name_tf, contact_tf,
                                                    ft.FilledButton("Agregar", icon=ft.Icons.SAVE, on_click=add_customer)])
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=form),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]; page.update(); load()


    def render_replenishment_rules_page():
        ui_state["current_view"] = "rules"
        warehouses = db.list_warehouses()
        if not warehouses:
            content_column.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Crea un almacén primero.")]
            page.update(); return

        wh_dd = ft.Dropdown(label="Almacén", width=260,
                            options=[ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses],
                            value=str(warehouses[0]["id"]))
        code_tf = ft.TextField(label="Código", width=180)
        min_tf  = ft.TextField(label="Mínimo", width=120, keyboard_type=ft.KeyboardType.NUMBER, value="0")
        max_tf  = ft.TextField(label="Máximo", width=120, keyboard_type=ft.KeyboardType.NUMBER, value="0")
        rp_tf   = ft.TextField(label="Reorden", width=120, keyboard_type=ft.KeyboardType.NUMBER, value="0")
        mul_tf  = ft.TextField(label="Múltiplo", width=120, keyboard_type=ft.KeyboardType.NUMBER, value="1")
        lt_tf   = ft.TextField(label="Lead time (días)", width=160, keyboard_type=ft.KeyboardType.NUMBER, value="0")

        list_col = ft.Column(spacing=6, height=420, scroll=ft.ScrollMode.AUTO)

        def save_rule(e):
            try:
                wid = int(wh_dd.value)
                db.set_replenishment_rule(
                    code=(code_tf.value or "").strip(),
                    warehouse_id=wid,
                    min_qty=int(min_tf.value or "0"),
                    max_qty=int(max_tf.value or "0"),
                    reorder_point=int(rp_tf.value or "0"),
                    multiple=max(1, int(mul_tf.value or "1")),
                    lead_time_days=int(lt_tf.value or "0")
                )
                notify("success","Regla guardada.")
                load()
            except Exception as ex:
                notify("error", f"No se pudo guardar: {ex}")

        def load():
            list_col.controls.clear()
            wid = int(wh_dd.value)
            rows = db.list_replenishment_rules(wid, limit=1000)
            for r in rows:
                list_col.controls.append(
                    ft.Container(
                        padding=ft.padding.symmetric(8,10), bgcolor=ft.Colors.GREY_50, border_radius=8,
                        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                            ft.Text(f"{r['code']} – {r['name']}", size=13, weight=ft.FontWeight.W_600),
                            ft.Text(f"min:{r['min_qty']} max:{r['max_qty']} RP:{r['reorder_point']} mult:{r['multiple']} LT:{r['lead_time_days']}d",
                                size=12, color=ft.Colors.GREY_700)
                        ])
                    )
                )
            if not rows:
                list_col.controls[:] = [cmp.empty_state(ft.Icons.TUNE, "No hay reglas registradas.")]
            page.update()

        header = cmp.header_row("Reglas de reabastecimiento", [])
        form = ft.Row(wrap=True, spacing=10, controls=[wh_dd, code_tf, min_tf, max_tf, rp_tf, mul_tf, lt_tf,
                                                    ft.FilledButton("Guardar", icon=ft.Icons.SAVE, on_click=save_rule)])
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=form),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]
        page.update(); load()


    def render_cycle_counts_page():
        ui_state["current_view"] = "counts"
        warehouses = db.list_warehouses()
        if not warehouses:
            content_column.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Crea un almacén primero.")]
            page.update(); return

        wh_dd = ft.Dropdown(label="Almacén", width=260,
                            options=[ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses],
                            value=str(warehouses[0]["id"]))
        note_tf = ft.TextField(label="Nota del conteo", width=520)
        category_dd = ft.Dropdown(label="Categoría (opcional)", width=260,
                                options=[ft.dropdown.Option(c) for c in (db.list_categories() or [])])

        session_id_box = ft.Text("Sesión: —", size=12)
        list_col = ft.Column(spacing=6, height=420, scroll=ft.ScrollMode.AUTO)
        lines = []  # [{"code","name","sys","counted"}]

        def generate_session(e):
            wid = int(wh_dd.value)
            sid = db.create_count_session(wid, note_tf.value or None)
            session_id_box.value = f"Sesión: {sid}"
            # colectar productos del almacén (+ filtro categ.)
            items = db.list_products_by_warehouse(wid)
            cat = category_dd.value
            if cat:
                items = [it for it in items if (it.get("category") == cat)]
            stock = db.get_stock_map(wid)
            for it in items:
                sysq = int(stock.get(it["code"], 0))
                db.add_count_line(sid, it["code"], sysq)
            load_session(sid)

        def load_session(sid: int):
            nonlocal lines
            rows = db.list_count_lines(sid)
            name_map = {p["code"]: p["name"] for p in db.list_products() or []}
            lines = [{"code":r["code"], "name":name_map.get(r["code"], r["code"]),
                    "sys":int(r["sys_qty"]), "counted": (r["counted_qty"] if r["counted_qty"] is not None else r["sys_qty"])}
                    for r in rows]
            rebuild()

        def set_counted(code: str, val: str):
            sid = int(session_id_box.value.split(":")[1].strip())
            try: n = int(val); n = 0 if n < 0 else n
            except: return
            db.update_count_line(sid, code, n)
            for x in lines:
                if x["code"] == code: x["counted"] = n; break

        def rebuild():
            rows = []
            for r in lines:
                rows.append(
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Text(f"{r['code']} – {r['name']}", size=13),
                        ft.Row(controls=[
                            ft.Text(f"Sist.: {r['sys']}", size=12, color=ft.Colors.GREY_700),
                            ft.Text("Conteo:", size=12),
                            ft.TextField(value=str(r["counted"]), width=100, keyboard_type=ft.KeyboardType.NUMBER,
                                        on_change=lambda e, _c=r["code"]: set_counted(_c, e.control.value))
                        ])
                    ])
                )
            if not rows:
                rows = [cmp.empty_state(ft.Icons.CHECKLIST, "Genera una sesión de conteo.")]
            list_col.controls[:] = rows; page.update()

        def reconcile(e):
            txt = session_id_box.value
            if "Sesión:" not in txt: return
            sid = int(txt.split(":")[1].strip())
            wid = int(wh_dd.value)
            doc_id = db.reconcile_count_to_adjustments(
                sid, wid,
                create_movement_doc=db.create_movement_doc,
                inc_fn=db.increment_stock,
                dec_fn=db.decrement_stock
            )
            if doc_id:
                notify("success", f"Conteo conciliado. Doc #{doc_id}")
                rebuild()
            else:
                notify("warning","No hubo diferencias.")

        header = cmp.header_row("Conteos cíclicos", [
            ft.TextButton("Ver almacenes", icon=ft.Icons.WAREHOUSE, on_click=lambda e: render_warehouses()),
        ])
        filtros = ft.Row(wrap=True, spacing=10, controls=[wh_dd, category_dd, note_tf])
        actions = ft.Row(spacing=10, controls=[
            ft.FilledButton("Generar sesión", icon=ft.Icons.ADD_TASK, on_click=generate_session),
            ft.FilledTonalButton("Conciliar diferencias", icon=ft.Icons.DONE_ALL, on_click=reconcile),
            session_id_box
        ])

        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=filtros),
            ft.Container(padding=ft.padding.only(8,0), content=actions),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]
        page.update()


    def render_adjustments_page():
        ui_state["current_view"] = "adjustments"

        warehouses = db.list_warehouses()
        if not warehouses:
            content_column.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Crea un almacén primero.")]
            page.update(); return

        wh_dd = ft.Dropdown(label="Almacén", width=260,
                            options=[ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses],
                            value=str(warehouses[0]["id"]))
        reason_dd = ft.Dropdown(label="Motivo", width=220,
                                options=[ft.dropdown.Option(x) for x in ["merma","daño","regularización","otros"]], value="regularización")
        note_tf = ft.TextField(label="Nota", width=520)

        code_tf = ft.TextField(label="Código / Escáner", width=260, autofocus=True,
                            on_submit=lambda e: add_line((e.control.value or "").strip()))
        sys_qty_txt = ft.Text("—", size=12, color=ft.Colors.GREY_700)
        target_qty_tf = ft.TextField(label="Cantidad objetivo", width=160, keyboard_type=ft.KeyboardType.NUMBER, value="0")

        lines = {}  # code -> {"name":..., "sys":..., "target":...}
        lines_col = ft.Column(spacing=6, height=360, scroll=ft.ScrollMode.AUTO)

        def load_sys_qty(code: str):
            try:
                wid = int(wh_dd.value); stock = db.get_stock_map(wid)
                return int(stock.get(code, 0))
            except: return 0

        def add_line(code: str):
            code_tf.value = ""; page.update()
            if not code: return
            try:
                wid = int(wh_dd.value)
                prods = {p["code"]: p for p in db.list_products_by_warehouse(wid)}
                if code not in prods:
                    notify("warning","Código no pertenece al almacén seleccionado."); return
                sysq = load_sys_qty(code)
                lines[code] = {"name": prods[code]["name"], "sys": sysq, "target": sysq}
                rebuild()
            except Exception as ex:
                notify("error", f"No se pudo agregar: {ex}")

        def set_target(code: str, val: str):
            try: n = int(val); n = 0 if n < 0 else n
            except: n = lines[code]["target"]
            lines[code]["target"] = n

        def rebuild():
            rows = []
            for c, d in lines.items():
                rows.append(
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Text(f"{c} – {d['name']}", size=13),
                        ft.Row(controls=[
                            ft.Text(f"Sist.: {d['sys']}", size=12, color=ft.Colors.GREY_700),
                            ft.Text("→", size=12),
                            ft.TextField(value=str(d["target"]), width=100, keyboard_type=ft.KeyboardType.NUMBER,
                                        on_change=lambda e, _c=c: set_target(_c, e.control.value))
                        ])
                    ])
                )
            if not rows:
                rows = [cmp.empty_state(ft.Icons.EDIT_NOTE, "Captura un código y define la cantidad objetivo.")]
            lines_col.controls[:] = rows
            page.update()

        def apply_adjustment(e):
            if not lines:
                notify("warning","No hay líneas.");
                return
            wid = int(wh_dd.value)
            # crea doc de ajuste
            total_lines = len(lines)
            total_qty = sum(abs(d["target"] - d["sys"]) for d in lines.values())
            doc_id = db.create_movement_doc(
                doc_type="ADJ",
                warehouse_id=wid,
                counterparty="Ajuste Inventario",
                reference=f"ADJ-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                note=f"Motivo: {reason_dd.value}. {note_tf.value or ''}",
                total_lines=total_lines,
                total_qty=total_qty
            )
            db.create_adjustment(wid, reason_dd.value, note_tf.value or "", doc_id)

            # aplicar diferencias
            for c, d in lines.items():
                delta = int(d["target"]) - int(d["sys"])
                if delta > 0:
                    db.increment_stock(c, wid, delta, note=f"Ajuste + ({reason_dd.value})", doc_id=doc_id)
                elif delta < 0:
                    db.decrement_stock(c, wid, -delta, note=f"Ajuste - ({reason_dd.value})", doc_id=doc_id)

            notify("success", f"Ajuste aplicado. Doc #{doc_id}")
            lines.clear(); rebuild()

        header = cmp.header_row("Ajustes de inventario", [
            ft.TextButton("Ver almacenes", icon=ft.Icons.WAREHOUSE, on_click=lambda e: render_warehouses()),
        ])
        filtros = ft.Row(wrap=True, spacing=10, controls=[wh_dd, reason_dd, note_tf])
        captura = ft.Row(wrap=True, spacing=10, controls=[code_tf, ft.Text("Stock:", size=12), sys_qty_txt, target_qty_tf])

        # stock on typing
        code_tf.on_change = lambda e: sys_qty_txt.__setattr__("value", str(load_sys_qty((e.control.value or "").strip()))) or page.update()

        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=filtros),
            ft.Container(padding=ft.padding.only(8,0), content=ft.Text("Captura de líneas", size=12, color=ft.Colors.GREY_700)),
            ft.Container(padding=ft.padding.only(8,0), content=captura),
            ft.Container(expand=True, padding=ft.padding.all(8), content=lines_col),
            ft.Container(padding=ft.padding.all(8), content=ft.FilledButton("Aplicar ajuste", icon=ft.Icons.SAVE, on_click=apply_adjustment,
                                                                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6))))
        ]
        page.update()

    

    def render_search_page():
        ui_state["current_view"] = "search"

        # Opciones de almacén
        wh_options = [ft.dropdown.Option("all", text="Todos los almacenes")]
        try:
            for w in db.list_warehouses():
                wh_options.append(ft.dropdown.Option(str(w["id"]), text=w["name"]))  # FIX paréntesis
        except Exception:
            pass

        def _set_search_wh(val):
            if val == "all" or val is None:
                search_state["warehouse_id"] = None
            else:
                try:
                    search_state["warehouse_id"] = int(val)
                except Exception:
                    search_state["warehouse_id"] = None

        def _set_search_flag(key: str, val: bool): search_state[key] = bool(val)

        def _set_search_threshold(val: str):
            try:
                n = int(val)
                if n < 0:
                    n = 0
            except Exception:
                n = 5
            search_state["low_stock_threshold"] = n

        def _search_reset():
            search_state.update({
                "query": "",
                "warehouse_id": None,
                "in_stock_only": False,
                "include_descr": False,
                "low_stock_only": False,
                "low_stock_threshold": 5,
                "results": [],
            })
            ui_state["current_view"] = "search"

        def _search_open_first():
            if not search_state["results"]:
                return
            q = search_state["query"]
            if q:
                add_recent(q)
            first = search_state["results"][0]
            open_product_detail(first["code"], first["name"])

        wh_dd = ft.Dropdown(
            width=260, label="Almacén", options=wh_options,
            value=("all" if search_state["warehouse_id"] is None else str(search_state["warehouse_id"])),
            on_change=lambda e: (_set_search_wh(e.control.value), search_refresh_results())
        )
        instock_cb = ft.Checkbox(label="Solo con existencia", value=search_state["in_stock_only"],
                                 on_change=lambda e: (_set_search_flag("in_stock_only", e.control.value), search_refresh_results()))
        low_cb = ft.Checkbox(label="Stock bajo", value=search_state["low_stock_only"],
                             on_change=lambda e: (_set_search_flag("low_stock_only", e.control.value), search_refresh_results()))
        low_tf = ft.TextField(width=260, label="Umbral", value=str(search_state["low_stock_threshold"]),
                              keyboard_type=ft.KeyboardType.NUMBER,
                              on_change=lambda e: (_set_search_threshold(e.control.value), search_refresh_results()))
        include_cb = ft.Checkbox(label="Incluir descripción", value=search_state["include_descr"],
                                 on_change=lambda e: (_set_search_flag("include_descr", e.control.value), search_refresh_results()))

        search_tf = ft.TextField(
            ref=search_tf_ref,
            hint_text="Buscar por código, nombre o descripción...",
            autofocus=True,
            border_radius=50,
            border=ft.InputBorder.NONE,
            text_size=20,
            content_padding=ft.padding.symmetric(14, 20),
            on_change=lambda e: (search_state.__setitem__("query", e.control.value or ""), search_refresh_results()),
            on_submit=lambda e: _search_open_first(),
        )

        search_bar = ft.Container(
            bgcolor=ft.Colors.GREY_100,
            border_radius=28,
            padding=ft.padding.symmetric(6, 14),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.SEARCH, color=ft.Colors.GREY_700),
                    ft.Container(expand=True, content=search_tf),
                    ft.Container(
                        padding=ft.padding.symmetric(6, 10),
                        border_radius=14,
                        bgcolor=ft.Colors.GREY_200,
                        content=ft.Text("Ctrl/⌘ + K", size=11, color=ft.Colors.GREY_700),
                    ),
                ],
            ),
        )

        header_row = cmp.header_row(  # <<---
            "Buscar productos",
            [
                ft.TextButton("Ver almacenes", icon=ft.Icons.WAREHOUSE, on_click=lambda e: render_warehouses()),
                ft.TextButton(
                    "Ver productos",
                    icon=ft.Icons.INVENTORY_SHARP,
                    on_click=lambda e: (ui_state.__setitem__("last_warehouse_id", None), render_products_list(None)),
                ),
            ],
        )

        filtros_row = ft.Row(
            wrap=True, spacing=10,
            controls=[wh_dd, instock_cb, low_cb, low_tf, include_cb, ft.Container(),
                      ft.TextButton("Limpiar", icon=ft.Icons.CLEAR_ALL, on_click=lambda e: (_search_reset(), render_search_page()))]
        )

        body = [
            ft.Container(padding=ft.padding.only(8, 0, 8, 8), content=header_row),
            ft.Container(padding=ft.padding.only(8, 6), content=search_bar),
            ft.Container(padding=ft.padding.only(8, 0), content=filtros_row),
            ft.Container(padding=ft.padding.only(8, 4), content=ft.Text("Recientes", size=12, color=ft.Colors.GREY_700)),
            ft.Container(padding=ft.padding.only(8, 0), content=search_recent_row),
            ft.Divider(),
            ft.Container(padding=ft.padding.only(8, 0), content=ft.Text("Resultados", size=12, color=ft.Colors.GREY_700)),
            ft.Container(expand=True, padding=ft.padding.all(8), content=search_results_col),
        ]

        content_column.controls[:] = body
        search_refresh_results()
        page.update()
        try:
            search_tf_ref.current.focus()
        except Exception:
            pass

    # =========================
    #   IMPORTACIÓN / CSV-XLSX
    # =========================
    def import_rows_with_progress(rows: list[dict], warehouse_id: int, replace_mode: bool = False):
        existing = hp.existing_codes_set(db)
        preprocessed = [{
            "code": hp.normalize_string(r["code"]),
            "name": hp.normalize_string(r["name"]),
            "description": hp.normalize_string(r.get("description", "")),
            "qty": int(r.get("qty") or 0)
        } for r in rows]

        total = len(preprocessed)
        prog = ft.ProgressBar(value=0, width=400)
        lbl = ft.Text(f"0 / {total} productos", size=12)

        dlg_prog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Cargando productos..."),
            content=ft.Column([prog, lbl], spacing=10, width=420, height=60),
            shape=ft.RoundedRectangleBorder(radius=8),
            shadow_color=ft.Colors.BLACK38,
            actions=[],
        )
        open_dialog(dlg_prog)

        current_stock = {}
        try:
            for p in db.list_products_by_warehouse(warehouse_id):
                current_stock[str(p["code"])] = int(p.get("qty") or 0)
        except Exception:
            current_stock = {}

        def _link_to_warehouse(code: str, wid: int):
            try:
                if hasattr(db, "is_product_linked") and db.is_product_linked(code, wid):
                    return
            except Exception:
                pass
            if hasattr(db, "link_product_to_warehouse"):
                db.link_product_to_warehouse(code, wid)
            else:
                db.upsert_product(code=code, name=None, description=None, warehouse_id=wid)

        def _set_or_add_stock(code: str, wid: int, qty: int):
            if qty <= 0:
                return
            if replace_mode:
                if hasattr(db, "set_stock"):
                    try:
                        db.set_stock(code, wid, qty, note="Importación (reemplazo)")
                        current_stock[code] = qty
                        return
                    except Exception:
                        pass
                prev = current_stock.get(code, 0)
                delta = qty - prev
                if delta > 0:
                    db.increment_stock(code, wid, delta, note="Importación (ajuste a reemplazo +)")
                elif delta < 0:
                    db.decrement_stock(code, wid, -delta, note="Importación (ajuste a reemplazo -)")
                current_stock[code] = qty
            else:
                db.increment_stock(code, wid, qty, note="Importación (suma)")

        def worker():
            ok = link_ok = err = 0
            for i, r in enumerate(preprocessed, start=1):
                try:
                    code_key = r["code"]
                    if code_key not in existing:
                        db.upsert_product(code=r["code"], name=r["name"], description=r.get("description", ""), warehouse_id=None)
                        existing.add(code_key)
                        ok += 1
                    _link_to_warehouse(code_key, warehouse_id)
                    link_ok += 1
                    _set_or_add_stock(code_key, warehouse_id, int(r.get("qty") or 0))
                except Exception:
                    err += 1

                prog.value = i / total
                lbl.value = f"{i} / {total} productos"
                page.update()

            dlg_prog.open = False
            page.update()
            close_dialog()
            modo = "reemplazo" if replace_mode else "suma"
            msg = f"Importación ({modo}) completada: {ok} nuevos, {link_ok} asociados"
            if err:
                msg += f", {err} con error"
            notify("success", msg)
            render_products_list(warehouse_id)

        threading.Thread(target=worker, daemon=True).start()

    # =========================
    #   ENTRADA / SALIDA
    # =========================
    def focus_entry_field():
        try:
            entry_code_tf.focus()
        except Exception:
            pass
        page.update()

    def focus_exit_field():
        try:
            exit_code_tf.focus()
        except Exception:
            pass
        page.update()

    # ---- ENTRADA ----
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
        focus_entry_field()

    def entry_qty_submit(code: str, val: str):
        try:
            n = int(val)
            n = 1 if n <= 0 else n
        except Exception:
            n = 1
        if code in entry_state["lines"]:
            entry_state["lines"][code]["qty"] = n
        focus_entry_field()

    def entry_render_lines():
        rows = []
        for code, data in entry_state["lines"].items():
            qty_tf = ft.TextField(
                value=str(data["qty"]), width=70, text_align=ft.TextAlign.RIGHT,
                on_change=lambda e, _c=code: entry_update_qty(_c, e.control.value),
                on_submit=lambda e, _c=code: entry_qty_submit(_c, e.control.value),
                keyboard_type=ft.KeyboardType.NUMBER,
            )
            rows.append(ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                               controls=[ft.Text(f"{code} – {data['name']}", size=13), ft.Row(controls=[ft.Text("Cant."), qty_tf])]))
        entry_lines_col.controls = rows
        page.update()

    def entry_update_qty(code: str, val: str):
        try:
            n = int(val)
            n = 1 if n <= 0 else n
        except Exception:
            n = 1
        if code in entry_state["lines"]:
            entry_state["lines"][code]["qty"] = n

    def entry_add_code(raw_code: str):
        code = (raw_code or "").strip()
        entry_code_tf.value = ""
        page.update()
        if not code:
            focus_entry_field()
            return
        wid = entry_state["warehouse_id"]
        try:
            canonical = db.resolve_to_canonical_code(code)
            code = canonical
        except Exception:
            notify("warning", "El código no es válido.")
            pass
        if not wid:
            notify("warning", "Selecciona un almacén.")
            focus_entry_field()
            return
        try:
            prods = db.list_products_by_warehouse(wid)
            mp = {p["code"]: p for p in prods}
            if code not in mp:
                notify("warning", "El código no pertenece a este almacén.")
                focus_entry_field()
                return
            name = mp[code]["name"]
        except Exception as ex:
            notify("error", f"No se pudo validar producto: {ex}")
            focus_entry_field()
            return

        entry_state["lines"].setdefault(code, {"name": name, "qty": 0})
        entry_state["lines"][code]["qty"] += 1
        entry_render_lines()
        focus_entry_field()

    def entry_confirm(e):
        wid = entry_state["warehouse_id"]
        if not wid or not entry_state["lines"]:
            notify("warning", "No hay productos que registrar.")
            focus_entry_field()
            return

        # cerrar el diálogo de entrada antes de abrir el de reporte
        try:
            dlg_entry.open = False
            page.update()
        except Exception:
            pass

        # abrir el diálogo de reporte (encabezado) y ligar las líneas
        _open_report_dialog("IN", wid, entry_state["lines"])


    def open_entry_dialog():
        if not db.list_warehouses():
            open_dialog(alert_no_wh)
            return
        _entry_refresh_warehouse_options()
        entry_state["lines"].clear()
        entry_render_lines()
        page.open(dlg_entry)
        focus_entry_field()

    def open_entry_for(warehouse_id: int):
        if not db.list_warehouses():
            open_dialog(alert_no_wh)
            return
        _entry_refresh_warehouse_options()
        opts = {opt.key for opt in (entry_wh_dd.options or [])}
        if str(warehouse_id) in opts:
            entry_wh_dd.value = str(warehouse_id)
            entry_state["warehouse_id"] = warehouse_id
        else:
            entry_state["warehouse_id"] = int(entry_wh_dd.value) if entry_wh_dd.value else None
        entry_state["lines"].clear()
        entry_render_lines()
        page.open(dlg_entry)
        focus_entry_field()

    # ---- SALIDA ----
    def _exit_refresh_warehouse_options():
        ws = db.list_warehouses()
        exit_wh_dd.options = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in ws]
        if ws:
            exit_wh_dd.value = str(ws[0]["id"])
            exit_state["warehouse_id"] = ws[0]["id"]
        else:
            exit_wh_dd.value = None
            exit_state["warehouse_id"] = None
        page.update()

    def exit_on_wh_change(e):
        exit_state["warehouse_id"] = int(exit_wh_dd.value) if exit_wh_dd.value else None
        exit_render_lines()

    def exit_qty_submit(code: str, val: str):
        try:
            n = int(val)
            n = 1 if n <= 0 else n
        except Exception:
            n = 1
        if code in exit_state["lines"]:
            exit_state["lines"][code]["qty"] = n
        focus_exit_field()

    def exit_render_lines():
        rows = []
        for code, data in exit_state["lines"].items():
            qty_tf = ft.TextField(
                value=str(data["qty"]), width=70, text_align=ft.TextAlign.RIGHT,
                on_change=lambda e, _c=code: exit_update_qty(_c, e.control.value),
                on_submit=lambda e, _c=code: exit_qty_submit(_c, e.control.value),
                keyboard_type=ft.KeyboardType.NUMBER,
            )
            rows.append(ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                               controls=[ft.Text(f"{code} – {data['name']}", size=13), ft.Row(controls=[ft.Text("Cant."), qty_tf])]))
        exit_lines_col.controls[:] = rows
        page.update()

    def exit_update_qty(code: str, val: str):
        try:
            n = int(val)
            n = 1 if n <= 0 else n
        except Exception:
            n = 1
        if code in exit_state["lines"]:
            exit_state["lines"][code]["qty"] = n

    exit_over_list_col = ft.Column(spacing=8, tight=True, width=520, height=220, scroll=ft.ScrollMode.AUTO)

    def apply_exit_caps_and_perform(e):
        wid = exit_over_state.get("warehouse_id")
        for it in exit_over_state.get("items", []):
            code = it["code"]
            avail = int(it["avail"] or 0)
            if code in exit_state["lines"]:
                exit_state["lines"][code]["qty"] = avail
        dlg_exit_over.open = False
        page.update()
        close_dialog()
        perform_exit(wid)

    def show_exit_over_dialog(over_items: list[dict], wid: int):
        exit_over_state["items"] = over_items
        exit_over_state["warehouse_id"] = wid
        rows = []
        for it in over_items:
            rows.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(f"{it['code']} – {it['name']}", size=12),
                        ft.Text(f"Solicitado: {it['req']} • Máx: {it['avail']}", size=12, weight=ft.FontWeight.W_600),
                    ]
                )
            )
        exit_over_list_col.controls = rows
        open_dialog(dlg_exit_over)

    def perform_exit(wid: int | None):
        if not wid:
            notify("warning", "Selecciona un almacén.")
            focus_exit_field()
            return
        if not exit_state["lines"]:
            notify("warning", "No hay productos que registrar.")
            focus_exit_field()
            return

        total_items = 0
        for code, data in exit_state["lines"].items():
            qty = int(data["qty"] or 0)
            if qty > 0:
                db.decrement_stock(code, wid, qty, note="Salida manual")
                total_items += qty

        try:
            dlg_exit.open = False
        except Exception:
            pass
        page.update()
        close_dialog()

        if ui_state.get("last_warehouse_id") == wid:
            render_products_list(wid)
            page.update()

        notify("success", f"Salida registrada: {len(exit_state['lines'])} productos, {total_items} unidades.")
        exit_state["lines"].clear()

    def exit_add_code(raw_code: str):
        code = (raw_code or "").strip()
        exit_code_tf.value = ""
        page.update()
        if not code:
            focus_exit_field()
            return

        wid = exit_state["warehouse_id"]
        if not wid:
            notify("warning", "Selecciona un almacén.")
            focus_exit_field()
            return

        try:
            prods = db.list_products_by_warehouse(wid)
            mp = {p["code"]: p for p in prods}
            if code not in mp:
                notify("warning", "El código no pertenece a este almacén.")
                focus_exit_field()
                return
            name = mp[code]["name"]
        except Exception as ex:
            notify("error", f"No se pudo validar producto: {ex}")
            focus_exit_field()
            return

        if code in exit_state["lines"]:
            exit_state["lines"][code]["qty"] += 1
        else:
            exit_state["lines"][code] = {"name": name, "qty": 1}

        exit_render_lines()
        focus_exit_field()

    def exit_confirm(e):
        wid = exit_state["warehouse_id"]
        if not wid or not exit_state["lines"]:
            notify("warning", "No hay productos que registrar.")
            focus_exit_field()
            return

        stock = hp.get_stock_map(db, wid)
        over = []
        for code, data in exit_state["lines"].items():
            req = int(data.get("qty") or 0)
            avail = int(stock.get(code, 0))
            if req > avail:
                over.append({"code": code, "name": data.get("name", ""), "req": req, "avail": avail})

        if over:
            notify("error", "No se puede extraer más productos que los que están en existencia.")
            show_exit_over_dialog(over, wid)
            return

        # perform_exit(wid)
        _open_report_dialog("OUT", wid, exit_state["lines"])

    def exit_clear(e):
        exit_state["lines"].clear()
        exit_render_lines()
        focus_exit_field()

    def open_exit_dialog():
        if not db.list_warehouses():
            open_dialog(alert_no_wh)
            return
        _exit_refresh_warehouse_options()
        exit_state["lines"].clear()
        exit_render_lines()
        page.open(dlg_exit)
        focus_exit_field()

    def open_exit_for(warehouse_id: int):
        if not db.list_warehouses():
            open_dialog(alert_no_wh)
            return
        _exit_refresh_warehouse_options()
        opts = {opt.key for opt in (exit_wh_dd.options or [])}
        if str(warehouse_id) in opts:
            exit_wh_dd.value = str(warehouse_id)
            exit_state["warehouse_id"] = warehouse_id
        else:
            exit_state["warehouse_id"] = int(exit_wh_dd.value) if exit_wh_dd.value else None
        exit_state["lines"].clear()
        exit_render_lines()
        page.open(dlg_exit)
        focus_exit_field()


    # ======= REPORTE (encabezado del documento) =======
    report_context = {"mode": None, "warehouse_id": None, "lines": None}  # mode: 'IN'|'OUT'
    report_reference_tf   = ft.TextField(label="Referencia / Folio", width=260)
    report_counterparty_tf= ft.TextField(label="Persona / Cliente / Proveedor", width=260)
    report_note_tf        = ft.TextField(label="Nota (opcional)", width=520)

    def _open_report_dialog(mode: str, warehouse_id: int, lines_dict: dict):
        report_context.update({"mode": mode, "warehouse_id": warehouse_id, "lines": lines_dict})
        report_reference_tf.value = ""
        report_counterparty_tf.value = ""
        report_note_tf.value = ""
        page.open(dlg_report)

    def _do_report_and_apply(e):
        mode = report_context.get("mode")
        wid  = report_context.get("warehouse_id")
        lines = report_context.get("lines") or {}
        if mode not in ("IN", "OUT") or not wid or not lines:
            notify("warning", "No hay datos para generar el reporte."); 
            try: dlg_report.open = False; page.update(); close_dialog()
            except: pass
            return

        # totales
        total_lines = len([1 for _, d in lines.items() if int(d.get("qty") or 0) > 0])
        total_qty = sum(int(d.get("qty") or 0) for d in lines.values())

        # crear encabezado y obtener doc_id
        try:
            doc_id = db.create_movement_doc(
                doc_type=mode,
                warehouse_id=wid,
                counterparty=(report_counterparty_tf.value or ""),
                reference=(report_reference_tf.value or ""),
                note=(report_note_tf.value or ""),
                total_lines=total_lines,
                total_qty=total_qty,
            )
        except Exception as ex:
            notify("error", f"No se pudo crear el reporte: {ex}")
            return

        # aplicar movimientos ligados al doc_id
        try:
            if mode == "IN":
                for code, data in lines.items():
                    qty = int(data.get("qty") or 0)
                    if qty > 0:
                        db.increment_stock(code, wid, qty, note="Entrada manual", doc_id=doc_id)
            else:  # OUT
                for code, data in lines.items():
                    qty = int(data.get("qty") or 0)
                    if qty > 0:
                        db.decrement_stock(code, wid, qty, note="Salida manual", doc_id=doc_id)
        except Exception as ex:
            notify("error", f"Error al registrar líneas: {ex}")
            return

        try:
            dlg_report.open = False
            page.update()
            close_dialog()
        except:
            pass

        # refrescar si procede
        if ui_state.get("last_warehouse_id") == wid:
            render_products_list(wid)

        # Exportar CSV del reporte
        try:
            out_csv = export_report_csv(doc_id)
            out_pdf = export_report_pdf(doc_id)  # <- opcional si tienes reportlab instalado
            notify("success", f"Reportes: {out_csv or '—'} | {out_pdf or '—'}")
        except Exception as ex:
            notify("error", f"Reporte creado, pero falló la exportación: {ex}")

        # limpiar líneas
        if mode == "IN":
            entry_state["lines"].clear()
        else:
            exit_state["lines"].clear()

    dlg_report = ft.AlertDialog(
        modal=True,
        title=ft.Text("Generar reporte de movimiento"),
        content=ft.Column(
            spacing=10, width=580, height=220, scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Row(spacing=10, controls=[report_reference_tf, report_counterparty_tf]),
                report_note_tf,
                ft.Text("Se registrará un comprobante y cada línea quedará ligada a él.", size=11, color=ft.Colors.GREY_700),
            ]
        ),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_report,"open",False), page.update(), close_dialog())),
            ft.FilledButton("Generar y registrar", icon=ft.Icons.DESCRIPTION, on_click=_do_report_and_apply,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )



    # =============== TRANSFERENCIA DE STOCK ===============
    transfer_src_dd = ft.Dropdown(label="Desde (origen)", width=360)
    transfer_dst_dd = ft.Dropdown(label="Hacia (destino)", width=360)
    transfer_code_tf = ft.TextField(label="Código / Alias (escáner)", width=240, autofocus=True)
    transfer_qty_tf  = ft.TextField(label="Cantidad", width=100, keyboard_type=ft.KeyboardType.NUMBER, value="1")
    transfer_note_tf = ft.TextField(label="Nota (opcional)", width=520)

    def _refresh_transfer_dd():
        ws = db.list_warehouses()
        # crea listas NUEVAS para cada dropdown (no compartidas)
        src_opts = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in ws]
        dst_opts = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in ws]

        transfer_src_dd.options = src_opts
        transfer_dst_dd.options = dst_opts

        transfer_src_dd.value = src_opts[0].key if src_opts else None
        transfer_dst_dd.value = (dst_opts[1].key if len(dst_opts) > 1
                                else (dst_opts[0].key if dst_opts else None))
        # refleja los valores en UI
        page.update()


    def transfer_do(e=None):
        code = (transfer_code_tf.value or "").strip()
        if not code:
            notify("warning","Captura un código/alias."); return
        try:
            qty = int(transfer_qty_tf.value or "1")
            if qty <= 0: qty = 1
        except:
            qty = 1
        try:
            src = int(transfer_src_dd.value) if transfer_src_dd.value else None
            dst = int(transfer_dst_dd.value) if transfer_dst_dd.value else None
        except:
            src = dst = None

        if not (src and dst):
            notify("warning","Selecciona almacenes origen y destino."); return
        if src == dst:
            notify("warning","Origen y destino no pueden ser iguales."); return

        try:
            db.transfer_stock(code, src, dst, qty, note=(transfer_note_tf.value or "Transferencia"))
        except Exception as ex:
            notify("error", f"No se pudo transferir: {ex}")
            return

        close_dialog()
        page.update()

        # Si estás viendo el almacén origen o destino, refresca
        lwid = ui_state.get("last_warehouse_id")
        if lwid in (src, dst):
            render_products_list(lwid)
        notify("success", f"Transferencia realizada ({qty} uds).")

    dlg_transfer = ft.AlertDialog(
        modal=True, title=ft.Text("Transferir stock"),
        content=ft.Column(
            spacing=10, width=350, height=320, scroll=ft.ScrollMode.AUTO,
            controls=[
                transfer_src_dd, transfer_dst_dd,
                ft.Row(spacing=10, controls=[transfer_code_tf, transfer_qty_tf]),
                transfer_note_tf,
            ]
        ),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_transfer,"open",False), page.update(), close_dialog())),
            ft.FilledButton("Transferir", icon=ft.Icons.SEND, on_click=transfer_do,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=8),
    )

    def open_transfer_dialog():
        if not db.list_warehouses():
            open_dialog(alert_no_wh); return
        _refresh_transfer_dd()
        transfer_code_tf.value = ""
        transfer_qty_tf.value = "1"
        transfer_note_tf.value = ""
        open_dialog(dlg_transfer)
        try: transfer_code_tf.focus()
        except: pass

    # =============== REPORTES: MOVIMIENTOS ===============
    def render_movements_page():
        ui_state["current_view"] = "movs"

        # --------- Filtros ----------
        wh_opts = [ft.dropdown.Option("all", text="Todos los almacenes")]
        try:
            for w in db.list_warehouses():
                wh_opts.append(ft.dropdown.Option(str(w["id"]), text=w["name"]))
        except Exception:
            pass

        wh_dd   = ft.Dropdown(label="Almacén", width=240, options=wh_opts, value="all")
        code_tf = ft.TextField(label="Código / Alias (opcional)", width=220, on_submit=lambda e: load())
        days_tf = ft.TextField(label="Últimos N días", width=140, value="30",
                            keyboard_type=ft.KeyboardType.NUMBER, on_submit=lambda e: load())
        limit_tf= ft.TextField(label="Límite", width=120, value="300",
                            keyboard_type=ft.KeyboardType.NUMBER, on_submit=lambda e: load())

        list_col = ft.Column(spacing=4, height=460, scroll=ft.ScrollMode.AUTO)

        def load():
            # Lee filtros
            try:
                wid = None if wh_dd.value == "all" else int(wh_dd.value)
            except Exception:
                wid = None

            code = (code_tf.value or "").strip() or None

            try:
                days = int(days_tf.value or "30")
                if days <= 0:
                    days = None
            except Exception:
                days = None

            try:
                lim = int(limit_tf.value or "300")
                if lim <= 0:
                    lim = 300
            except Exception:
                lim = 300

            # Consulta
            try:
                rows = db.list_movements(warehouse_id=wid, code_or_alias=code, days=days, limit=lim)
            except Exception as ex:
                notify("error", f"No se pudieron listar movimientos: {ex}")
                rows = []

            # Render de ítems
            items = []
            for r in rows:
                badge = cmp.movement_badge(r.get("kind", ""))

                # Extra de documento (si el movimiento está ligado a un reporte)
                doc_bits = []
                if r.get("doc_id"):
                    doc_bits.append(ft.Text(f'Doc #{r["doc_id"]}', size=11, color=ft.Colors.GREY_700))
                if r.get("doc_reference"):
                    doc_bits.append(ft.Text(f'Ref: {r["doc_reference"]}', size=11, color=ft.Colors.GREY_700))
                if r.get("doc_counterparty"):
                    doc_bits.append(ft.Text(f'Con: {r["doc_counterparty"]}', size=11, color=ft.Colors.GREY_700))

                # Botones de exportación (si hay Doc #)
                export_row = ft.Row(spacing=4)
                if r.get("doc_id"):
                    d = int(r["doc_id"])
                    export_row.controls = [
                        ft.IconButton(
                            icon=ft.Icons.DOWNLOAD, tooltip="Exportar CSV",
                            on_click=lambda e, _d=d: export_doc_and_notify(_d, "csv"),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                            icon_size=18, width=34, height=34
                        ),
                        ft.IconButton(
                            icon=ft.Icons.PICTURE_AS_PDF, tooltip="Exportar PDF",
                            on_click=lambda e, _d=d: export_doc_and_notify(_d, "pdf"),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                            icon_size=18, width=34, height=34
                        ),
                    ]

                left_col = ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(f'{r.get("ts","")} • {r.get("warehouse","")}', size=12, color=ft.Colors.GREY_700),
                        ft.Text(f'{r.get("code","")} – {r.get("product","")}', size=13, weight=ft.FontWeight.W_600),
                        *doc_bits,
                        ft.Text(r.get("note") or "—", size=11, color=ft.Colors.GREY_700),
                        export_row if r.get("doc_id") else ft.Container(),
                    ],
                )

                qty_and_badge = ft.Row(
                    spacing=8,
                    controls=[ft.Text(str(r.get("qty", 0)), size=14, weight=ft.FontWeight.BOLD), badge],
                )

                items.append(
                    ft.Container(
                        padding=ft.padding.symmetric(8, 10),
                        border_radius=8,
                        bgcolor=ft.Colors.GREY_50,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[left_col, qty_and_badge],
                        ),
                    )
                )

            if not items:
                items = [cmp.empty_state(ft.Icons.INBOX, "No se encontraron movimientos con esos filtros.")]

            list_col.controls[:] = items
            page.update()

        # Header y filtros
        header = cmp.header_row(
            "Movimientos",
            [
                ft.TextButton("Refrescar", icon=ft.Icons.REFRESH, on_click=lambda e: load()),
                ft.TextButton("Ver almacenes", icon=ft.Icons.WAREHOUSE, on_click=lambda e: render_warehouses()),
            ],
        )

        filtros = ft.Row(
            wrap=True,
            spacing=10,
            controls=[
                wh_dd,
                code_tf,
                days_tf,
                limit_tf,
                ft.FilledTonalButton("Aplicar filtros", icon=ft.Icons.FILTER_ALT, on_click=lambda e: load(), height=50, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
            ],
        )

        # Monta vista
        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8, 0, 8, 8), content=header),
            ft.Container(padding=ft.padding.only(8, 0), content=filtros),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]
        page.update()
        load()



    # =============== REPORTES: STOCK BAJO ===============
    def render_low_stock_page():
        ui_state["current_view"] = "low"

        wh_opts = []
        try:
            for w in db.list_warehouses():
                wh_opts.append(ft.dropdown.Option(str(w["id"]), text=w["name"]))
        except:
            pass
        if not wh_opts:
            content_column.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Crea al menos un almacén para usar esta vista.")]
            page.update(); return

        wh_dd = ft.Dropdown(label="Almacén", width=280, options=wh_opts, value=wh_opts[0].key)
        list_col = ft.Column(spacing=4, height=460, scroll=ft.ScrollMode.AUTO)

        def load():
            try:
                wid = int(wh_dd.value)
            except:
                wid = None
            if not wid:
                list_col.controls[:] = [cmp.empty_state(ft.Icons.WARNING, "Selecciona un almacén.")]
                page.update(); return
            try:
                rows = db.list_low_stock(wid, limit=800)
            except Exception as ex:
                notify("error", f"No se pudo listar stock bajo: {ex}")
                rows = []

            items = []
            for r in rows:
                chip = cmp.quantity_chip(int(r.get("qty") or 0))
                code = r["code"]  # <- evita late binding

                items.append(
                    ft.Container(
                        padding=ft.padding.symmetric(8,10),
                        border_radius=8,
                        bgcolor=ft.Colors.GREY_50,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(f'{code} – {r["name"]}', size=13, weight=ft.FontWeight.W_600),
                                        ft.Text(f'Umbral: {r["threshold"]}', size=11, color=ft.Colors.GREY_700),
                                    ],
                                ),
                                ft.Row(
                                    spacing=6,
                                    controls=[
                                        chip,
                                        # --- NUEVO: botón para abrir el diálogo de umbral ---
                                        ft.IconButton(
                                            icon=ft.Icons.TUNE,
                                            tooltip="Definir umbral",
                                            on_click=lambda e, _c=code: set_threshold_dialog(_c),
                                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                                            icon_size=18, width=34, height=34
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    )
                )
            if not items:
                items = [cmp.empty_state(ft.Icons.VERIFIED, "No hay productos en nivel bajo con los umbrales actuales.")]
            list_col.controls[:] = items
            page.update()

        def set_threshold_dialog(r_code: str):
            try:
                wid = int(wh_dd.value)
            except:
                notify("warning","Selecciona almacén"); return
            tf = ft.TextField(label=f"Nuevo umbral para {r_code}", width=240, keyboard_type=ft.KeyboardType.NUMBER, value="5")
            dlg = ft.AlertDialog(
                modal=True, title=ft.Text("Definir umbral"),
                content=tf,
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg,"open",False), page.update(), close_dialog())),
                    ft.FilledButton("Guardar", on_click=lambda e: (
                        db.set_threshold(r_code, wid, int(tf.value or "0")),
                        setattr(dlg,"open",False), page.update(), close_dialog(), load()
                    )),
                ], actions_alignment=ft.MainAxisAlignment.END
            )
            open_dialog(dlg)

        def prompt_set_threshold():
            tf_code = ft.TextField(label="Código del producto", width=240)
            dlg = ft.AlertDialog(
                modal=True, title=ft.Text("Definir umbral"),
                content=tf_code,
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg, "open", False), page.update(), close_dialog())),
                    ft.FilledButton(
                        "Continuar",
                        on_click=lambda e: (
                            setattr(dlg, "open", False), page.update(), close_dialog(),
                            set_threshold_dialog((tf_code.value or "").strip())
                        ),
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END
            )
            open_dialog(dlg)


        header = cmp.header_row(
            "Stock bajo",
            [
                ft.TextButton("Refrescar", icon=ft.Icons.REFRESH, on_click=lambda e: load()),
                ft.TextButton("Definir umbral", icon=ft.Icons.TUNE, on_click=lambda e: prompt_set_threshold()),
                ft.TextButton("Ver almacenes", icon=ft.Icons.WAREHOUSE, on_click=lambda e: render_warehouses()),
            ],
        )
        filt = ft.Row(wrap=True, spacing=10, controls=[wh_dd, ft.FilledTonalButton("Aplicar", icon=ft.Icons.FILTER_ALT, on_click=lambda e: load(), height=50, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)))])

        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8,0,8,8), content=header),
            ft.Container(padding=ft.padding.only(8,0), content=filt),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]
        page.update()
        load()




    # =========================
    #   IMPORT UI HELPERS
    # =========================
    def render_import_products():
        warehouses = db.list_warehouses()
        if not warehouses:
            open_dialog(alert_no_wh)
            return

        hint = ft.Column(
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.FILE_UPLOAD, size=60, color=ft.Colors.GREY_700),
                ft.Text("Arrastra tu archivo CSV o Excel aquí", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("o haz clic para seleccionar un archivo", size=12, color=ft.Colors.GREY_600),
                ft.FilledButton("Cargar archivo", icon=ft.Icons.UPLOAD_FILE,
                                on_click=lambda e: file_picker.pick_files(allow_multiple=False, allowed_extensions=["csv", "CSV", "xlsx", "XLSX", "xls", "XLS"])),
                ft.Text("Campos requeridos: Código, Nombre; Descripción y Existencias (opcional)", size=11, color=ft.Colors.GREY_700),
            ],
        )

        drop_zone = ft.Container(
            width=520, height=280, bgcolor=ft.Colors.GREY_100,
            border=ft.border.all(2, ft.Colors.GREY_300), border_radius=8, ink=True,
            on_click=lambda e: file_picker.pick_files(allow_multiple=False, allowed_extensions=["csv", "xlsx", "xls"]),
            content=hint, alignment=ft.alignment.center,
        )

        content_column.controls[:] = [ft.Container(expand=True, alignment=ft.alignment.center, content=drop_zone)]
        page.update()

    # =========================
    #   ALMACÉN CRUD
    # =========================
    def open_create_dialog():
        name_tf.value = ""
        descr_tf.value = ""
        dlg_create.open = True
        page.open(dlg_create)

    def save_warehouse():
        name = (name_tf.value or "").strip()
        desc = (descr_tf.value or "").strip()
        if not name:
            notify("warning", "El nombre es obligatorio.")
            return
        try:
            db.add_warehouse(name=name, description=desc, color_key=color_dd.value)
            notify("success", f"Almacén '{name}' creado.")
            dlg_create.open = False
            page.update()
            close_dialog()
            render_warehouses()
            page.update()
        except Exception as ex:
            notify("error", f"Error: {ex}")

    def confirm_delete(w):
        warehouse_to_delete["id"] = w["id"]
        warehouse_to_delete["name"] = w["name"]
        open_dialog(dlg_delete)

    def do_delete_warehouse():
        try:
            db.delete_warehouse_cascade(warehouse_to_delete["id"])
            notify("success", f"Almacén '{warehouse_to_delete['name']}' eliminado.")
        except Exception as ex:
            notify("error", f"Error: {ex}")
        finally:
            dlg_delete.open = False
            page.update()
            close_dialog()
            render_warehouses()

    # =========================
    #   MENÚ / HANDLERS
    # =========================
    def handle_menu_item_click(e: ft.ControlEvent):
        cmd = getattr(e.control, "data", None)

        if cmd == "warehouses_view":
            render_warehouses(); set_appbar_text("Ver almacenes")
        elif cmd == "warehouse_new":
            open_create_dialog(); set_appbar_text("Crear un almacen")
        elif cmd == "products_import":
            render_import_products(); set_appbar_text("Agregar Lista de Productos")
        elif cmd == "products_view":
            ui_state["last_warehouse_id"] = None
            render_products_list(None); set_appbar_text("Ver productos")
        elif cmd == "search_product":
            render_search_page(); set_appbar_text("Buscar un producto")
        else:
            pass  # los que usan lambda directa no pasan por aquí

    def set_appbar_text(txt: str):
        if appbar_text_ref.current:
            appbar_text_ref.current.value = txt
            page.update()


    # Atajos de teclado globales
    def on_key(e: ft.KeyboardEvent):
        if (e.ctrl and e.key.lower() == "k") or (e.meta and e.key.lower() == "k"):
            render_search_page()
            try:
                if search_tf_ref.current:
                    search_tf_ref.current.focus()
            except Exception:
                pass
        elif e.key == "escape" and ui_state["current_view"] == "search":
            if ui_state.get("last_warehouse_id") is not None:
                render_products_list(ui_state["last_warehouse_id"])
            else:
                render_warehouses()

    page.on_keyboard_event = on_key

        # =============== REPORTES: SUGERENCIA DE COMPRA ===============
    def render_purchase_suggestions_page():
        ui_state["current_view"] = "suggestions"

        # -- Filtros --
        warehouses = db.list_warehouses()
        if not warehouses:
            content_column.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Crea al menos un almacén para usar esta vista.")]
            page.update()
            return

        wh_opts = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses]
        id_to_name = {w["id"]: w["name"] for w in warehouses}

        wh_dd = ft.Dropdown(label="Almacén", width=280, options=wh_opts, value=wh_opts[0].key)
        limit_tf = ft.TextField(label="Límite", width=140, value="1000", keyboard_type=ft.KeyboardType.NUMBER)

        list_col = ft.Column(spacing=4, height=460, scroll=ft.ScrollMode.AUTO)

        def export_csv(rows: list[dict], wid: int):
            try:
                folder = _ensure_reports_dir()
                wh_name = id_to_name.get(wid, f"WH{wid}")
                ts = hp.now_timestamp_compact() if hasattr(hp, "now_timestamp_compact") else ""
                fname = f"{ts}_SUGERENCIAS_{_safe_slug(wh_name)}.csv"
                path = os.path.join(folder, fname)
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["Almacén", wh_name])
                    w.writerow(["Generado", ts or ""])
                    w.writerow([])
                    w.writerow(["Código", "Nombre", "Existencia", "Umbral", "Déficit"])
                    for r in rows:
                        w.writerow([r["code"], r["name"], int(r["qty"] or 0), int(r["threshold"] or 0), int(r["deficit"] or 0)])
                notify("success", f"Exportado CSV: {path}")
            except Exception as ex:
                notify("error", f"No se pudo exportar CSV: {ex}")

        def load():
            # Lee filtros
                try:
                    wid = int(wh_dd.value) if wh_dd.value else None
                except Exception:
                    wid = None
                try:
                    lim = int(limit_tf.value or "1000")
                    if lim <= 0:
                        lim = 1000
                except Exception:
                    lim = 1000

                if not wid:
                    list_col.controls[:] = [cmp.empty_state(ft.Icons.WAREHOUSE, "Selecciona un almacén.")]
                    page.update()
                    return

                # -------- Obtener sugerencias --------
                rows = []
                try:
                    # Si existe la función en tu 'database.py', úsala
                    if hasattr(db, "list_purchase_suggestions"):
                        rows = db.list_purchase_suggestions(wid, limit=lim) or []
                    else:
                        raise AttributeError("db.list_purchase_suggestions no existe")
                except Exception:
                    # Fallback: construir desde 'stock bajo'
                    try:
                        base = db.list_low_stock(wid, limit=lim) or []
                        rows = []
                        for r in base:
                            qty = int(r.get("qty") or 0)
                            thr = int(r.get("threshold") or 0)
                            if thr > 0 and qty < thr:
                                rows.append({
                                    "code": r["code"],
                                    "name": r.get("name") or "",
                                    "qty": qty,
                                    "threshold": thr,
                                    "deficit": thr - qty
                                })
                    except Exception as ex2:
                        notify("error", f"No se pudieron obtener sugerencias: {ex2}")
                        rows = []

                # -------- Render --------
                items = []
                for r in rows:
                    chip_qty = cmp.quantity_chip(int(r.get("qty") or 0))
                    deficit = int(r.get("deficit") or 0)
                    threshold = int(r.get("threshold") or 0)
                    items.append(
                        ft.Container(
                            padding=ft.padding.symmetric(8, 10),
                            border_radius=8,
                            bgcolor=ft.Colors.GREY_50,
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text(f'{r["code"]} – {r["name"]}', size=13, weight=ft.FontWeight.W_600),
                                            ft.Text(f'Existencia: {int(r["qty"] or 0)} • Umbral: {threshold}', size=11, color=ft.Colors.GREY_700),
                                        ],
                                    ),
                                    ft.Row(
                                        spacing=8,
                                        controls=[
                                            ft.Text(f"Déficit: {deficit}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                                            chip_qty,
                                        ],
                                    ),
                                ],
                            ),
                        )
                    )

                if not items:
                    items = [cmp.empty_state(ft.Icons.VERIFIED, "No hay déficit con los umbrales actuales.")]
                list_col.controls[:] = items

                # Botón exportar (dependiente de últimos resultados)
                export_btn.on_click = lambda e, _rows=rows, _wid=wid: export_csv(_rows, _wid)
                export_btn.disabled = (len(rows) == 0)

                page.update()


        header = cmp.header_row(
            "Sugerencia de compra",
            [
                ft.TextButton("Refrescar", icon=ft.Icons.REFRESH, on_click=lambda e: load()),
                ft.TextButton("Ver almacenes", icon=ft.Icons.WAREHOUSE, on_click=lambda e: render_warehouses()),
            ],
        )

        export_btn = ft.FilledTonalButton(
            "Exportar CSV", icon=ft.Icons.DOWNLOAD,
            on_click=lambda e: None,  # se setea tras el load()
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)),
            disabled=True,
            height=50,
        )

        filtros = ft.Row(
            wrap=True,
            spacing=10,
            controls=[wh_dd, limit_tf, ft.FilledTonalButton("Aplicar filtros", icon=ft.Icons.FILTER_ALT,
                                                            on_click=lambda e: load(), height=50,
                                                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
                      export_btn],
        )

        content_column.controls[:] = [
            ft.Container(padding=ft.padding.only(8, 0, 8, 8), content=header),
            ft.Container(padding=ft.padding.only(8, 0), content=filtros),
            ft.Container(expand=True, padding=ft.padding.all(8), content=list_col),
        ]
        page.update()
        load()


    # =========================
    #   UI (COMPONENTES)
    # =========================
    file_picker = ft.FilePicker(on_result=lambda e: (
        ui_state.__setitem__("pending_file", e.files[0]) if e.files else None,
        refresh_pick_wh_dialog_and_open() if e.files else None
    ))
    page.overlay.append(file_picker)

    # ---- Diálogos comunes ----
    alert_no_wh = ft.AlertDialog(
        modal=True,
        title=ft.Text("No hay almacenes"),
        content=ft.Text("Debes crear al menos un almacén antes de continuar."),
        actions=[ft.FilledButton("Crear un almacén", on_click=lambda e: (close_dialog(), open_create_dialog()),
                                 style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # Crear almacén
    name_tf = ft.TextField(label="Nombre del almacén", autofocus=True, width=400)
    descr_tf = ft.TextField(label="Descripción (opcional)", width=400, height=100)
    color_dd = ft.Dropdown(label="Color de tarjeta", width=400, value="slate",
                           options=[ft.dropdown.Option(k, text=k.capitalize()) for k, _ in COLOR_CHOICES])

    dlg_create = ft.AlertDialog(
        modal=True,
        title=ft.Text("Crear un almacén"),
        shape=ft.RoundedRectangleBorder(radius=5),
        content=ft.Column([name_tf, color_dd], tight=True, spacing=10, width=400),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_create, "open", False), page.update(), close_dialog()),
                          style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
            ft.FilledButton("Guardar", on_click=lambda e: save_warehouse(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    dlg_delete = ft.AlertDialog(
        modal=True,
        title=ft.Text("Eliminar almacén"),
        content=ft.Text("Esta acción eliminará el almacén y sus datos relacionados (vínculos/stock). ¿Deseas continuar?"),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_delete, "open", False), page.update(), close_dialog())),
            ft.FilledButton("Eliminar", on_click=lambda e: do_delete_warehouse(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # Importación: elegir almacén
    wh_dd = ft.Dropdown(label="Selecciona un almacén", width=360,
                        on_change=lambda e: ui_state.__setitem__("selected_wh_id", int(e.control.value) if e.control.value else None))
    replace_stock_cb = ft.Checkbox(
        label="Reemplazar existencias en el almacén (no sumar)",
        value=False,
        on_change=lambda e: ui_state.__setitem__("replace_stock", bool(e.control.value)),
    )

    def refresh_pick_wh_dialog_and_open():
        warehouses = db.list_warehouses()
        if not warehouses:
            open_dialog(alert_no_wh)
            return
        wh_options = [ft.dropdown.Option(str(w["id"]), text=w["name"]) for w in warehouses]
        wh_dd.options = wh_options
        wh_dd.value = wh_options[0].key if wh_options else None
        ui_state["selected_wh_id"] = int(wh_dd.value) if wh_dd.value else None
        replace_stock_cb.value = bool(ui_state.get("replace_stock", False))
        page.update()
        open_dialog(dlg_pick_wh)

    def on_pick_wh_confirm(e):
        if ui_state["pending_file"] is None or ui_state["selected_wh_id"] is None:
            notify("warning", "Selecciona un almacén válido.")
            return
        dlg_pick_wh.open = False
        page.update()
        close_dialog()
        try:
            rows = hp.parse_products_from_file(ui_state["pending_file"])
        except ImportError as ie:
            notify("error", str(ie))
            return
        except Exception as ex:
            notify("error", f"Error al leer archivo: {ex}")
            return
        import_rows_with_progress(rows, ui_state["selected_wh_id"], replace_mode=bool(ui_state.get("replace_stock", False)))
        ui_state["pending_file"] = None

    def on_pick_wh_cancel(e):
        dlg_pick_wh.open = False
        page.update()
        close_dialog()
        ui_state["pending_file"] = None
        ui_state["selected_wh_id"] = None

    dlg_pick_wh = ft.AlertDialog(
        modal=True,
        title=ft.Text("¿A qué almacén se agregarán estos productos?"),
        content=ft.Column([wh_dd, replace_stock_cb], spacing=10, width=380, tight=True),
        actions=[ft.TextButton("Cancelar", on_click=on_pick_wh_cancel),
                 ft.FilledButton("Confirmar", on_click=on_pick_wh_confirm, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # Entrada
    entry_wh_dd = ft.Dropdown(label="Almacén", width=360, on_change=entry_on_wh_change)
    entry_code_tf = ft.TextField(
        label="Código / Escáner", autofocus=True, width=360,
        on_submit=lambda e: entry_add_code(e.control.value),
    )
    entry_lines_col = ft.Column(spacing=8, width=520, tight=True, scroll=ft.ScrollMode.ADAPTIVE)

    dlg_entry = ft.AlertDialog(
        modal=True,
        title=ft.Text("Entrada de productos"),
        content=ft.Column(
            width=560, spacing=12,
            controls=[entry_wh_dd, entry_code_tf, ft.Divider(), ft.Text("Productos en esta entrada:", size=12, color=ft.Colors.GREY_700), entry_lines_col],
            height=400, scroll=ft.ScrollMode.AUTO
        ),
        shape=ft.RoundedRectangleBorder(radius=5),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_entry, "open", False), page.update(), close_dialog())),
            ft.FilledButton("Confirmar", on_click=entry_confirm, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # Salida
    exit_wh_dd = ft.Dropdown(label="Almacén", width=360, on_change=exit_on_wh_change)
    exit_code_tf = ft.TextField(
        label="Código / Escáner", autofocus=True, width=360,
        on_submit=lambda e: exit_add_code(e.control.value),
        keyboard_type=ft.KeyboardType.TEXT,
    )
    exit_lines_col = ft.Column(spacing=8, width=520, tight=True, scroll=ft.ScrollMode.ADAPTIVE)

    dlg_exit = ft.AlertDialog(
        modal=True,
        title=ft.Text("Salida de productos"),
        content=ft.Column(
            width=560, spacing=12,
            controls=[exit_wh_dd, exit_code_tf, ft.Divider(), ft.Text("Productos en esta salida:", size=12, color=ft.Colors.GREY_700), exit_lines_col],
            height=400, scroll=ft.ScrollMode.AUTO
        ),
        shape=ft.RoundedRectangleBorder(radius=5),
        actions=[
            ft.TextButton("Vaciar", on_click=exit_clear),
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_exit, "open", False), page.update(), close_dialog())),
            ft.FilledButton("Confirmar", on_click=exit_confirm, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    dlg_exit_over = ft.AlertDialog(
        modal=True,
        title=ft.Text("Cantidad solicitada supera la existencia"),
        content=ft.Column(
            controls=[
                ft.Text("Se encontraron productos con cantidad solicitada mayor que la existencia. ¿Deseas extraer la cantidad máxima disponible?", size=12),
                ft.Divider(),
                exit_over_list_col,
            ],
            spacing=8, width=560, height=320, scroll=ft.ScrollMode.AUTO,
        ),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg_exit_over, "open", False), page.update(), close_dialog()),
                          style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
            ft.FilledButton("Usar máximos y continuar", on_click=apply_exit_caps_and_perform,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=5),
    )

    # Área de contenido
    content_area = ft.Container(
        padding=ft.padding.only(20, 20, 20, 20),
        content=content_column,
        expand=True,
    )

    # Menú superior (reutilizando menu_item)
    menubar = ft.MenuBar(
        expand=True,
        style=ft.MenuStyle(
            alignment=ft.alignment.top_left, bgcolor=ft.Colors.WHITE,
            mouse_cursor={ft.ControlState.HOVERED: ft.MouseCursor.WAIT, ft.ControlState.DEFAULT: ft.MouseCursor.ZOOM_OUT},
            shape=ft.RoundedRectangleBorder(radius=0),
        ),
        controls=[
        ft.SubmenuButton(
            content=ft.Text("Almacén"),
            controls=[
                cmp.menu_item("Ver almacenes", ft.Icons.INVENTORY, handle_menu_item_click, data="warehouses_view"),
                cmp.menu_item("Crear un almacen", ft.Icons.WAREHOUSE, handle_menu_item_click, data="warehouse_new", disabled=True),
                cmp.menu_item("Transferir stock", ft.Icons.SWAP_HORIZ, lambda e: open_transfer_dialog()),
                cmp.menu_item("Entrada de productos", ft.Icons.QR_CODE, lambda e: open_entry_dialog()),
                cmp.menu_item("Salida de productos", ft.Icons.EXIT_TO_APP, lambda e: open_exit_dialog()),
                cmp.menu_item("Ajustes de inventario", ft.Icons.BUILD, lambda e: render_adjustments_page()),
                cmp.menu_item("Conteos cíclicos", ft.Icons.CHECKLIST, lambda e: render_cycle_counts_page()),
                cmp.menu_item("Ubicaciones internas", ft.Icons.MAP, lambda e: render_locations_page()),

            ],
        ),
        ft.SubmenuButton(
            content=ft.Text("Productos"),
            controls=[
                cmp.menu_item("Ver productos", ft.Icons.INVENTORY_SHARP, handle_menu_item_click, data="products_view"),
                cmp.menu_item("Agregar Lista de Productos", ft.Icons.FILE_OPEN, handle_menu_item_click, data="products_import", disabled=True),
                cmp.menu_item("Categorías y unidades", ft.Icons.CATEGORY, lambda e: render_categories_units_page(), disabled=True),

            ],
        ),
        ft.SubmenuButton(
            content=ft.Text("Buscar"),
            controls=[
                cmp.menu_item("Buscar un producto", ft.Icons.SEARCH, handle_menu_item_click, data="search_product"),
            ],
        ),
        ft.SubmenuButton(
            content=ft.Text("Contrapartes"),
            controls=[
                cmp.menu_item("Proveedores", ft.Icons.SUPPORT_AGENT, lambda e: render_suppliers_page()),
                cmp.menu_item("Clientes", ft.Icons.PERSON, lambda e: render_customers_page()),
            ],
        ),

        # Nuevo Submenu "Reabastecimiento"
        ft.SubmenuButton(
            content=ft.Text("Reabastecimiento"),
            controls=[
                cmp.menu_item("Reglas por producto", ft.Icons.TUNE, lambda e: render_replenishment_rules_page()),
            ],
        ),

        # Nuevo Submenu "Dashboard"
        ft.SubmenuButton(
            content=ft.Text("Dashboard"),
            controls=[
                cmp.menu_item("Hoy", ft.Icons.DASHBOARD, lambda e: render_dashboard_page()),
            ],
        ),
        ft.SubmenuButton(
            content=ft.Text("Reportes"),
            controls=[
                cmp.menu_item("Movimientos", ft.Icons.LIST, lambda e: render_movements_page()),
                cmp.menu_item("Stock bajo", ft.Icons.WARNING, lambda e: render_low_stock_page()),
                cmp.menu_item("Sugerencia de compra", ft.Icons.SHOPPING_CART, lambda e: render_purchase_suggestions_page()),
            ],
        ),
    ],
    )

    # Header ancho completo
    top_bar = ft.Container(
        bgcolor=ft.Colors.WHITE,
        height=56,
        padding=0,
        content=ft.Row(controls=[menubar], expand=True),  # <- fuerza a ocupar el ancho disponible
    )

    # Raíz de la UI
    page.add(
    ft.SafeArea(
        content=ft.Column(
            controls=[
               top_bar,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                content_area,  # <- el cuerpo (expand=True)
            ],
            expand=True,
        ),
        top=True, bottom=True, left=True, right=True, expand=True,
    )
)

    # Arranque en "Almacenes"
    render_warehouses()

if __name__ == "__main__":
    ft.app(target=main)
