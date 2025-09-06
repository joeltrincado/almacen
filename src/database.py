# database.py
import os, sqlite3
from contextlib import contextmanager

DB_FILE = os.path.join(os.path.dirname(__file__), "almacen.db")

_conn = None

def init_db(db_path: str | None = None):
    global _conn
    path = db_path or DB_FILE
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _create_schema()     # idempotente
    _migrate_to_m2m()    # migra datos antiguos products.warehouse_id -> tabla vínculo
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

def _create_schema():
    with _cur() as c:
        # Warehouses
        c.execute("""
        CREATE TABLE IF NOT EXISTS warehouses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            color_key TEXT DEFAULT 'slate'
        )
        """)

        # Products (catálogo). Conservamos warehouse_id para compatibilidad/migración.
        c.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            warehouse_id INTEGER
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_code ON products(code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_wh ON products(warehouse_id)")

        # App state
        c.execute("""
        CREATE TABLE IF NOT EXISTS app_state(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # Vínculo muchos-a-muchos producto<->almacén
        c.execute("""
        CREATE TABLE IF NOT EXISTS product_warehouse(
            product_id   INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            PRIMARY KEY (product_id, warehouse_id),
            FOREIGN KEY(product_id)   REFERENCES products(id)    ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)  ON DELETE CASCADE
        )
        """)
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
        )
        """)

        # Movimientos de stock
        c.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            product_id   INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            kind TEXT NOT NULL,   -- 'IN' | 'OUT'
            note TEXT DEFAULT '',
            FOREIGN KEY(product_id)   REFERENCES products(id)   ON DELETE CASCADE,
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
        )
        """)

def _migrate_to_m2m():
    """
    Si existen filas antiguas en products.warehouse_id, crea vínculos en product_warehouse
    y limpia la columna para dejar de usarla.
    """
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
                    VALUES (?, ?)
                """, (r["product_id"], r["warehouse_id"]))
                # inicializa stock a 0 si no existía registro
                c.execute("""
                    INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty)
                    VALUES (?, ?, 0)
                """, (r["product_id"], r["warehouse_id"]))
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

# ---------------- Warehouses ----------------
def add_warehouse(name: str, description: str = "", color_key: str = "slate"):
    with _cur() as c:
        c.execute(
            "INSERT INTO warehouses(name, description, color_key) VALUES (?, ?, ?)",
            (name, description, color_key),
        )

def list_warehouses():
    with _cur() as c:
        rows = c.execute("SELECT id, name, description, color_key FROM warehouses ORDER BY name").fetchall()
        return [dict(r) for r in rows]

def delete_warehouse_cascade(warehouse_id: int):
    with _cur() as c:
        c.execute("DELETE FROM product_warehouse WHERE warehouse_id = ?", (warehouse_id,))
        c.execute("DELETE FROM product_stock WHERE warehouse_id = ?", (warehouse_id,))
        c.execute("DELETE FROM warehouses WHERE id = ?", (warehouse_id,))

# ---------------- Products (catálogo) ----------------
def _get_product_by_code(code: str):
    with _cur() as c:
        return c.execute("SELECT id, code, name, description FROM products WHERE code = ?", (code,)).fetchone()

def upsert_product(code: str, name: str | None, description: str | None, warehouse_id: int | None):
    """
    Crea/actualiza un producto del catálogo por 'code'.
    - name/description None NO pisan valores existentes.
    - Si warehouse_id viene, crea el vínculo product_warehouse (y registro de stock si falta).
    """
    with _cur() as c:
        existing = _get_product_by_code(code)
        if existing:
            updates, params = [], []
            if name is not None:
                updates.append("name = ?"); params.append(name)
            if description is not None:
                updates.append("description = ?"); params.append(description)
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
            c.execute("""
                INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id)
                VALUES (?, ?)
            """, (product_id, warehouse_id))
            c.execute("""
                INSERT OR IGNORE INTO product_stock(product_id, warehouse_id, qty)
                VALUES (?, ?, 0)
            """, (product_id, warehouse_id))

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

def list_products():
    with _cur() as c:
        rows = c.execute("""
            SELECT id, code, name, description
            FROM products
            ORDER BY code
        """).fetchall()
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

# ---------------- Stock ----------------
def increment_stock(code: str, warehouse_id: int, qty: int, note: str = ""):
    """Suma qty al stock y registra movimiento 'IN'."""
    if qty <= 0:
        return
    with _cur() as c:
        prod = _get_product_by_code(code)
        if not prod:
            raise ValueError(f"Producto '{code}' no existe")

        # Asegura vínculo y registro de stock
        c.execute("""
            INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id)
            VALUES (?, ?)
        """, (prod["id"], warehouse_id))
        c.execute("""
            INSERT INTO product_stock(product_id, warehouse_id, qty)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id, warehouse_id)
            DO UPDATE SET qty = qty + excluded.qty
        """, (prod["id"], warehouse_id, qty))
        c.execute("""
            INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note)
            VALUES (?, ?, ?, 'IN', ?)
        """, (prod["id"], warehouse_id, qty, note))

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
        if not row or row["value"] in (None, ""):
            return None
        try:
            return int(row["value"])
        except:
            return None

# ---------------- Stock ----------------
def decrement_stock(code: str, warehouse_id: int, qty: int, note: str = ""):
    """Resta qty del stock y registra movimiento 'OUT'."""
    if qty <= 0:
        return
    with _cur() as c:
        prod = _get_product_by_code(code)
        if not prod:
            raise ValueError(f"Producto '{code}' no existe")

        # Asegura vínculo y registro de stock
        c.execute("""
            INSERT OR IGNORE INTO product_warehouse(product_id, warehouse_id)
            VALUES (?, ?)
        """, (prod["id"], warehouse_id))
        c.execute("""
            INSERT INTO product_stock(product_id, warehouse_id, qty)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id, warehouse_id)
            DO UPDATE SET qty = qty - excluded.qty
        """, (prod["id"], warehouse_id, qty))
        c.execute("""
            INSERT INTO stock_movements(product_id, warehouse_id, qty, kind, note)
            VALUES (?, ?, ?, 'OUT', ?)
        """, (prod["id"], warehouse_id, qty, note))
