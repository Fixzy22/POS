import json
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import get_db, init_db, verify_user

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)


@app.template_filter("tojson")
def tojson_filter(value):
    if hasattr(value, "keys"):
        value = dict(value)
    return json.dumps(value)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated


@app.before_request
def ensure_db():
    init_db()


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = verify_user(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    with get_db() as conn:
        stats = {
            "total_products": conn.execute(
                "SELECT COUNT(*) AS c FROM products WHERE is_active = 1"
            ).fetchone()["c"],
            "low_stock": conn.execute(
                "SELECT COUNT(*) AS c FROM products WHERE is_active = 1 AND stock <= low_stock_threshold"
            ).fetchone()["c"],
            "total_stock_value": conn.execute(
                "SELECT COALESCE(SUM(stock * price), 0) AS v FROM products WHERE is_active = 1"
            ).fetchone()["v"],
            "sales_today": conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) AS v FROM sales WHERE date(created_at) = date('now')"
            ).fetchone()["v"],
            "sales_count_today": conn.execute(
                "SELECT COUNT(*) AS c FROM sales WHERE date(created_at) = date('now')"
            ).fetchone()["c"],
            "total_sales": conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) AS v FROM sales"
            ).fetchone()["v"],
        }
        low_stock_products = conn.execute(
            """
            SELECT * FROM products
            WHERE is_active = 1 AND stock <= low_stock_threshold
            ORDER BY stock ASC LIMIT 10
            """
        ).fetchall()
        recent_sales = conn.execute(
            """
            SELECT s.*, u.username
            FROM sales s
            JOIN users u ON u.id = s.created_by
            ORDER BY s.created_at DESC LIMIT 8
            """
        ).fetchall()
    return render_template(
        "dashboard.html",
        stats=stats,
        low_stock_products=low_stock_products,
        recent_sales=recent_sales,
    )


@app.route("/inventory")
@login_required
@admin_required
def inventory():
    search = request.args.get("q", "").strip()
    with get_db() as conn:
        if search:
            products = conn.execute(
                """
                SELECT * FROM products
                WHERE name LIKE ? OR sku LIKE ? OR category LIKE ?
                ORDER BY name
                """,
                (f"%{search}%", f"%{search}%", f"%{search}%"),
            ).fetchall()
        else:
            products = conn.execute(
                "SELECT * FROM products ORDER BY name"
            ).fetchall()
    return render_template("inventory.html", products=products, search=search)


@app.route("/inventory/add", methods=["POST"])
@login_required
@admin_required
def add_product():
    sku = request.form.get("sku", "").strip().upper()
    name = request.form.get("name", "").strip()
    price = float(request.form.get("price", 0) or 0)
    cost = float(request.form.get("cost", 0) or 0)
    stock = int(request.form.get("stock", 0) or 0)
    category = request.form.get("category", "General").strip() or "General"
    low_stock = int(request.form.get("low_stock_threshold", 5) or 5)
    description = request.form.get("description", "").strip()

    if not sku or not name or price < 0:
        flash("SKU, name, and valid price are required.", "error")
        return redirect(url_for("inventory"))

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO products (sku, name, description, price, cost, stock, category, low_stock_threshold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sku, name, description, price, cost, stock, category, low_stock),
            )
            product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """
                INSERT INTO inventory_logs (product_id, change_amount, previous_stock, new_stock, reason, created_by)
                VALUES (?, ?, 0, ?, 'Initial stock', ?)
                """,
                (product_id, stock, stock, session["user_id"]),
            )
        flash(f"Product '{name}' added successfully.", "success")
    except Exception:
        flash("Could not add product. SKU may already exist.", "error")
    return redirect(url_for("inventory"))


