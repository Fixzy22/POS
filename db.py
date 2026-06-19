import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from config import ADMIN_PASSWORD, ADMIN_USERNAME

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "pos.db"))

PRODUCT_MIGRATIONS = [
    "ALTER TABLE products ADD COLUMN price_box REAL NOT NULL DEFAULT 0",
    "ALTER TABLE products ADD COLUMN price_row REAL NOT NULL DEFAULT 0",
    "ALTER TABLE products ADD COLUMN units_per_box INTEGER NOT NULL DEFAULT 12",
    "ALTER TABLE products ADD COLUMN units_per_row INTEGER NOT NULL DEFAULT 72",
    "ALTER TABLE sales ADD COLUMN customer_name TEXT DEFAULT ''",
    "ALTER TABLE sale_items ADD COLUMN unit_type TEXT NOT NULL DEFAULT 'single'",
    "ALTER TABLE sale_items ADD COLUMN base_quantity INTEGER NOT NULL DEFAULT 1",
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_columns(conn):
    for sql in PRODUCT_MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    conn.execute(
        """
        UPDATE products SET price_box = price * units_per_box
        WHERE price_box = 0 AND units_per_box > 0
        """
    )
    conn.execute(
        """
        UPDATE products SET price_row = price * units_per_row
        WHERE price_row = 0 AND units_per_row > 0
        """
    )
    conn.execute(
        "UPDATE sale_items SET base_quantity = quantity WHERE base_quantity IS NULL OR base_quantity = 0"
    )


def _ensure_admin_user(conn):
    password_hash = generate_password_hash(ADMIN_PASSWORD)
    yoky = conn.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if yoky:
        conn.execute(
            "UPDATE users SET password_hash = ?, role = 'admin' WHERE username = ?",
            (password_hash, ADMIN_USERNAME),
        )
        return

    old_admin = conn.execute(
        "SELECT id FROM users WHERE username = ?", ("admin",)
    ).fetchone()
    if old_admin:
        conn.execute(
            "UPDATE users SET username = ?, password_hash = ?, role = 'admin' WHERE id = ?",
            (ADMIN_USERNAME, password_hash, old_admin["id"]),
        )
        return

    user_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if user_count == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (ADMIN_USERNAME, password_hash, "admin"),
        )


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                price REAL NOT NULL CHECK(price >= 0),
                price_box REAL NOT NULL DEFAULT 0 CHECK(price_box >= 0),
                price_row REAL NOT NULL DEFAULT 0 CHECK(price_row >= 0),
                cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0),
                stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                units_per_box INTEGER NOT NULL DEFAULT 12,
                units_per_row INTEGER NOT NULL DEFAULT 72,
                low_stock_threshold INTEGER NOT NULL DEFAULT 5,
                category TEXT DEFAULT 'Spices',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_number TEXT UNIQUE NOT NULL,
                total_amount REAL NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'cash',
                customer_name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_type TEXT NOT NULL DEFAULT 'single',
                base_quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                change_amount INTEGER NOT NULL,
                previous_stock INTEGER NOT NULL,
                new_stock INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            """
        )

        _migrate_columns(conn)

        _ensure_admin_user(conn)

        product_count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        if product_count == 0:
            sample_products = [
                ("YOKY-001", "Curry Powder", "Premium blend 50g sachet", 2.50, 28.00, 150.00, 1.20, 12, 72, 200, "Ground Spices", 50),
                ("YOKY-002", "Paprika", "Sweet paprika 40g sachet", 2.00, 22.00, 120.00, 0.90, 12, 72, 180, "Ground Spices", 40),
                ("YOKY-003", "Black Pepper Whole", "Whole peppercorns 100g", 4.50, 48.00, 270.00, 2.50, 12, 72, 120, "Whole Spices", 30),
                ("YOKY-004", "Cinnamon Sticks", "Ceylon cinnamon 20-pack", 3.75, 40.00, 225.00, 2.00, 12, 72, 90, "Whole Spices", 25),
                ("YOKY-005", "Mixed Spice Blend", "All-purpose seasoning 60g", 3.25, 35.00, 200.00, 1.80, 12, 72, 150, "Blends", 35),
            ]
            for sku, name, desc, price, price_box, price_row, cost, upb, upr, stock, category, low in sample_products:
                conn.execute(
                    """
                    INSERT INTO products (
                        sku, name, description, price, price_box, price_row, cost, stock,
                        units_per_box, units_per_row, category, low_stock_threshold
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sku, name, desc, price, price_box, price_row, cost, stock, upb, upr, category, low),
                )


def verify_user(username: str, password: str):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            return dict(user)
    return None


def get_user_by_id(user_id: int):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(user) if user else None
