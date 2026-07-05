from config import UNIT_LABELS

VALID_UNITS = ("single", "box", "row")


def singles_per_unit(product, unit_type: str) -> int:
    if unit_type == "box":
        return max(1, int(product["units_per_box"]))
    if unit_type == "row":
        return max(1, int(product["units_per_row"]))
    return 1


def unit_price(product, unit_type: str) -> float:
    if unit_type == "box":
        return float(product["price_box"])
    if unit_type == "row":
        return float(product["price_row"])
    return float(product["price"])


def stock_count(product, unit_type: str) -> int:
    if unit_type == "box":
        return max(0, int(product.get("stock_boxes") or 0))
    if unit_type == "row":
        return max(0, int(product.get("stock_rows") or 0))
    return max(0, int(product.get("stock_singles") or 0))


def stock_in_units(product, unit_type: str) -> int:
    return stock_count(product, unit_type)


def total_stock_singles(product) -> int:
    return (
        stock_count(product, "single")
        + stock_count(product, "box") * singles_per_unit(product, "box")
        + stock_count(product, "row") * singles_per_unit(product, "row")
    )


def compute_total_stock(stock_singles: int, stock_boxes: int, stock_rows: int, units_per_box: int, units_per_row: int) -> int:
    return (
        max(0, int(stock_singles))
        + max(0, int(stock_boxes)) * max(1, int(units_per_box))
        + max(0, int(stock_rows)) * max(1, int(units_per_row))
    )


def to_singles(quantity: int, unit_type: str, product) -> int:
    return quantity * singles_per_unit(product, unit_type)


def from_mixed_units(singles: int, boxes: int, rows: int, product) -> int:
    return compute_total_stock(
        singles,
        boxes,
        rows,
        product["units_per_box"],
        product["units_per_row"],
    )


def apply_stock_adjustment(product, singles_delta: int, boxes_delta: int, rows_delta: int):
    stock_singles = stock_count(product, "single") + int(singles_delta)
    stock_boxes = stock_count(product, "box") + int(boxes_delta)
    stock_rows = stock_count(product, "row") + int(rows_delta)
    if stock_singles < 0 or stock_boxes < 0 or stock_rows < 0:
        return None
    total = compute_total_stock(
        stock_singles,
        stock_boxes,
        stock_rows,
        product["units_per_box"],
        product["units_per_row"],
    )
    return stock_singles, stock_boxes, stock_rows, total


def deduct_stock(product, unit_type: str, quantity: int):
    stock_singles = stock_count(product, "single")
    stock_boxes = stock_count(product, "box")
    stock_rows = stock_count(product, "row")
    if unit_type == "single":
        stock_singles -= quantity
    elif unit_type == "box":
        stock_boxes -= quantity
    elif unit_type == "row":
        stock_rows -= quantity
    if stock_singles < 0 or stock_boxes < 0 or stock_rows < 0:
        return None
    total = compute_total_stock(
        stock_singles,
        stock_boxes,
        stock_rows,
        product["units_per_box"],
        product["units_per_row"],
    )
    return stock_singles, stock_boxes, stock_rows, total


def has_any_stock(product) -> bool:
    return (
        stock_count(product, "single") > 0
        or stock_count(product, "box") > 0
        or stock_count(product, "row") > 0
    )


def unit_label(unit_type: str) -> str:
    return UNIT_LABELS.get(unit_type, unit_type.title())
