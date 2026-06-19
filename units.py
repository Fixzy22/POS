from config import UNIT_LABELS

VALID_UNITS = ("single", "box", "row")


def singles_per_unit(product, unit_type: str) -> int:
    if unit_type == "box":
        return max(1, int(product["units_per_box"]))
    if unit_type == "row":
        return max(1, int(product["units_per_row"]))
    return 1


def unit_price(product, unit_type: str) -> float:
    if unit_type == "box" and product["price_box"] > 0:
        return float(product["price_box"])
    if unit_type == "row" and product["price_row"] > 0:
        return float(product["price_row"])
    return float(product["price"]) * singles_per_unit(product, unit_type)


def stock_in_units(product, unit_type: str) -> int:
    singles = int(product["stock"])
    per = singles_per_unit(product, unit_type)
    return singles // per


def to_singles(quantity: int, unit_type: str, product) -> int:
    return quantity * singles_per_unit(product, unit_type)


def from_mixed_units(singles: int, boxes: int, rows: int, product) -> int:
    return (
        int(singles)
        + int(boxes) * singles_per_unit(product, "box")
        + int(rows) * singles_per_unit(product, "row")
    )


def unit_label(unit_type: str) -> str:
    return UNIT_LABELS.get(unit_type, unit_type.title())
