"""Money helpers: Decimal parsing, 2-dp serialisation and Indian-format display.

Implements the AGENTS.md money rule (and policy preamble "All values are in INR"):
every amount is a Decimal, thresholds compare unrounded values, and rounding to
two decimals happens only when a value is serialised.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
CENT = Decimal("0.01")


class MoneyError(ValueError):
    """Raised when a value cannot be read as a Decimal amount."""


def to_decimal(value: object) -> Decimal:
    """Convert a CSV/JSON value to Decimal without passing through float.

    Accepts Decimal, int, str (with optional Indian or Western thousands
    separators and an optional currency prefix). Floats are converted via
    their shortest repr, which is exact for the values JSON can carry.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise MoneyError(f"not a number: {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip().replace("₹", "").replace("INR", "").replace(",", "").strip()
        if not text:
            raise MoneyError("empty value")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"not a number: {value!r}") from exc
        if not result.is_finite():
            raise MoneyError(f"not a finite number: {value!r}")
        return result
    raise MoneyError(f"not a number: {value!r}")


def optional_decimal(value: object) -> Decimal | None:
    """Like to_decimal, but '' / None become None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return to_decimal(value)


def q2(value: Decimal) -> Decimal:
    """Round half-up to 2 decimal places (serialisation only)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt2(value: Decimal | None) -> str:
    """Serialise an amount with exactly two decimals; None becomes ''."""
    if value is None:
        return ""
    return f"{q2(value):f}"


def fmt_plain(value: Decimal) -> str:
    """Serialise a non-money number without exponent or trailing zeros (e.g. 4610, 0.5)."""
    text = f"{value.normalize():f}"
    return text


def group_indian(integer_digits: str) -> str:
    """Group an unsigned digit string the Indian way: 12,34,56,789."""
    if len(integer_digits) <= 3:
        return integer_digits
    head, tail = integer_digits[:-3], integer_digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join([*pairs, tail])


def format_inr(value: Decimal, *, decimals: int = 0, symbol: str = "₹") -> str:
    """Display an amount in Indian format, e.g. ₹1,37,531 or ₹7.06 (decimals=2)."""
    exponent = Decimal(1).scaleb(-decimals)
    rounded = value.quantize(exponent, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    text = f"{abs(rounded):f}"
    whole, _, frac = text.partition(".")
    grouped = group_indian(whole)
    return f"{sign}{symbol}{grouped}{'.' + frac if frac else ''}"


def parse_indian_amount(text: str) -> Decimal:
    """Parse amounts such as '60,00,000', 'INR 8,00,000' or '3,537.76'."""
    return to_decimal(text)
