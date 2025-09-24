# database.py
import os, sqlite3
from contextlib import contextmanager
import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "almacen.db")
_conn = None

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db(db_path: str | None = None):
    """
    Inicializa conexión, PRAGMAs, crea/esquema y migra M2M.
    """
    global _conn
    path = db_path or DB_FILE
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row

    # PRAGMAs recomendados
    _conn.execute("PRAGMA foreign_keys = ON;")
    _conn.execute("PRAGMA journal_mode = WAL;")
    _conn.execute("PRAGMA synchronous = NORMAL;")

    _create_schema()
    _migrate_to_m2m()
    _ensure_product_extra_columns()  # <- añade category/unit/unit_factor si faltan
    _conn.commit()

@contextmanager
def _cur():
    if _conn is None:
        init_db()
    c = _conn.cursor()
    try:
        yield c
        _conn.commit()
    finally:
        c.close()

def _table_has_column(table: str, col: str) -> bool:
    with _cur() as c:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        return col in cols

def _ensure_product_extra_columns():
    """
    Agrega columnas opcionales a products (idempotente).
    """
    with _cur() as c:
        for name, ddl in [
            ("category", "ALTER TABLE products ADD COLUMN category TEXT"),
            ("unit", "ALTER TABLE products ADD COLUMN unit TEXT"),
            ("unit_factor", "ALTER TABLE products ADD COLUMN unit_factor REAL"),
        ]:
            if not _table_has_column("products", name):
                try:
                    c.execute(ddl)
                except Exception:
                    pass  # otra instancia pudo haberlo agregado

def _create_schema():
    with _cur() as c:
        # Warehouses
        c.execute("""
        CREATE TABLE IF NOT EXISTS warehouses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            color_key TEXT DEFAULT 'slate'
        )""")

        # Products (base mínima; columnas extra se agregan con _ensure_product_extra_columns)
        c.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            warehouse_id INTEGER
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_code ON products(code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_wh ON products(warehouse_id)")

        # App state
        c.execute("""
        CREATE TABLE IF NOT EXISTS app_state(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        # M2M producto<->almacén
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_warehouse(
            product_id   INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            PRIMARY KEY (product_id, warehouse_id),
            FOREIGN KEY(product_id)   REFERENCES products(id)    ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)  ON DELETE CASCADE
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pw_wh ON product_warehouse(warehouse_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pw_prod ON product_warehouse(product_id)")

        # Stock por almacén
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_stock(
            product_id   INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            qty INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(product_id, warehouse_id),
            FOREIGN KEY(product_id)   REFERENCES products(id)    ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)  ON DELETE CASCADE
        )""")

        # Encabezados de documentos (reportes)
        c.execute("""
        CREATE TABLE IF NOT EXISTS movement_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            doc_type TEXT NOT NULL,        -- 'IN' | 'OUT' | 'ADJ' | otros
            warehouse_id INTEGER NOT NULL,
            counterparty TEXT DEFAULT '',
            reference TEXT DEFAULT '',
            note TEXT DEFAULT '',
            total_lines INTEGER DEFAULT 0,
            total_qty INTEGER DEFAULT 0,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE SET NULL
        )""")

        # Movimientos de stock
        c.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            product_id   INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            kind TEXT NOT NULL,   -- 'IN' | 'OUT' | 'ADJ' | 'XFER-IN' | 'XFER-OUT'
            note TEXT DEFAULT '',
            ref_id INTEGER,
            doc_id INTEGER,
            FOREIGN KEY(product_id)   REFERENCES products(id)   ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
            FOREIGN KEY(doc_id)       REFERENCES movement_docs(id) ON DELETE SET NULL
        )""")

        # Alias por producto
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_codes(
            product_id INTEGER NOT NULL,
            alt_code   TEXT NOT NULL UNIQUE,
            PRIMARY KEY(product_id, alt_code),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_alt_code ON product_codes(alt_code)")

        # Umbrales
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_threshold(
            product_id   INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            threshold INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(product_id, warehouse_id),
            FOREIGN KEY(product_id)   REFERENCES products(id)   ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
        )""")

        # === NUEVO: Reglas de reabastecimiento (por producto/almacén) ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_rules(
            code TEXT NOT NULL,
            warehouse_id INTEGER NOT NULL,
            min_qty INTEGER DEFAULT 0,
            max_qty INTEGER DEFAULT 0,
            reorder_point INTEGER DEFAULT 0,
            multiple INTEGER DEFAULT 1,
            lead_time_days INTEGER DEFAULT 0,
            PRIMARY KEY(code, warehouse_id),
            FOREIGN KEY(code) REFERENCES products(code) ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rules_wh ON product_rules(warehouse_id)")

        # === NUEVO: Proveedores / Clientes ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS suppliers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS customers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT
        )""")

        # === NUEVO: Ubicaciones internas ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_locations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            warehouse_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            UNIQUE(warehouse_id, code),
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_locations(
            warehouse_id INTEGER NOT NULL,
            code TEXT NOT NULL,        -- product code
            location_id INTEGER,       -- FK a warehouse_locations.id
            PRIMARY KEY(warehouse_id, code),
            FOREIGN KEY(code) REFERENCES products(code) ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
            FOREIGN KEY(location_id) REFERENCES warehouse_locations(id) ON DELETE SET NULL
        )""")

        # === NUEVO: Ajustes (cabecera) ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS adjustments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            warehouse_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            reason TEXT,
            note TEXT,
            doc_id INTEGER,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
            FOREIGN KEY(doc_id) REFERENCES movement_docs(id) ON DELETE SET NULL
        )""")

        # === NUEVO: Conteos cíclicos ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS count_sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            warehouse_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'OPEN',   -- OPEN|CLOSED
            note TEXT,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS count_lines(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            code TEXT NOT NULL,        -- product code
            sys_qty INTEGER NOT NULL,
            counted_qty INTEGER,
            UNIQUE(session_id, code),
            FOREIGN KEY(session_id) REFERENCES count_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(code) REFERENCES products(code) ON DELETE CASCADE
        )""")

        # Triggers: evitar qty negativa en product_stock
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_product_stock_no_negative_insert
        BEFORE INSERT ON product_stock
        FOR EACH ROW
        WHEN NEW.qty < 0
        BEGIN
            SELECT RAISE(ABORT, 'product_stock.qty must be >= 0');
        END;""")
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_product_stock_no_negative_update
        BEFORE UPDATE ON product_stock
        FOR EACH ROW
        WHEN NEW.qty < 0
        BEGIN
            SELECT RAISE(ABORT, 'product_stock.qty must be >= 0');
        END;""")

        # Índices para movimientos y docs
        c.execute("CREATE INDEX IF NOT EXISTS idx_movements_doc ON stock_movements(doc_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_movements_prod_wh_ts ON stock_movements(product_id, warehouse_id, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_docs_wh_ts ON movement_docs(warehouse_id, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_docs_ts ON movement_docs(ts DESC)")

