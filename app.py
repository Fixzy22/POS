import json
import os
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

from config import (
    COMPANY_ADDRESS,
    COMPANY_EMAIL,
    COMPANY_NAME,
    COMPANY_PHONE,
    COMPANY_TAGLINE,
    CURRENCY_SYMBOL,
    UNIT_LABELS,
)
from db import get_db, init_db, verify_user
from units import (
    from_mixed_units,
    singles_per_unit,
    stock_in_units,
    to_singles,
    unit_label,
    unit_price,
    VALID_UNITS,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


@app.context_processor
def inject_company():
    return {
        "company_name": COMPANY_NAME,
        "company_tagline": COMPANY_TAGLINE,
        "company_address": COMPANY_ADDRESS,
        "company_phone": COMPANY_PHONE,
        "company_email": COMPANY_EMAIL,
        "currency_symbol": CURRENCY_SYMBOL,
        "unit_labels": UNIT_LABELS,
    }


@app.template_filter("money")
def money_filter(value):
    try:
        return f"{CURRENCY_SYMBOL}{float(value):.2f}"
    except (TypeError, ValueError):
        return f"{CURRENCY_SYMBOL}0.00"


@app.template_filter("tojson")
def tojson_filter(value):
    if hasattr(value, "keys"):
        value = dict(value)
    return json.dumps(value)


@app.template_filter("unit_label")
def unit_label_filter(value):
    return unit_label(value)


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
    price_box = float(request.form.get("price_box", 0) or 0)
    price_row = float(request.form.get("price_row", 0) or 0)
    cost = float(request.form.get("cost", 0) or 0)
    units_per_box = max(1, int(request.form.get("units_per_box", 12) or 12))
    units_per_row = max(1, int(request.form.get("units_per_row", 72) or 72))
    stock_singles = int(request.form.get("stock_singles", 0) or 0)
    stock_boxes = int(request.form.get("stock_boxes", 0) or 0)
    stock_rows = int(request.form.get("stock_rows", 0) or 0)
    category = request.form.get("category", "Spices").strip() or "Spices"
    low_stock = int(request.form.get("low_stock_threshold", 5) or 5)
    description = request.form.get("description", "").strip()

    if not sku or not name or price < 0:
        flash("SKU, name, and valid single-unit price are required.", "error")
        return redirect(url_for("inventory"))

    if price_box <= 0:
        price_box = price * units_per_box
    if price_row <= 0:
        price_row = price * units_per_row

    stock = stock_singles + stock_boxes * units_per_box + stock_rows * units_per_row

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO products (
                    sku, name, description, price, price_box, price_row, cost, stock,
                    units_per_box, units_per_row, category, low_stock_threshold
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sku, name, description, price, price_box, price_row, cost, stock,
                    units_per_box, units_per_row, category, low_stock,
                ),
            )
            product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """
                INSERT INTO inventory_logs (product_id, change_amount, previous_stock, new_stock, reason, created_by)
                VALUES (?, ?, 0, ?, 'Initial stock', ?)
                """,
                (product_id, stock, stock, session["user_id"]),
            )
        flash(f"Spice '{name}' added successfully.", "success")
    except Exception:
        flash("Could not add product. SKU may already exist.", "error")
    return redirect(url_for("inventory"))


