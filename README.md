# ShopPOS — Online Point of Sale System

A web-based POS application for tracking inventory, recording sales, and monitoring store performance. Built with Python Flask and SQLite.

## Features

- **Admin authentication** — Secure login with role-based access
- **Dashboard** — Overview of products, low-stock alerts, and recent sales
- **Inventory management** (admin) — Add, edit, adjust stock, search products
- **Point of Sale** — Quick checkout with cart, payment methods, auto stock deduction
- **Sales history** — Full transaction records with line-item details
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
| Username | `admin`   |
| Password | `admin123` |

Change the default password before deploying to production.

## Usage

1. **Login** as admin
2. **Inventory** — Review sample products or add your own
3. **Point of Sale** — Click products to add to cart, then complete sale
4. **Sales** — View all transactions and details
5. **Stock Logs** — Monitor every inventory change

## Project Structure

```
POS/
├── app.py              # Main Flask application & routes
├── db.py               # Database setup & auth helpers
├── requirements.txt    # Python dependencies
├── pos.db              # SQLite database (created on first run)
├── templates/          # HTML templates
└── static/             # CSS & JavaScript
```

## Deploying Online

To run on a network or cloud server:

```bash
python app.py
```

The app binds to `0.0.0.0:5000` so other devices on your network can access it at `http://<your-ip>:5000`.

For production deployment, use a WSGI server like Gunicorn (Linux) or Waitress (Windows):

```bash
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

## Security Notes

- Change the default admin password immediately
- Set a fixed `SECRET_KEY` in `app.py` for production (instead of random generation)
- Use HTTPS when exposing to the internet
- Back up `pos.db` regularly