def _migrate_to_m2m():
    if not _table_has_column("products", "warehouse_id"):
        return
    with _cur() as c:
        rows = c.execute("""
            SELECT id AS product_id, warehouse_id
            FROM products
            WHERE warehouse_id IS NOT NULL
        """).fetchall()
        for r in rows:
            try:
                c.execute("""
                    INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id)
                    VALUES (?, ?)""", (r["product_id"], r["warehouse_id"]))
                c.execute("""
                    INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty)
                    VALUES (?, ?, 0)""", (r["product_id"], r["warehouse_id"]))
            except Exception:
                pass
        if rows:
            c.execute("UPDATE products SET warehouse_id = NULL")

def ensure_color_column():
    with _cur() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(warehouses)")]
        if "color_key" not in cols:
            c.execute("ALTER TABLE warehouses ADD COLUMN color_key TEXT DEFAULT 'slate'")

def ensure_products_table():
    _create_schema()

# ---------------- Utilidades internas ----------------
def _get_product_by_code(code: str):
    with _cur() as c:
        return c.execute("SELECT id, code, name, description FROM products WHERE code = ?", (code,)).fetchone()

def _get_product_by_any_code(any_code: str):
    with _cur() as c:
        row = c.execute("SELECT id, code, name, description FROM products WHERE code = ?", (any_code,)).fetchone()
        if row:
            return row
        row = c.execute("""
            SELECT p.id, p.code, p.name, p.description
            FROM product_codes pc
            JOIN products p ON p.id = pc.product_id
            WHERE pc.alt_code = ?
        """, (any_code,)).fetchone()
        return row

def _get_ids_for_code(any_code: str):
    p = _get_product_by_any_code(any_code)
    if not p:
        raise ValueError(f"Producto con código '{any_code}' no existe")
    return int(p["id"])

# ---------------- Warehouses ----------------
def add_warehouse(name: str, description: str = "", color_key: str = "slate"):
    with _cur() as c:
        c.execute("INSERT INTO warehouses(name, description, color_key) VALUES (?, ?, ?)", (name, description, color_key))

def list_warehouses():
    with _cur() as c:
        rows = c.execute("SELECT id, name, description, color_key FROM warehouses ORDER BY name").fetchall()
        return [dict(r) for r in rows]

def delete_warehouse_cascade(warehouse_id: int):
    with _cur() as c:
        c.execute("DELETE FROM product_warehouse WHERE warehouse_id = ?", (warehouse_id,))
        c.execute("DELETE FROM product_stock WHERE warehouse_id = ?", (warehouse_id,))
        c.execute("DELETE FROM warehouses WHERE id = ?", (warehouse_id,))

# ---------------- Products ----------------
def upsert_product(code: str, name: str | None, description: str | None, warehouse_id: int | None):
    with _cur() as c:
        existing = _get_product_by_code(code)
        if existing:
            updates, params = [], []
            if name is not None: updates.append("name = ?"); params.append(name)
            if description is not None: updates.append("description = ?"); params.append(description)
            if updates:
                params.append(code)
                c.execute(f"UPDATE products SET {', '.join(updates)} WHERE code = ?", params)
            product_id = existing["id"]
        else:
            ins_name = name if name is not None else ""
            ins_desc = description if description is not None else ""
            c.execute("INSERT INTO products(code, name, description) VALUES (?, ?, ?)", (code, ins_name, ins_desc))
            product_id = c.lastrowid

        if warehouse_id is not None:
            c.execute("INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id) VALUES (?, ?)", (product_id, warehouse_id))
            c.execute("INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty) VALUES (?, ?, 0)", (product_id, warehouse_id))

def list_products():
    with _cur() as c:
        # Si existen columnas extra, se incluirán como keys (o None)
        rows = c.execute("SELECT id, code, name, description, category, unit, unit_factor FROM products ORDER BY code").fetchall()
        return [{**dict(r), "warehouse_id": None} for r in rows]

def list_products_by_warehouse(warehouse_id: int):
    with _cur() as c:
        rows = c.execute("""
            SELECT p.id, p.code, p.name, p.description,
                   IFNULL(ps.qty, 0) AS qty
            FROM products p
            JOIN product_warehouse pw ON pw.product_id = p.id
            LEFT JOIN product_stock ps
                   ON ps.product_id = p.id AND ps.warehouse_id = pw.warehouse_id
            WHERE pw.warehouse_id = ?
            ORDER BY p.code
        """, (warehouse_id,)).fetchall()
        return [{**dict(r), "warehouse_id": warehouse_id} for r in rows]