@app.route("/inventory/<int:product_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_product(product_id):
    name = request.form.get("name", "").strip()
    price = float(request.form.get("price", 0) or 0)
    price_box = float(request.form.get("price_box", 0) or 0)
    price_row = float(request.form.get("price_row", 0) or 0)
    cost = float(request.form.get("cost", 0) or 0)
    units_per_box = max(1, int(request.form.get("units_per_box", 12) or 12))
    units_per_row = max(1, int(request.form.get("units_per_row", 72) or 72))
    category = request.form.get("category", "Spices").strip() or "Spices"
    low_stock = int(request.form.get("low_stock_threshold", 5) or 5)
    description = request.form.get("description", "").strip()
    is_active = 1 if request.form.get("is_active") == "on" else 0

    if price_box <= 0:
        price_box = price * units_per_box
    if price_row <= 0:
        price_row = price * units_per_row

    with get_db() as conn:
        conn.execute(
            """
            UPDATE products
            SET name = ?, description = ?, price = ?, price_box = ?, price_row = ?,
                cost = ?, units_per_box = ?, units_per_row = ?, category = ?,
                low_stock_threshold = ?, is_active = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                name, description, price, price_box, price_row, cost,
                units_per_box, units_per_row, category, low_stock, is_active, product_id,
            ),
        )
    flash("Product updated.", "success")
    return redirect(url_for("inventory"))


@app.route("/inventory/<int:product_id>/adjust", methods=["POST"])
@login_required
@admin_required
def adjust_stock(product_id):
    singles = int(request.form.get("adj_singles", 0) or 0)
    boxes = int(request.form.get("adj_boxes", 0) or 0)
    rows = int(request.form.get("adj_rows", 0) or 0)
    reason = request.form.get("reason", "Manual adjustment").strip() or "Manual adjustment"

    with get_db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("inventory"))

        change = from_mixed_units(singles, boxes, rows, product)
        if change == 0:
            flash("Enter a quantity to adjust.", "error")
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


@app.route("/inventory/<int:product_id>/clear-stock", methods=["POST"])
@login_required
@admin_required
def clear_stock(product_id):
    with get_db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("inventory"))

        if product["stock"] == 0:
            flash("Stock is already zero.", "error")
            return redirect(url_for("inventory"))

        conn.execute(
            "UPDATE products SET stock = 0, updated_at = datetime('now') WHERE id = ?",
            (product_id,),
        )
        conn.execute(
            """
            INSERT INTO inventory_logs (product_id, change_amount, previous_stock, new_stock, reason, created_by)
            VALUES (?, ?, ?, 0, 'Stock cleared', ?)
            """,
            (product_id, -product["stock"], product["stock"], session["user_id"]),
        )
    flash(f"All stock removed for '{product['name']}'.", "success")
    return redirect(url_for("inventory"))


@app.route("/inventory/<int:product_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_product(product_id):
    with get_db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("inventory"))

        sale_count = conn.execute(
            "SELECT COUNT(*) AS c FROM sale_items WHERE product_id = ?",
            (product_id,),
        ).fetchone()["c"]
        if sale_count > 0:
            flash(
                f"Cannot delete '{product['name']}' — it has sales history. Deactivate it instead.",
                "error",
            )
            return redirect(url_for("inventory"))

        conn.execute("DELETE FROM inventory_logs WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    flash(f"Product '{product['name']}' removed from inventory.", "success")
    return redirect(url_for("inventory"))


@app.route("/pos")
@login_required
def pos():
    with get_db() as conn:
        products = conn.execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0 ORDER BY name"
        ).fetchall()
    products_json = []
    for p in products:
        products_json.append({
            "id": p["id"],
            "name": p["name"],
            "sku": p["sku"],
            "price": p["price"],
            "price_box": p["price_box"],
            "price_row": p["price_row"],
            "stock": p["stock"],
            "units_per_box": p["units_per_box"],
            "units_per_row": p["units_per_row"],
            "stock_single": stock_in_units(p, "single"),
            "stock_box": stock_in_units(p, "box"),
            "stock_row": stock_in_units(p, "row"),
        })
    return render_template("pos.html", products=products, products_json=products_json)


@app.route("/receipts")
@login_required
def receipts():
    with get_db() as conn:
        products = conn.execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0 ORDER BY name"
        ).fetchall()
        recent_sales = conn.execute(
            """
            SELECT s.*, u.username,
                   (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.id) AS item_count
            FROM sales s
            JOIN users u ON u.id = s.created_by
            ORDER BY s.created_at DESC LIMIT 20
            """
        ).fetchall()
    products_json = []
    for p in products:
        products_json.append({
            "id": p["id"],
            "name": p["name"],
            "sku": p["sku"],
            "price": p["price"],
            "price_box": p["price_box"],
            "price_row": p["price_row"],
            "stock": p["stock"],
            "units_per_box": p["units_per_box"],
            "units_per_row": p["units_per_row"],
            "stock_single": stock_in_units(p, "single"),
            "stock_box": stock_in_units(p, "box"),
            "stock_row": stock_in_units(p, "row"),
        })
    return render_template(
        "receipts.html",
        products_json=products_json,
        recent_sales=recent_sales,
    )


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    payment_method = data.get("payment_method", "cash")
    customer_name = data.get("customer_name", "").strip()
    notes = data.get("notes", "")

    if not items:
        return jsonify({"error": "Cart is empty"}), 400

    sale_number = f"YOKY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"

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

                unit_type = item.get("unit_type", "single")
                if unit_type not in VALID_UNITS:
                    return jsonify({"error": "Invalid unit type"}), 400

                qty = int(item["quantity"])
                if qty <= 0:
                    return jsonify({"error": "Invalid quantity"}), 400

                base_qty = to_singles(qty, unit_type, product)
                if product["stock"] < base_qty:
                    return jsonify(
                        {"error": f"Insufficient stock for {product['name']} ({unit_label(unit_type)})"}
                    ), 400

                price = unit_price(product, unit_type)
                line_total = price * qty
                total += line_total
                line_items.append((product, qty, unit_type, base_qty, price, line_total))

            conn.execute(
                """
                INSERT INTO sales (sale_number, total_amount, payment_method, customer_name, notes, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sale_number, total, payment_method, customer_name, notes, session["user_id"]),
            )
            sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for product, qty, unit_type, base_qty, price, line_total in line_items:
                display_name = f"{product['name']} ({unit_label(unit_type)})"
                conn.execute(
                    """
                    INSERT INTO sale_items (
                        sale_id, product_id, product_name, quantity, unit_type,
                        base_quantity, unit_price, line_total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id, product["id"], display_name, qty, unit_type,
                        base_qty, price, line_total,
                    ),
                )
                new_stock = product["stock"] - base_qty
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
                        -base_qty,
                        product["stock"],
                        new_stock,
                        f"Sale {sale_number}",
                        session["user_id"],
                    ),
                )

        return jsonify({
            "success": True,
            "sale_id": sale_id,
            "sale_number": sale_number,
            "total": total,
        })
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


@app.route("/sales/<int:sale_id>/receipt")
@login_required
def sale_receipt(sale_id):
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
            return redirect(url_for("receipts"))
        items = conn.execute(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id",
            (sale_id,),
        ).fetchall()
    auto_print = request.args.get("print") == "1"
    return render_template(
        "receipt.html",
        sale=sale,
        items=items,
        auto_print=auto_print,
    )


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