@app.route("/inventory/<int:product_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_product(product_id):
    name = request.form.get("name", "").strip()
    price = float(request.form.get("price", 0) or 0)
    cost = float(request.form.get("cost", 0) or 0)
    category = request.form.get("category", "General").strip() or "General"
    low_stock = int(request.form.get("low_stock_threshold", 5) or 5)
    description = request.form.get("description", "").strip()
    is_active = 1 if request.form.get("is_active") == "on" else 0

    with get_db() as conn:
        conn.execute(
            """
            UPDATE products
            SET name = ?, description = ?, price = ?, cost = ?, category = ?,
                low_stock_threshold = ?, is_active = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (name, description, price, cost, category, low_stock, is_active, product_id),
        )
    flash("Product updated.", "success")
    return redirect(url_for("inventory"))


@app.route("/inventory/<int:product_id>/adjust", methods=["POST"])
@login_required
@admin_required
def adjust_stock(product_id):
    change = int(request.form.get("change", 0) or 0)
    reason = request.form.get("reason", "Manual adjustment").strip() or "Manual adjustment"

    with get_db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("inventory"))

        new_stock = product["stock"] + change
        if new_stock < 0:
            flash("Stock cannot go below zero.", "error")
            return redirect(url_for("inventory"))

        conn.execute(
            "UPDATE products SET stock = ?, updated_at = datetime('now') WHERE id = ?",
            (new_stock, product_id),
        )
        conn.execute(
            """
            INSERT INTO inventory_logs (product_id, change_amount, previous_stock, new_stock, reason, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (product_id, change, product["stock"], new_stock, reason, session["user_id"]),
        )
    flash("Stock adjusted successfully.", "success")
    return redirect(url_for("inventory"))


@app.route("/pos")
@login_required
def pos():
    with get_db() as conn:
        products = conn.execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0 ORDER BY name"
        ).fetchall()
    return render_template("pos.html", products=products)


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    payment_method = data.get("payment_method", "cash")
    notes = data.get("notes", "")

    if not items:
        return jsonify({"error": "Cart is empty"}), 400

    sale_number = f"SALE-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"

    try:
        with get_db() as conn:
            total = 0.0
            line_items = []

            for item in items:
                product = conn.execute(
                    "SELECT * FROM products WHERE id = ? AND is_active = 1",
                    (item["product_id"],),
                ).fetchone()
                if not product:
                    return jsonify({"error": f"Product {item['product_id']} not found"}), 400

                qty = int(item["quantity"])
                if qty <= 0:
                    return jsonify({"error": "Invalid quantity"}), 400
                if product["stock"] < qty:
                    return jsonify(
                        {"error": f"Insufficient stock for {product['name']}"}
                    ), 400

                line_total = product["price"] * qty
                total += line_total
                line_items.append((product, qty, line_total))

            conn.execute(
                """
                INSERT INTO sales (sale_number, total_amount, payment_method, notes, created_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sale_number, total, payment_method, notes, session["user_id"]),
            )
            sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for product, qty, line_total in line_items:
                conn.execute(
                    """
                    INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, line_total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (sale_id, product["id"], product["name"], qty, product["price"], line_total),
                )
                new_stock = product["stock"] - qty
                conn.execute(
                    "UPDATE products SET stock = ?, updated_at = datetime('now') WHERE id = ?",
                    (new_stock, product["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO inventory_logs (product_id, change_amount, previous_stock, new_stock, reason, created_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product["id"],
                        -qty,
                        product["stock"],
                        new_stock,
                        f"Sale {sale_number}",
                        session["user_id"],
                    ),
                )

        return jsonify({"success": True, "sale_number": sale_number, "total": total})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sales")
@login_required
def sales_history():
    with get_db() as conn:
        sales = conn.execute(
            """
            SELECT s.*, u.username,
                   (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.id) AS item_count
            FROM sales s
            JOIN users u ON u.id = s.created_by
            ORDER BY s.created_at DESC
            """
        ).fetchall()
    return render_template("sales.html", sales=sales)


@app.route("/sales/<int:sale_id>")
@login_required
def sale_detail(sale_id):
    with get_db() as conn:
        sale = conn.execute(
            """
            SELECT s.*, u.username FROM sales s
            JOIN users u ON u.id = s.created_by
            WHERE s.id = ?
            """,
            (sale_id,),
        ).fetchone()
        if not sale:
            flash("Sale not found.", "error")
            return redirect(url_for("sales_history"))
        items = conn.execute(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id",
            (sale_id,),
        ).fetchall()
    return render_template("sale_detail.html", sale=sale, items=items)


@app.route("/inventory/logs")
@login_required
@admin_required
def inventory_logs():
    with get_db() as conn:
        logs = conn.execute(
            """
            SELECT l.*, p.name AS product_name, p.sku, u.username
            FROM inventory_logs l
            JOIN products p ON p.id = l.product_id
            JOIN users u ON u.id = l.created_by
            ORDER BY l.created_at DESC LIMIT 100
            """
        ).fetchall()
    return render_template("inventory_logs.html", logs=logs)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
