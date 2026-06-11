import sqlite3
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).parent / "pos.db"


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
                cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0),
                stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                low_stock_threshold INTEGER NOT NULL DEFAULT 5,
                category TEXT DEFAULT 'General',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_number TEXT UNIQUE NOT NULL,
                total_amount REAL NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'cash',
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

        admin = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("admin",)
        ).fetchone()
        if not admin:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "admin"),
            )

        product_count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        if product_count == 0:
            sample_products = [
                ("SKU-001", "Coffee Mug", "Ceramic mug 12oz", 12.99, 5.00, 50, "Drinkware", 10),
                ("SKU-002", "Notebook", "A5 ruled notebook", 8.50, 3.00, 100, "Stationery", 15),
                ("SKU-003", "Wireless Mouse", "Ergonomic wireless mouse", 24.99, 12.00, 30, "Electronics", 5),
                ("SKU-004", "Water Bottle", "Stainless steel 500ml", 18.00, 8.00, 40, "Drinkware", 8),
                ("SKU-005", "USB-C Cable", "2m braided cable", 14.99, 4.50, 75, "Electronics", 10),
            ]
            for sku, name, desc, price, cost, stock, category, low in sample_products:
                conn.execute(
                    """
                    INSERT INTO products (sku, name, description, price, cost, stock, category, low_stock_threshold)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sku, name, desc, price, cost, stock, category, low),
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
