# YOKy Enterprise — Online POS System

A web-based POS application for **YOKy Enterprise**, a food spices retailer. Track inventory in singles, boxes, and rows; record sales; and print customer receipts.

## Features

- **Admin authentication** — Secure login with role-based access
- **Dashboard** — Overview of spices, low-stock alerts, and recent sales
- **Inventory management** (admin) — Add spices with single/box/row pricing and stock entry
- **Point of Sale** — Sell by single unit, box, or row with automatic stock deduction
- **Customer Receipts** — Create receipts with customer name and print instantly
- **Sales history** — Full transaction records with print option
- **Inventory logs** (admin) — Audit trail of all stock changes

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the server

```bash
python app.py
```

### 3. Open in browser

Go to [http://localhost:5000](http://localhost:5000)

### Default login

| Field    | Value     |
|----------|-----------|
| Username | `YOKy`          |
| Password | `559900ok`      |

## Unit Types

| Unit   | Description                                      |
|--------|--------------------------------------------------|
| Single | Individual spice packet/sachet                   |
| Box    | Carton of singles (default: 12 per box)          |
| Row    | Bulk pack / shelf row (default: 72 singles)      |

Stock is tracked internally in **single units**. Enter inventory using any combination of singles, boxes, and rows.

## Printing Receipts

1. **Point of Sale** — Complete sale → receipt opens and prints automatically
2. **Receipts** — Build a cart, enter customer name, click **Create & Print Receipt**
3. **Sales / Sale Detail** — Click **Print** on any past transaction

## Usage

1. **Login** as `YOKy`
2. **Inventory** — Add spices with prices per single, box, and row
3. **Point of Sale** or **Receipts** — Select products, choose unit type, checkout
4. **Sales** — View history and reprint receipts
5. **Stock Logs** — Monitor inventory changes

## Project Structure

```
POS/
├── app.py              # Main Flask application & routes
├── config.py           # YOKy Enterprise branding settings
├── db.py               # Database setup & migrations
├── units.py            # Single/box/row conversion helpers
├── requirements.txt    # Python dependencies
├── pos.db              # SQLite database (created on first run)
├── templates/          # HTML templates
└── static/             # CSS & JavaScript
```

## Deploying Online

```bash
python app.py
```

The app binds to `0.0.0.0:5000` so other devices on your network can access it at `http://<your-ip>:5000`.

For production on Windows:

```bash
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

## Security Notes

- Change the default admin password immediately
- Set a fixed `SECRET_KEY` in `app.py` for production
- Use HTTPS when exposing to the internet
- Back up `pos.db` regularly