# ---------------- Alias ----------------
def add_product_alias(code: str, alt_code: str):
    with _cur() as c:
        prod = _get_product_by_code(code)
        if not prod:
            raise ValueError(f"No existe producto base '{code}'")
        c.execute("INSERT OR IGNORE INTO product_codes(product_id, alt_code) VALUES (?, ?)", (prod["id"], alt_code))

def resolve_to_canonical_code(any_code: str) -> str:
    with _cur() as c:
        row = c.execute("SELECT code FROM products WHERE code = ?", (any_code,)).fetchone()
        if row:
            return row["code"]
        row = c.execute("""
            SELECT p.code
            FROM product_codes pc
            JOIN products p ON p.id = pc.product_id
            WHERE pc.alt_code = ?
        """, (any_code,)).fetchone()
        if not row:
            raise ValueError(f"Código/alias '{any_code}' no existe")
        return row["code"]

# ---------------- Documentos (Reportes) ----------------

def _next_doc_folio(series: str) -> int:
    """
    Devuelve el siguiente folio incremental para la serie dada.
    Si no hay folios aún en esa serie, retorna 1.
    """
    s = (series or "GEN").strip().upper()
    with _cur() as c:
        row = c.execute("SELECT MAX(folio) FROM movement_docs WHERE series = ?", (s,)).fetchone()
    last = row[0] if row else None
    try:
        return int(last) + 1 if last is not None else 1
    except Exception:
        return 1


