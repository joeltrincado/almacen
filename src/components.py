# componentes.py
# Componentes reutilizables de UI para Flet

import flet as ft

# Paleta por defecto para tarjetas
DEFAULT_COLOR_CHOICES = [
    ("slate",  ["#0f172a", "#1f2937"]),
    ("indigo", ["#1e1b4b", "#312e81"]),
    ("emerald",["#064e3b", "#065f46"]),
    ("rose",   ["#7f1d1d", "#9f1239"]),
    ("amber",  ["#78350f", "#92400e"]),
    ("zinc",   ["#18181b", "#27272a"]),
]


# -------------------------
#  Feedback / Notificaciones
# -------------------------
def make_snackbar(kind: str, message: str) -> ft.SnackBar:
    """Devuelve un SnackBar estandarizado (usa page.open(...) afuera)."""
    kind = (kind or "info").lower()
    colors = {
        "success": ft.Colors.GREEN_600,
        "info": ft.Colors.BLUE_600,
        "warning": ft.Colors.AMBER_700,
        "error": ft.Colors.RED_600,
    }
    icons = {
        "success": ft.Icons.CHECK_CIRCLE_ROUNDED,
        "info": ft.Icons.INFO_ROUNDED,
        "warning": ft.Icons.WARNING_AMBER_ROUNDED,
        "error": ft.Icons.ERROR_ROUNDED,
    }
    return ft.SnackBar(
        content=ft.Row(
            controls=[
                ft.Icon(icons.get(kind, ft.Icons.INFO_ROUNDED), color=ft.Colors.WHITE, size=22),
                ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.W_600),
            ],
            spacing=10,
            tight=True,
        ),
        bgcolor=colors.get(kind, ft.Colors.BLUE_600),
        behavior=ft.SnackBarBehavior.FLOATING,
    )


# -------------------------
#  Estilos / decoraciones
# -------------------------
def gradient_for(key: str, color_choices: list[tuple[str, list[str]]] = None) -> ft.LinearGradient:
    """Gradient para las tarjetas de almacén."""
    color_choices = color_choices or DEFAULT_COLOR_CHOICES
    mp = {k: v for k, v in color_choices}
    colors = mp.get(key, mp["slate"])
    return ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=colors)


# -------------------------
#  Primitivos de UI
# -------------------------
def header_row(title: str, actions: list[ft.Control] | None = None) -> ft.Row:
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(title, size=20, weight=ft.FontWeight.BOLD),
            ft.Row(controls=(actions or []), spacing=8),
        ],
    )


def quantity_chip(qty: int) -> ft.Container:
    """Chips de cantidad con color para stock = 0."""
    is_zero = int(qty or 0) == 0
    return ft.Container(
        bgcolor=ft.Colors.RED_100 if is_zero else ft.Colors.GREY_100,
        padding=ft.padding.symmetric(2, 8),
        border_radius=20,
        content=ft.Text(str(qty), size=11, color=ft.Colors.RED_700 if is_zero else ft.Colors.BLACK87),
    )


def pager_buttons(disabled_prev: bool, disabled_next: bool, on_prev, on_next) -> ft.Row:
    """Paginador estándar (Anterior / Siguiente)."""
    return ft.Row(
        alignment=ft.MainAxisAlignment.END,
        controls=[
            ft.FilledButton(
                "Anterior",
                on_click=on_prev,
                disabled=disabled_prev,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)),
            ),
            ft.FilledButton(
                "Siguiente",
                on_click=on_next,
                disabled=disabled_next,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)),
            ),
        ],
    )


def empty_state(icon: str, text: str) -> ft.Container:
    return ft.Container(
        padding=10,
        content=ft.Row(
            spacing=8,
            controls=[ft.Icon(icon, color=ft.Colors.GREY_600), ft.Text(text, color=ft.Colors.GREY_700)],
        ),
    )


def menu_item(label: str, icon: str, on_click, data: str | None = None) -> ft.MenuItemButton:
    return ft.MenuItemButton(
        content=ft.Text(label),
        data=data,
        leading=ft.Icon(icon),
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.HOVERED: ft.Colors.GREY_200},
            shape=ft.RoundedRectangleBorder(radius=0),
        ),
        on_click=on_click,
    )


# -------------------------
#  Componentes compuestos
# -------------------------
def warehouse_card(
    warehouse: dict,
    on_open,         # fn(e, warehouse)
    on_delete,       # fn(e, warehouse)
    color_choices: list[tuple[str, list[str]]] = None,
) -> ft.Stack:
    """Tarjeta clickable del almacén con botón de eliminar."""
    card_body = ft.Container(
        width=300,
        height=300,
        gradient=gradient_for(warehouse.get("color_key") or "slate", color_choices),
        border_radius=8,
        padding=16,
        ink=True,
        on_click=lambda e, w=warehouse: on_open(e, w),
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=18, color=ft.Colors.BLACK26, offset=ft.Offset(0, 6)),
        content=ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.WAREHOUSE, size=68, color=ft.Colors.WHITE),
                ft.Text(warehouse["name"], size=18, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, color=ft.Colors.WHITE),
                ft.Text((warehouse.get("description") or "—"), size=12, color=ft.Colors.WHITE70, text_align=ft.TextAlign.CENTER),
            ],
        ),
    )

    delete_btn = ft.IconButton(
        icon=ft.Icons.DELETE_FOREVER_ROUNDED,
        icon_size=20,
        width=25,
        height=25,
        tooltip="Eliminar almacén",
        icon_color=ft.Colors.RED_600,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=2, bgcolor=ft.Colors.WHITE),
        on_click=lambda e, w=warehouse: on_delete(e, w),
    )
    return ft.Stack(
        width=300,
        height=300,
        controls=[card_body, ft.Container(right=8, top=8, content=delete_btn, border_radius=8)],
    )


def empty_warehouses(on_create) -> ft.Container:
    """
    Pantalla vacía para cuando no hay almacenes.
    Muestra icono, texto de guía y un botón primario para crear un almacén.
    """
    card = ft.Container(
        width=520,
        padding=20,
        border_radius=12,
        bgcolor=ft.Colors.GREY_50,
        shadow=ft.BoxShadow(blur_radius=18, color=ft.Colors.BLACK12, offset=ft.Offset(0, 6)),
        content=ft.Column(
            spacing=14,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.WAREHOUSE, size=72, color=ft.Colors.GREY_700),
                ft.Text("Aún no hay almacenes", size=20, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Crea tu primer almacén para empezar a gestionar entradas, salidas y stock.",
                    size=12,
                    color=ft.Colors.GREY_700,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.FilledButton(
                    "Crear un almacén",
                    icon=ft.Icons.ADD_BUSINESS,
                    on_click=on_create,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                ),
            ],
        ),
    )
    return ft.Container(
        expand=True,
        alignment=ft.alignment.center,
        content=card,
        padding=ft.padding.all(16),
    )