from datetime import date, timedelta


def period_bounds():
    today = date.today()
    return {
        "today": today,
        "week_start": today - timedelta(days=today.weekday()),
        "month_start": today.replace(day=1),
    }


def fetch_revenue(conn, start: date, end: date):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS revenue,
               COUNT(*) AS transactions
        FROM sales
        WHERE date(created_at) >= ? AND date(created_at) <= ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    return {"revenue": row["revenue"], "transactions": row["transactions"]}


def fetch_dashboard_revenue(conn):
    bounds = period_bounds()
    today = bounds["today"]
    all_time = conn.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS revenue,
               COUNT(*) AS transactions
        FROM sales
        """
    ).fetchone()
    return {
        "today": fetch_revenue(conn, today, today),
        "week": fetch_revenue(conn, bounds["week_start"], today),
        "month": fetch_revenue(conn, bounds["month_start"], today),
        "all_time": {"revenue": all_time["revenue"], "transactions": all_time["transactions"]},
        "week_start": bounds["week_start"].isoformat(),
        "month_start": bounds["month_start"].isoformat(),
    }