def create_movement_doc(
    doc_type: str,
    warehouse_id: int,
    counterparty: str = "",
    reference: str = "",
    note: str = "",
    total_lines: int = 0,
    total_qty: int = 0,
    series: str | None = None,
    folio: int | None = None,
    status: str = "posted",
) -> int:
    """Crea encabezado de documento (IN/OUT/ADJ) con soporte de series/folio/status."""
    # Asegurar columnas y constraints (idempotente)
    try:
        ensure_movement_doc_series_status()
    except Exception:
        pass
    s = (series or "GEN").strip().upper()
    try:
        f = folio if (folio and int(folio) > 0) else _next_doc_folio(s)
    except Exception:
        f = folio or None
    st = (status or "posted").strip().lower()

    with _cur() as c:
        if f is None:
            # permitir folio NULL si no podemos calcularlo ahora
            c.execute("""
                INSERT INTO movement_docs(doc_type, warehouse_id, counterparty, reference, note,
                                          total_lines, total_qty, series, folio, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """, (doc_type, warehouse_id, counterparty or "", reference or "", note or "",
                    int(total_lines or 0), int(total_qty or 0), s, st))
        else:
            c.execute("""
                INSERT INTO movement_docs(doc_type, warehouse_id, counterparty, reference, note,
                                          total_lines, total_qty, series, folio, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (doc_type, warehouse_id, counterparty or "", reference or "", note or "",
                    int(total_lines or 0), int(total_qty or 0), s, int(f), st))
        return int(c.lastrowid)

def increment_stock(code_or_alias: str, warehouse_id: int, qty: int, note: str = "", doc_id: int | None = None):
    if qty <= 0: return
    with _cur() as c:
        prod = _get_product_by_any_code(code_or_alias)
        if not prod: raise ValueError(f"Producto '{code_or_alias}' no existe")
        c.execute("INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id) VALUES (?, ?)", (prod["id"], warehouse_id))
        c.execute("""
            INSERT INTO product_stock(product_id, warehouse_id, qty)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id, warehouse_id)
            DO UPDATE SET qty = qty + excluded.qty
        """, (prod["id"], warehouse_id, qty))
        c.execute("""
            INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note, doc_id)
            VALUES (?, ?, ?, 'IN', ?, ?)
        """, (prod["id"], warehouse_id, qty, note, doc_id))

def decrement_stock(code_or_alias: str, warehouse_id: int, qty: int, note: str = "", doc_id: int | None = None):
    if qty <= 0:
        return
    with _cur() as c:
        prod = _get_product_by_any_code(code_or_alias)
        if not prod:
            raise ValueError(f"Producto '{code_or_alias}' no existe")

        # Asegura vínculo y fila en stock
        c.execute("INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id) VALUES (?, ?)", (prod["id"], warehouse_id))
        c.execute("INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty) VALUES (?, ?, 0)", (prod["id"], warehouse_id))

        # Lee disponibilidad actual
        row = c.execute(
            "SELECT qty FROM product_stock WHERE product_id=? AND warehouse_id=?",
            (prod["id"], warehouse_id)
        ).fetchone()
        curr = int(row["qty"]) if row else 0

        if qty > curr:
            raise ValueError(f"Solicitud ({qty}) supera existencia ({curr}) en almacén {warehouse_id}")

        # Aplica decremento
        c.execute(
            "UPDATE product_stock SET qty = qty - ? WHERE product_id=? AND warehouse_id=?",
            (qty, prod["id"], warehouse_id)
        )
        c.execute("""
            INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note, doc_id)
            VALUES (?, ?, ?, 'OUT', ?, ?)
        """, (prod["id"], warehouse_id, qty, note, doc_id))

def set_stock(code_or_alias: str, warehouse_id: int, new_qty: int, note: str = "", doc_id: int | None = None):
    if new_qty < 0:
        raise ValueError("Nuevo nivel de existencias no puede ser negativo")
    with _cur() as c:
        prod = _get_product_by_any_code(code_or_alias)
        if not prod:
            raise ValueError(f"Producto '{code_or_alias}' no existe")

        c.execute("INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id) VALUES (?, ?)", (prod["id"], warehouse_id))
        row = c.execute(
            "SELECT qty FROM product_stock WHERE product_id=? AND warehouse_id=?",
            (prod["id"], warehouse_id)
        ).fetchone()
        curr = int(row["qty"]) if row else 0
        delta = int(new_qty) - curr

        c.execute("""
            INSERT INTO product_stock(product_id, warehouse_id, qty)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id, warehouse_id)
            DO UPDATE SET qty = excluded.qty
        """, (prod["id"], warehouse_id, int(new_qty)))

        if delta != 0:
            c.execute("""
                INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note, doc_id)
                VALUES (?, ?, ?, 'ADJ', ?, ?)
            """, (prod["id"], warehouse_id, delta, note or f"Ajuste a {new_qty} (Δ {delta})", doc_id))

def transfer_stock(code_or_alias: str, src_warehouse_id: int, dst_warehouse_id: int, qty: int, note: str = ""):
    if qty <= 0 or src_warehouse_id == dst_warehouse_id:
        return
    with _cur() as c:
        prod = _get_product_by_any_code(code_or_alias)
        if not prod: raise ValueError(f"Producto '{code_or_alias}' no existe")
        for wid in (src_warehouse_id, dst_warehouse_id):
            c.execute("INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id) VALUES (?, ?)", (prod["id"], wid))
            c.execute("INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty) VALUES (?, ?, 0)", (prod["id"], wid))
        row = c.execute("SELECT qty FROM product_stock WHERE product_id=? AND warehouse_id=?", (prod["id"], src_warehouse_id)).fetchone()
        avail = int(row["qty"]) if row else 0
        if qty > avail:
            raise ValueError(f"Transferencia supera disponibilidad (req {qty} > disp {avail})")
        # OUT origen
        c.execute("UPDATE product_stock SET qty = qty - ? WHERE product_id=? AND warehouse_id=?", (qty, prod["id"], src_warehouse_id))
        c.execute("""
            INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note)
            VALUES (?, ?, ?, 'XFER-OUT', ?)
        """, (prod["id"], src_warehouse_id, qty, note or f"XFER a {dst_warehouse_id}"))
        out_id = c.lastrowid
        # IN destino
        c.execute("UPDATE product_stock SET qty = qty + ? WHERE product_id=? AND warehouse_id=?", (qty, prod["id"], dst_warehouse_id))
        c.execute("""
            INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note, ref_id)
            VALUES (?, ?, ?, 'XFER-IN', ?, ?)
        """, (prod["id"], dst_warehouse_id, qty, note or f"XFER de {src_warehouse_id}", out_id))

# ---------------- Umbrales y reportes ----------------
def set_threshold(code_or_alias: str, warehouse_id: int, threshold: int):
    if threshold < 0: threshold = 0
    pid = _get_ids_for_code(code_or_alias)
    with _cur() as c:
        c.execute("""
            INSERT INTO product_threshold(product_id, warehouse_id, threshold)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id, warehouse_id)
            DO UPDATE SET threshold = excluded.threshold
        """, (pid, warehouse_id, threshold))

def get_threshold(code_or_alias: str, warehouse_id: int) -> int:
    pid = _get_ids_for_code(code_or_alias)
    with _cur() as c:
        row = c.execute("SELECT threshold FROM product_threshold WHERE product_id=? AND warehouse_id=?", (pid, warehouse_id)).fetchone()
        return int(row["threshold"]) if row else 0

def list_low_stock(warehouse_id: int, limit: int = 500):
    with _cur() as c:
        rows = c.execute("""
            SELECT p.code, p.name, IFNULL(ps.qty,0) AS qty, IFNULL(pt.threshold,0) AS threshold
            FROM product_warehouse pw
            JOIN products p ON p.id = pw.product_id
            LEFT JOIN product_stock ps ON ps.product_id = pw.product_id AND ps.warehouse_id = pw.warehouse_id
            LEFT JOIN product_threshold pt ON pt.product_id = pw.product_id AND pt.warehouse_id = pw.warehouse_id
            WHERE pw.warehouse_id = ?
              AND ( (IFNULL(ps.qty,0) <= IFNULL(pt.threshold,0) AND IFNULL(pt.threshold,0) > 0) OR IFNULL(ps.qty,0) = 0 )
            ORDER BY (CASE WHEN ps.qty=0 THEN 0 ELSE 1 END), p.code
            LIMIT ?
        """, (warehouse_id, limit)).fetchall()
        return [dict(r) for r in rows]

def list_movements(warehouse_id: int | None = None, code_or_alias: str | None = None,
                   days: int | None = None, limit: int = 500):
    params, where = [], []
    if warehouse_id is not None:
        where.append("m.warehouse_id = ?"); params.append(warehouse_id)
    if code_or_alias:
        pid = _get_ids_for_code(code_or_alias)
        where.append("m.product_id = ?"); params.append(pid)
    if days is not None and days > 0:
        where.append("m.ts >= datetime('now', ?)"); params.append(f'-{int(days)} days')
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT m.id, m.ts, m.qty, m.kind, m.note,
               m.doc_id,
               w.name AS warehouse, p.code AS code, p.name AS product,
               d.reference AS doc_reference,
               d.counterparty AS doc_counterparty
        FROM stock_movements m
        JOIN products p  ON p.id  = m.product_id
        JOIN warehouses w ON w.id = m.warehouse_id
        LEFT JOIN movement_docs d ON d.id = m.doc_id
        {where_sql}
        ORDER BY m.ts DESC, m.id DESC
        LIMIT ?
    """
    params.append(limit)
    with _cur() as c:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

