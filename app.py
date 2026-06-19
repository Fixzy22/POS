import json
import os
import secrets
from datetime import date, datetime
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
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    COMPANY_ADDRESS,
    COMPANY_EMAIL,
    COMPANY_NAME,
    COMPANY_PHONE,
    COMPANY_TAGLINE,
    CURRENCY_SYMBOL,
    UNIT_LABELS,
)
from db import create_user, get_db, init_db, list_users, update_user_password, verify_user
from reports import fetch_dashboard_revenue, fetch_revenue
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
        "current_year": datetime.now().year,
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
            return redirect(url_for("home"))
        return f(*args, **kwargs)

    return decorated


def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "user":
            flash("This area is for staff users only.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)

    return decorated


def home_redirect():
    if session.get("role") == "admin":
        return redirect(url_for("dashboard"))
    return redirect(url_for("pos"))


@app.before_request
def ensure_db():
    init_db()


@app.route("/")
def index():
    if "user_id" in session:
        return home_redirect()
    return redirect(url_for("login"))


@app.route("/home")
@login_required
def home():
    return home_redirect()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = verify_user(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user.get("full_name") or ""
            session["role"] = user["role"]
            display = user.get("full_name") or user["username"]
            flash(f"Welcome back, {display}!", "success")
            if user["role"] == "admin":
                return redirect(url_for("dashboard"))
            return redirect(url_for("pos"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
@admin_required
def dashboard():
    with get_db() as conn:
        revenue = fetch_dashboard_revenue(conn)
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
            SELECT s.*, u.username, u.full_name
            FROM sales s
            JOIN users u ON u.id = s.created_by
            ORDER BY s.created_at DESC LIMIT 8
            """
        ).fetchall()
    return render_template(
        "dashboard.html",
        stats=stats,
        revenue=revenue,
        low_stock_products=low_stock_products,
        recent_sales=recent_sales,
    )


@app.route("/inventory")
@login_required
def inventory():
    search = request.args.get("q", "").strip()
    with get_db() as conn:
        if search:
            products = conn.execute(
                """
                SELECT * FROM products
                WHERE is_active = 1 AND (name LIKE ? OR sku LIKE ? OR category LIKE ?)
                ORDER BY name
                """,
                (f"%{search}%", f"%{search}%", f"%{search}%"),
            ).fetchall()
        else:
            products = conn.execute(
                "SELECT * FROM products WHERE is_active = 1 ORDER BY name"
            ).fetchall()
    return render_template(
        "inventory.html",
        products=products,
        search=search,
        can_manage_inventory=True,
    )


@app.route("/inventory/add", methods=["POST"])
@login_required
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
            if product["stock"] > 0:
                conn.execute(
                    """
                    INSERT INTO inventory_logs (product_id, change_amount, previous_stock, new_stock, reason, created_by)
                    VALUES (?, ?, ?, 0, 'Stock cleared on product removal', ?)
                    """,
                    (product_id, -product["stock"], product["stock"], session["user_id"]),
                )
            conn.execute(
                """
                UPDATE products
                SET is_active = 0, stock = 0, updated_at = datetime('now')
                WHERE id = ?
                """,
                (product_id,),
            )
            flash(
                f"'{product['name']}' removed from inventory. Past sales records are kept.",
                "success",
            )
        else:
            conn.execute("DELETE FROM inventory_logs WHERE product_id = ?", (product_id,))
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            flash(f"Product '{product['name']}' permanently deleted.", "success")
    return redirect(url_for("inventory"))


@app.route("/pos")
@login_required
@staff_required
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
@staff_required
def receipts():
    with get_db() as conn:
        products = conn.execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0 ORDER BY name"
        ).fetchall()
        recent_sales = conn.execute(
            """
            SELECT s.*, u.username, u.full_name,
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
@staff_required
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
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    is_admin = session.get("role") == "admin"

    with get_db() as conn:
        params = []
        date_clause = ""
        if is_admin and date_from:
            date_clause += " AND date(s.created_at) >= ?"
            params.append(date_from)
        if is_admin and date_to:
            date_clause += " AND date(s.created_at) <= ?"
            params.append(date_to)

        if session.get("role") == "user":
            sales = conn.execute(
                f"""
                SELECT s.*, u.username, u.full_name,
                       (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.id) AS item_count
                FROM sales s
                JOIN users u ON u.id = s.created_by
                WHERE s.created_by = ?
                ORDER BY s.created_at DESC
                """,
                (session["user_id"],),
            ).fetchall()
            period_revenue = None
        else:
            sales = conn.execute(
                f"""
                SELECT s.*, u.username, u.full_name,
                       (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.id) AS item_count
                FROM sales s
                JOIN users u ON u.id = s.created_by
                WHERE 1=1{date_clause}
                ORDER BY s.created_at DESC
                """,
                params,
            ).fetchall()

            if date_from or date_to:
                start = date.fromisoformat(date_from) if date_from else date(1900, 1, 1)
                end = date.fromisoformat(date_to) if date_to else date.today()
                if start > end:
                    start, end = end, start
                period_revenue = fetch_revenue(conn, start, end)
                period_revenue["date_from"] = start.isoformat()
                period_revenue["date_to"] = end.isoformat()
            else:
                period_revenue = fetch_dashboard_revenue(conn)

    return render_template(
        "sales.html",
        sales=sales,
        is_admin=is_admin,
        date_from=date_from,
        date_to=date_to,
        period_revenue=period_revenue,
    )


@app.route("/sales/<int:sale_id>")
@login_required
def sale_detail(sale_id):
    with get_db() as conn:
        sale = conn.execute(
            """
            SELECT s.*, u.username, u.full_name FROM sales s
            JOIN users u ON u.id = s.created_by
            WHERE s.id = ?
            """,
            (sale_id,),
        ).fetchone()
        if not sale:
            flash("Sale not found.", "error")
            return redirect(url_for("sales_history"))
        if session.get("role") == "user" and sale["created_by"] != session["user_id"]:
            flash("You can only view your own sales.", "error")
            return redirect(url_for("sales_history"))
        items = conn.execute(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id",
            (sale_id,),
        ).fetchall()
    return render_template(
        "sale_detail.html",
        sale=sale,
        items=items,
        is_admin=session.get("role") == "admin",
    )


@app.route("/sales/<int:sale_id>/receipt")
@login_required
def sale_receipt(sale_id):
    with get_db() as conn:
        sale = conn.execute(
            """
            SELECT s.*, u.username, u.full_name FROM sales s
            JOIN users u ON u.id = s.created_by
            WHERE s.id = ?
            """,
            (sale_id,),
        ).fetchone()
        if not sale:
            flash("Sale not found.", "error")
            return redirect(url_for("receipts") if session.get("role") == "user" else url_for("sales_history"))
        if session.get("role") == "user" and sale["created_by"] != session["user_id"]:
            flash("You can only view your own receipts.", "error")
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
            SELECT l.*, p.name AS product_name, p.sku, u.username, u.full_name
            FROM inventory_logs l
            JOIN products p ON p.id = l.product_id
            JOIN users u ON u.id = l.created_by
            ORDER BY l.created_at DESC LIMIT 100
            """
        ).fetchall()
    return render_template("inventory_logs.html", logs=logs)


def _clear_sales_in_range(conn, date_from: str | None, date_to: str | None):
    clauses = []
    params = []
    if date_from:
        clauses.append("date(created_at) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date(created_at) <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    sales = conn.execute(
        f"SELECT id, sale_number FROM sales {where}",
        params,
    ).fetchall()
    if not sales:
        return 0

    sale_ids = [s["id"] for s in sales]
    placeholders = ",".join("?" * len(sale_ids))
    conn.execute(f"DELETE FROM sale_items WHERE sale_id IN ({placeholders})", sale_ids)

    for sale in sales:
        conn.execute(
            "DELETE FROM inventory_logs WHERE reason = ?",
            (f"Sale {sale['sale_number']}",),
        )

    conn.execute(f"DELETE FROM sales {where}", params)
    return len(sales)


def _delete_sale(conn, sale_id: int) -> bool:
    sale = conn.execute(
        "SELECT id, sale_number FROM sales WHERE id = ?", (sale_id,)
    ).fetchone()
    if not sale:
        return False

    conn.execute("DELETE FROM sale_items WHERE sale_id = ?", (sale_id,))
    conn.execute(
        "DELETE FROM inventory_logs WHERE reason = ?",
        (f"Sale {sale['sale_number']}",),
    )
    conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
    return True


@app.route("/admin/sales/clear-all", methods=["POST"])
@login_required
@admin_required
def admin_clear_all_sales():
    confirm = request.form.get("confirm_text", "").strip().upper()
    if confirm != "CLEAR ALL":
        flash('Type CLEAR ALL to permanently delete every sale and receipt.', "error")
        return redirect(url_for("sales_history"))

    try:
        with get_db() as conn:
            deleted = _clear_sales_in_range(conn, None, None)
    except Exception:
        flash("Could not clear sales records. Please try again.", "error")
        return redirect(url_for("sales_history"))

    flash(f"All sales records cleared ({deleted} sales removed).", "success")
    return redirect(url_for("sales_history"))


@app.route("/admin/sales/clear-range", methods=["POST"])
@login_required
@admin_required
def admin_clear_sales_range():
    date_from = request.form.get("date_from", "").strip()
    date_to = request.form.get("date_to", "").strip()
    confirm = request.form.get("confirm_text", "").strip().upper()

    if not date_from and not date_to:
        flash("Select a date range to clear.", "error")
        return redirect(url_for("sales_history"))
    if confirm != "CLEAR":
        flash('Type CLEAR to delete sales in the selected date range.', "error")
        return redirect(url_for("sales_history", date_from=date_from, date_to=date_to))

    try:
        with get_db() as conn:
            deleted = _clear_sales_in_range(conn, date_from or None, date_to or None)
    except Exception:
        flash("Could not clear sales for that date range. Please try again.", "error")
        return redirect(url_for("sales_history", date_from=date_from, date_to=date_to))

    flash(f"Removed {deleted} sales from the selected period.", "success")
    return redirect(url_for("sales_history", date_from=date_from, date_to=date_to))


@app.route("/admin/sales/<int:sale_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_sale(sale_id):
    confirm = request.form.get("confirm_text", "").strip().upper()
    if confirm != "DELETE":
        flash('Type DELETE to remove this sale record.', "error")
        return redirect(url_for("sale_detail", sale_id=sale_id))

    try:
        with get_db() as conn:
            if not _delete_sale(conn, sale_id):
                flash("Sale not found.", "error")
                return redirect(url_for("sales_history"))
    except Exception:
        flash("Could not delete this sale record.", "error")
        return redirect(url_for("sale_detail", sale_id=sale_id))

    flash("Sale record and receipt removed.", "success")
    return redirect(url_for("sales_history"))


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = list_users()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
@login_required
@admin_required
def admin_add_user():
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("admin_users"))
    if len(password) < 4:
        flash("Password must be at least 4 characters.", "error")
        return redirect(url_for("admin_users"))
    if password != confirm:
        flash("Passwords do not match.", "error")
        return redirect(url_for("admin_users"))
    if username.lower() == ADMIN_USERNAME.lower():
        flash("That username is reserved for the admin account.", "error")
        return redirect(url_for("admin_users"))

    try:
        create_user(username, password, full_name, role="user")
        flash(f"Staff user '{username}' created successfully.", "success")
    except Exception:
        flash("Could not create user. Username may already exist.", "error")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/edit", methods=["POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "").strip()
    confirm = request.form.get("confirm_password", "").strip()
    is_active = 1 if request.form.get("is_active") == "on" else 0

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("admin_users"))
        if user["role"] == "admin" and user_id != session["user_id"]:
            flash("Admin accounts cannot be edited here.", "error")
            return redirect(url_for("admin_users"))
        if user_id == session["user_id"] and not is_active:
            flash("You cannot deactivate your own account.", "error")
            return redirect(url_for("admin_users"))

        conn.execute(
            "UPDATE users SET full_name = ?, is_active = ? WHERE id = ?",
            (full_name, is_active, user_id),
        )

    if password:
        if len(password) < 4:
            flash("Password must be at least 4 characters.", "error")
            return redirect(url_for("admin_users"))
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("admin_users"))
        update_user_password(user_id, password)

    flash(f"User '{user['username']}' updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin_users"))

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("admin_users"))
        if user["role"] == "admin":
            flash("Admin accounts cannot be deleted.", "error")
            return redirect(url_for("admin_users"))

        sale_count = conn.execute(
            "SELECT COUNT(*) AS c FROM sales WHERE created_by = ?", (user_id,)
        ).fetchone()["c"]
        if sale_count > 0:
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
            flash(
                f"User '{user['username']}' has sales history and was deactivated instead of deleted.",
                "success",
            )
        else:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            flash(f"User '{user['username']}' removed.", "success")
    return redirect(url_for("admin_users"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
