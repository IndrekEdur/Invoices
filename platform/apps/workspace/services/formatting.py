from decimal import Decimal, ROUND_HALF_UP


ZERO = Decimal("0")
DISPLAY_QUANT = Decimal("0.01")


def format_decimal(value, *, places=2, grouping=True):
    """Format Decimal values for Workspace presentation without changing source precision."""
    quant = Decimal("1").scaleb(-places)
    amount = Decimal(value or ZERO).quantize(quant, rounding=ROUND_HALF_UP)
    formatted = f"{amount:,.{places}f}" if grouping else f"{amount:.{places}f}"
    return formatted.replace(",", " ").replace(".", ",")


def format_money(value, currency=None):
    amount = format_decimal(value, places=2)
    return f"{amount} {currency}" if currency else amount


def format_percent(value, *, places=2):
    if value is None:
        return "-"
    return f"{format_decimal(value, places=places)}%"


def format_axis_number(value):
    return format_decimal(value, places=0)