# ---------------- App state ----------------
def save_last_warehouse_id(warehouse_id: int | None):
    with _cur() as c:
        if warehouse_id is None:
            c.execute("DELETE FROM app_state WHERE key = 'last_warehouse_id'")
        else:
            c.execute("""
                INSERT INTO app_state(key, value) VALUES('last_warehouse_id', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (str(warehouse_id),))

def load_last_warehouse_id() -> int | None:
    with _cur() as c:
        row = c.execute("SELECT value FROM app_state WHERE key = 'last_warehouse_id'").fetchone()
        if not row or row["value"] in (None, ""): return None
        try: return int(row["value"])
        except: return None

# --- Reportes (encabezado + líneas) ---
def get_movement_doc(doc_id: int) -> dict | None:
    with _cur() as c:
        row = c.execute("""
            SELECT d.id, d.ts, d.doc_type, d.warehouse_id, w.name AS warehouse,
                   d.counterparty, d.reference, d.note, d.total_lines, d.total_qty,
                   d.created_by, cu.username AS created_by_username, cu.name AS created_by_name,
                   d.approved_by, au.username AS approved_by_username, au.name AS approved_by_name
            FROM movement_docs d
            JOIN warehouses w ON w.id = d.warehouse_id
            LEFT JOIN users cu ON cu.id = d.created_by
            LEFT JOIN users au ON au.id = d.approved_by
            WHERE d.id = ?
        """, (doc_id,)).fetchone()
        return dict(row) if row else None

def list_doc_lines(doc_id: int) -> list[dict]:
    with _cur() as c:
        rows = c.execute("""
            SELECT m.id, m.ts, m.qty, m.kind, m.note,
                   p.code, p.name, w.name AS warehouse
            FROM stock_movements m
            JOIN products p  ON p.id = m.product_id
            JOIN warehouses w ON w.id = m.warehouse_id
            WHERE m.doc_id = ?
            ORDER BY m.id
        """, (doc_id,)).fetchall()
        return [dict(r) for r in rows]

def list_purchase_suggestions(warehouse_id: int, limit: int = 1000) -> list[dict]:
    with _cur() as c:
        rows = c.execute("""
            SELECT
                p.code AS code,
                p.name AS name,
                IFNULL(ps.qty, 0)      AS qty,
                IFNULL(pt.threshold,0) AS threshold,
                CASE
                    WHEN IFNULL(pt.threshold,0) - IFNULL(ps.qty,0) > 0
                    THEN (pt.threshold - IFNULL(ps.qty,0))
                    ELSE 0
                END AS deficit
            FROM product_warehouse pw
            JOIN products p
              ON p.id = pw.product_id
            LEFT JOIN product_stock ps
              ON ps.product_id = pw.product_id
             AND ps.warehouse_id = pw.warehouse_id
            LEFT JOIN product_threshold pt
              ON pt.product_id = pw.product_id
             AND pt.warehouse_id = pw.warehouse_id
            WHERE pw.warehouse_id = ?
              AND IFNULL(pt.threshold,0) > 0
              AND (IFNULL(pt.threshold,0) - IFNULL(ps.qty,0)) > 0
            ORDER BY deficit DESC, p.code
            LIMIT ?
        """, (warehouse_id, limit)).fetchall()
        return [dict(r) for r in rows]

# ====== Categorías / unidades ======
def set_product_category_unit(code: str, category: str|None, unit: str|None, unit_factor: float|None):
    with _cur() as c:
        c.execute("""UPDATE products SET category=?, unit=?, unit_factor=? WHERE code=?""",
                  (category or None, unit or None, unit_factor if unit_factor else None, code))

def list_categories():
    with _cur() as c:
        cur = c.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category<>'' ORDER BY 1")
        return [r[0] for r in cur.fetchall()]

# ====== Reglas de reabastecimiento ======
def set_replenishment_rule(code: str, warehouse_id: int, min_qty: int, max_qty: int,
                           reorder_point: int, multiple: int, lead_time_days: int):
    with _cur() as c:
        c.execute("""INSERT INTO product_rules(code, warehouse_id, min_qty, max_qty, reorder_point, multiple, lead_time_days)
                     VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(code,warehouse_id)
                     DO UPDATE SET min_qty=excluded.min_qty, max_qty=excluded.max_qty, 
                         reorder_point=excluded.reorder_point, multiple=excluded.multiple, 
                         lead_time_days=excluded.lead_time_days""",
                  (code, warehouse_id, min_qty, max_qty, reorder_point, multiple, lead_time_days))

def get_replenishment_rule(code: str, warehouse_id: int):
    with _cur() as c:
        r = c.execute("""SELECT min_qty,max_qty,reorder_point,multiple,lead_time_days
                         FROM product_rules WHERE code=? AND warehouse_id=?""", (code, warehouse_id)).fetchone()
        if not r: return None
        return {"min_qty":r[0],"max_qty":r[1],"reorder_point":r[2],"multiple":r[3],"lead_time_days":r[4]}

def list_replenishment_rules(warehouse_id: int, limit: int=1000):
    with _cur() as c:
        rows = c.execute("""SELECT pr.code, p.name, pr.min_qty, pr.max_qty, pr.reorder_point, pr.multiple, pr.lead_time_days
                            FROM product_rules pr
                            LEFT JOIN products p ON p.code=pr.code
                            WHERE pr.warehouse_id=?
                            ORDER BY pr.code LIMIT ?""", (warehouse_id, limit)).fetchall()
        return [{"code":c, "name":n or "", "min_qty":mn, "max_qty":mx, "reorder_point":rp,
                 "multiple":mul, "lead_time_days":lt} for c,n,mn,mx,rp,mul,lt in rows]

# ====== Proveedores / Clientes ======
def add_supplier(name: str, contact: str|None=None):
    with _cur() as c:
        c.execute("INSERT INTO suppliers(name, contact) VALUES(?,?)", (name, contact or None))

def list_suppliers(limit: int=500):
    with _cur() as c:
        rows = c.execute("SELECT id, name, contact FROM suppliers ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id":i,"name":n,"contact":c} for i,n,c in rows]

def add_customer(name: str, contact: str|None=None):
    with _cur() as c:
        c.execute("INSERT INTO customers(name, contact) VALUES(?,?)", (name, contact or None))

def list_customers(limit: int=500):
    with _cur() as c:
        rows = c.execute("SELECT id, name, contact FROM customers ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id":i,"name":n,"contact":c} for i,n,c in rows]

# ====== Ubicaciones ======
def add_location(warehouse_id: int, code: str, name: str|None=None):
    with _cur() as c:
        c.execute("INSERT INTO warehouse_locations(warehouse_id, code, name) VALUES(?,?,?)",
                  (warehouse_id, code, name or None))

def list_locations(warehouse_id: int):
    with _cur() as c:
        rows = c.execute("SELECT id, code, name FROM warehouse_locations WHERE warehouse_id=? ORDER BY code", (warehouse_id,)).fetchall()
        return [{"id":i,"code":c,"name":n} for i,c,n in rows]

def set_product_location(warehouse_id: int, code: str, location_id: int|None):
    with _cur() as c:
        c.execute("""INSERT INTO product_locations(warehouse_id, code, location_id)
                     VALUES(?,?,?)
                     ON CONFLICT(warehouse_id, code)
                     DO UPDATE SET location_id=excluded.location_id""",
                  (warehouse_id, code, location_id))

def get_product_location(warehouse_id: int, code: str):
    with _cur() as c:
        r = c.execute("SELECT location_id FROM product_locations WHERE warehouse_id=? AND code=?", (warehouse_id, code)).fetchone()
        return r[0] if r else None

# ====== Ajustes ======
def create_adjustment(warehouse_id: int, reason: str, note: str|None, doc_id: int|None):
    with _cur() as c:
        c.execute("INSERT INTO adjustments(warehouse_id, created_at, reason, note, doc_id) VALUES(?,?,?,?,?)",
                  (warehouse_id, _now(), reason, note or None, doc_id))
        return c.lastrowid

# ====== Conteos ======
def create_count_session(warehouse_id: int, note: str|None=None):
    with _cur() as c:
        c.execute("INSERT INTO count_sessions(warehouse_id, created_at, note, status) VALUES(?,?,?,?)",
                  (warehouse_id, _now(), note or None, "OPEN"))
        return c.lastrowid

def add_count_line(session_id: int, code: str, sys_qty: int):
    with _cur() as c:
        c.execute("""INSERT OR IGNORE INTO count_lines(session_id, code, sys_qty) VALUES(?,?,?)""",
                  (session_id, code, sys_qty))

def update_count_line(session_id: int, code: str, counted_qty: int):
    with _cur() as c:
        c.execute("""UPDATE count_lines SET counted_qty=? WHERE session_id=? AND code=?""",
                  (counted_qty, session_id, code))

def list_count_lines(session_id: int):
    with _cur() as c:
        rows = c.execute("""SELECT code, sys_qty, counted_qty FROM count_lines WHERE session_id=? ORDER BY code""",
                         (session_id,)).fetchall()
        return [{"code":c,"sys_qty":s,"counted_qty":(q if q is not None else None)} for c,s,q in rows]

def close_count_session(session_id: int):
    with _cur() as c:
        c.execute("UPDATE count_sessions SET status='CLOSED' WHERE id=?", (session_id,))

# ====== APOYO: stock por almacén ======
def get_stock_map(warehouse_id: int) -> dict:
    """
    Devuelve {code: qty} para un almacén usando product_stock.
    """
    with _cur() as c:
        rows = c.execute("""
            SELECT p.code, IFNULL(ps.qty,0) AS qty
            FROM product_warehouse pw
            JOIN products p ON p.id = pw.product_id
            LEFT JOIN product_stock ps ON ps.product_id = pw.product_id AND ps.warehouse_id = pw.warehouse_id
            WHERE pw.warehouse_id=?
        """, (warehouse_id,)).fetchall()
        return {r["code"]: int(r["qty"] or 0) for r in rows}

# ====== Reconciliación conteo → ajustes ======
def reconcile_count_to_adjustments(session_id: int, warehouse_id: int,
                                   create_movement_doc,  # inyección: tu función existente
                                   inc_fn, dec_fn):
    rows = list_count_lines(session_id)
    diffs = []
    for r in rows:
        if r["counted_qty"] is None: continue
        delta = int(r["counted_qty"]) - int(r["sys_qty"])
        if delta != 0:
            diffs.append({"code": r["code"], "delta": delta})

    if not diffs:
        return None

    total_lines = len(diffs)
    total_qty = sum(abs(d["delta"]) for d in diffs)
    doc_id = create_movement_doc(
        doc_type="ADJ",
        warehouse_id=warehouse_id,
        counterparty="Conteo cíclico",
        reference=f"COUNT {session_id}",
        note="Ajuste por conciliación de conteo",
        total_lines=total_lines,
        total_qty=total_qty,
    )
    create_adjustment(warehouse_id, "conteo", "Ajuste por conteo cíclico", doc_id)

    for d in diffs:
        if d["delta"] > 0:
            inc_fn(d["code"], warehouse_id, d["delta"], note="Ajuste + conteo", doc_id=doc_id)
        else:
            dec_fn(d["code"], warehouse_id, -d["delta"], note="Ajuste - conteo", doc_id=doc_id)

    close_count_session(session_id)
    return doc_id

def link_product_to_warehouse(code: str, warehouse_id: int):
    with _cur() as c:
        prod = _get_product_by_code(code)
        if not prod:
            raise ValueError(f"Producto con código '{code}' no existe en catálogo.")
        c.execute("""
            INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id)
            VALUES (?, ?)
        """, (prod["id"], warehouse_id))
        c.execute("""
            INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty)
            VALUES (?, ?, 0)
        """, (prod["id"], warehouse_id))

def is_product_linked(code: str, warehouse_id: int) -> bool:
    with _cur() as c:
        prod = _get_product_by_code(code)
        if not prod:
            return False
        row = c.execute("""
            SELECT 1 FROM product_warehouse WHERE product_id = ? AND warehouse_id = ? LIMIT 1
        """, (prod["id"], warehouse_id)).fetchone()
        return bool(row)

# ========================
#  FASE 2: Seguridad & Auditoría
# ========================

def ensure_security_audit_schema():
    """
    Crea tablas de usuarios y bitácora de auditoría, y agrega columnas de usuario a movement_docs.
    Llamar desde init_db.
    """
    with _cur() as c:
        # Tabla de usuarios
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',  -- operator|supervisor|admin|viewer
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")

        # Tabla de auditoría
        c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            user_id INTEGER,
            action TEXT NOT NULL,
            entity TEXT NOT NULL,
            entity_id INTEGER,
            details TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        )""")

        # Columnas de usuario en movement_docs
        if not _table_has_column("movement_docs", "created_by"):
            c.execute("ALTER TABLE movement_docs ADD COLUMN created_by INTEGER")
        if not _table_has_column("movement_docs", "approved_by"):
            c.execute("ALTER TABLE movement_docs ADD COLUMN approved_by INTEGER")

def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    import os, hashlib, binascii
    if salt is None:
        salt = os.urandom(16)
    if isinstance(salt, str):
        salt = binascii.unhexlify(salt.encode())
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000, dklen=32)
    return binascii.hexlify(dk).decode(), binascii.hexlify(salt).decode()

def create_user(username: str, name: str, role: str, password: str) -> int:
    role = (role or "operator").lower()
    if role not in ("viewer","operator","supervisor","admin"):
        raise ValueError("Rol inválido")
    pw_hash, salt = _hash_password(password)
    with _cur() as c:
        c.execute("""
            INSERT INTO users(username, name, role, password_hash, salt)
            VALUES (?,?,?,?,?)""", (username.strip(), name.strip(), role, pw_hash, salt))
        return int(c.lastrowid)

def get_user_by_username(username: str) -> dict | None:
    with _cur() as c:
        r = c.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username.strip(),)).fetchone()
        return dict(r) if r else None

def verify_user_password(username: str, password: str) -> dict | None:
    u = get_user_by_username(username)
    if not u: 
        return None
    pw_hash, _ = _hash_password(password, u["salt"])
    return u if pw_hash == u["password_hash"] else None

def update_user_password(user_id: int, new_password: str):
    pw_hash, salt = _hash_password(new_password)
    with _cur() as c:
        c.execute("UPDATE users SET password_hash=?, salt=? WHERE id=? AND active=1", (pw_hash, salt, user_id))

def ensure_default_admin():
    with _cur() as c:
        r = c.execute("SELECT id FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone()
    if not r:
        try:
            return create_user("admin", "Administrador", "admin", "admin")
        except Exception:
            pass

def log_audit(user_id: int | None, action: str, entity: str, entity_id: int | None, details: str | None = None):
    with _cur() as c:
        c.execute("""
            INSERT INTO audit_log(user_id, action, entity, entity_id, details)
            VALUES (?,?,?,?,?)""", (user_id, action, entity, entity_id, details or ""))

# --- Wrappers con auditoría ---
# Guardamos las referencias originales para no perder la lógica actual
try:
    _orig_create_movement_doc = create_movement_doc
    def create_movement_doc(
        doc_type: str,
        warehouse_id: int,
        counterparty: str = "",
        reference: str = "",
        note: str = "",
        total_lines: int = 0,
        total_qty: int = 0,
        series: str | None = None,
        folio: int | None = None,
        status: str = "posted",
        created_by: int | None = None,
        approved_by: int | None = None,
    ) -> int:
        doc_id = _orig_create_movement_doc(
            doc_type=doc_type,
            warehouse_id=warehouse_id,
            counterparty=counterparty,
            reference=reference,
            note=note,
            total_lines=total_lines,
            total_qty=total_qty,
            series=series,
            folio=folio,
            status=status,
        )
        # Actualizar campos de usuario si se proporcionan
        try:
            with _cur() as c:
                if created_by is not None or approved_by is not None:
                    c.execute("""
                        UPDATE movement_docs
                           SET created_by = COALESCE(?, created_by),
                               approved_by = COALESCE(?, approved_by)
                         WHERE id = ?
                    """, (created_by, approved_by, doc_id))
        except Exception:
            pass
        try:
            log_audit(created_by, "CREATE_DOC", "movement_docs", doc_id, f"{doc_type}|WH:{warehouse_id}|lines:{total_lines}|qty:{total_qty}")
        except Exception:
            pass
        return doc_id
except NameError:
    pass

try:
    _orig_increment_stock = increment_stock
    def increment_stock(code_or_alias: str, warehouse_id: int, qty: int, note: str = "", doc_id: int | None = None, user_id: int | None = None):
        res = _orig_increment_stock(code_or_alias, warehouse_id, qty, note=note, doc_id=doc_id)
        try:
            log_audit(user_id, "INCREMENT_STOCK", "stock_movements", doc_id, f"{code_or_alias}|WH:{warehouse_id}|+{qty}|{note}")
        except Exception:
            pass
        return res
except NameError:
    pass

try:
    _orig_decrement_stock = decrement_stock
    def decrement_stock(code_or_alias: str, warehouse_id: int, qty: int, note: str = "", doc_id: int | None = None, user_id: int | None = None):
        res = _orig_decrement_stock(code_or_alias, warehouse_id, qty, note=note, doc_id=doc_id)
        try:
            log_audit(user_id, "DECREMENT_STOCK", "stock_movements", doc_id, f"{code_or_alias}|WH:{warehouse_id}|-{qty}|{note}")
        except Exception:
            pass
        return res
except NameError:
    pass

try:
    _orig_set_stock = set_stock
    def set_stock(code_or_alias: str, warehouse_id: int, new_qty: int, note: str = "", doc_id: int | None = None, user_id: int | None = None):
        res = _orig_set_stock(code_or_alias, warehouse_id, new_qty, note=note, doc_id=doc_id)
        try:
            log_audit(user_id, "SET_STOCK", "stock_movements", doc_id, f"{code_or_alias}|WH:{warehouse_id}|={new_qty}|{note}")
        except Exception:
            pass
        return res
except NameError:
    pass

try:
    _orig_transfer_stock = transfer_stock
    def transfer_stock(
        code_or_alias: str,
        src_warehouse_id: int,
        dst_warehouse_id: int,
        qty: int,
        note: str = "Transferencia",
        ref_id: int | None = None,
        user_id: int | None = None
    ):
        # Ejecutar la función original (no acepta ref_id)
        res = _orig_transfer_stock(
            code_or_alias,
            src_warehouse_id,
            dst_warehouse_id,
            qty,
            note=note
        )

        # Guardar log de auditoría (puedes aprovechar ref_id aquí si lo necesitas)
        try:
            log_audit(
                user_id,
                "TRANSFER_STOCK",
                "stock_movements",
                ref_id,  # aquí se guarda como referencia de auditoría
                f"{code_or_alias}|{src_warehouse_id}->{dst_warehouse_id}|{qty}|{note}"
            )
        except Exception:
            pass

        return res
except NameError:
    pass

# --- Reencolar init_db para asegurar el esquema de seguridad/auditoría ---
try:
    _orig_init_db = init_db
    def init_db(db_path: str | None = None):
        _orig_init_db(db_path)
        ensure_security_audit_schema()
        ensure_movement_doc_series_status()  # por si llegaste a esta fase sin correr Fase 1
        ensure_default_admin()
        _conn.commit()
except NameError:
    pass

# --- Phase 2: security/audit additions (idempotentes) ---
def ensure_movement_doc_series_status():
    """Asegura series/folio/status y el índice único (serie, folio)."""
    with _cur() as c:
        if not _table_has_column("movement_docs", "series"):
            c.execute("ALTER TABLE movement_docs ADD COLUMN series TEXT")
        if not _table_has_column("movement_docs", "folio"):
            c.execute("ALTER TABLE movement_docs ADD COLUMN folio INTEGER")
        if not _table_has_column("movement_docs", "status"):
            c.execute("ALTER TABLE movement_docs ADD COLUMN status TEXT DEFAULT 'posted'")
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_movement_docs_series_folio
            ON movement_docs(series, folio)
            WHERE folio IS NOT NULL
        """)


# =========================
#  EXTENSIONES: Usuarios & Contrapartes (edición)
# =========================
def _ensure_users_table():
    with _cur() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                name TEXT,
                role TEXT DEFAULT 'operator',
                password_hash TEXT,
                active INTEGER DEFAULT 1
            )""")

def list_active_users():
    """Devuelve usuarios activos para selector de operador."""
    _ensure_users_table()
    with _cur() as c:
        rows = c.execute("""
            SELECT id, username, name, role
            FROM users
            WHERE IFNULL(active,1)=1
            ORDER BY CASE WHEN IFNULL(name,'')<>'' THEN name ELSE username END
        """).fetchall()
        return [dict(r) for r in rows]

def update_supplier(supplier_id: int, name: str, contact: str|None=None):
    with _cur() as c:
        c.execute("UPDATE suppliers SET name=?, contact=? WHERE id=?", (name, (contact or None), supplier_id))


def delete_supplier(supplier_id: int):
    """Elimina completamente el proveedor (nombre y contacto)."""
    with _cur() as c:
        c.execute("DELETE FROM suppliers WHERE id=?", (supplier_id,))


def update_customer(customer_id: int, name: str, contact: str|None=None):
    with _cur() as c:
        c.execute("UPDATE customers SET name=?, contact=? WHERE id=?", (name, (contact or None), customer_id))


def delete_customer(customer_id: int):
    """Elimina completamente el cliente (nombre y contacto)."""
    with _cur() as c:
        c.execute("DELETE FROM customers WHERE id=?", (customer_id,))

# ---------------- Proveedores / Clientes ----------------
def add_supplier_if_not_exists(name: str, contact: str | None = None):
    if not name: 
        return
    with _cur() as c:
        row = c.execute("SELECT id FROM suppliers WHERE name = ?", (name,)).fetchone()
        if not row:
            c.execute("INSERT INTO suppliers(name, contact) VALUES (?, ?)", (name, contact or None))

def add_customer_if_not_exists(name: str, contact: str | None = None):
    if not name:
        return
    with _cur() as c:
        row = c.execute("SELECT id FROM customers WHERE name = ?", (name,)).fetchone()
        if not row:
            c.execute("INSERT INTO customers(name, contact) VALUES (?, ?)", (name, contact or None))
