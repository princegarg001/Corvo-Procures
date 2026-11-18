"""Deterministic chat parser (PLAN §9): quantities and units, plant names, relative dates in
IST, urgency words, yes/no, prices, and the leftover item text. Works with no LLM.

Plant aliases are derived from the plants master (code and the words of its name), so
"Chakan", "chakan plant", "Bhosari", "Pune" and the codes all resolve without hard-coding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from procure_engine.models import Plant
from procure_engine.money import MoneyError, to_decimal

UOM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "NOS": ("nos", "no", "nos.", "pcs", "pc", "piece", "pieces", "unit", "units", "number", "numbers", "qty", "ea", "each"),
    "PAIR": ("pair", "pairs", "pr", "prs"),
    "KG": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"),
    "LTR": ("l", "ltr", "ltrs", "litre", "litres", "liter", "liters", "lit"),
    "MTR": ("m", "mtr", "mtrs", "meter", "meters", "metre", "metres", "rmt"),
    "SET": ("set", "sets", "kit", "kits"),
    "ROL": ("rol", "roll", "rolls"),
    "CYL": ("cyl", "cylinder", "cylinders"),
    "REAM": ("ream", "reams"),
    "BKT": ("bkt", "bucket", "buckets"),
    "BRL": ("brl", "barrel", "barrels", "drum", "drums"),
    "JOB": ("job", "jobs", "visit", "visits"),
    "MON": ("mon", "month", "months"),
    "QTR": ("qtr", "quarter", "quarters"),
}
UNIT_WORD = {w: u for u, words in UOM_SYNONYMS.items() for w in words}
URGENT = re.compile(r"\b(urgent(ly)?|asap|emergency|breakdown|immediately|right away|critical|jaldi|turant|line (is )?down)\b",
                    re.IGNORECASE)
YES = re.compile(r"^\s*(y|yes|yeah|yep|ok|okay|sure|correct|right|confirm(ed)?|haan|ha|ji|done|go ahead|create( it)?|submit)\b",
                 re.IGNORECASE)
NO = re.compile(r"^\s*(n|no|nope|nahi|nahin|not really|wrong|cancel)\b", re.IGNORECASE)
FILLER = {
    "i", "we", "need", "needs", "needed", "want", "wants", "require", "required", "requires", "please", "pls", "plz",
    "kindly", "for", "of", "the", "a", "an", "some", "to", "order", "get", "buy", "procure", "raise", "pr", "at",
    "in", "by", "before", "on", "until", "till", "and", "with", "our", "my", "us", "me", "plant", "site", "urgent",
    "urgently", "asap", "chahiye", "ke", "liye", "tak", "hai", "hain", "ka", "ki", "ko", "mujhe", "humein", "hume",
    "do", "dena", "bhejo", "about", "approx", "approximately", "around", "can", "you", "could", "would", "like",
    "emergency", "immediately", "is", "are", "it", "this", "that", "new", "item", "also", "plus", "more",
    "each", "per", "rate", "qty", "quantity", "x", "nos", "pcs", "make", "change", "instead", "update", "actually",
    "only", "just", "sorry",
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "fifty": 50, "hundred": 100, "dozen": 12}
_QTY = re.compile(r"(?<![\w./-])(\d+(?:[.,]\d+)?)\s*(" + "|".join(sorted(map(re.escape, UNIT_WORD), key=len, reverse=True)) +
                  r")?(?![\w/])(?!\s*(?:mm|inch|ton|hp|kw|lph|gsm|micron|sqmm|cum|pole|core|w\b|a\b|x))",
                  re.IGNORECASE)
_DATE_PHRASE = re.compile(
    r"\b(?:by|before|on|until|till|latest by|need(?:ed)? by|deliver(?:y|ed)? by)\s+(.+?)(?=$|[,.;!?]|\s+(?:for|at|to|in|of|and)\s)"
    r"|(\b(?:next|this|coming)\s+(?:week|month|" + "|".join(WEEKDAYS) + r")\b(?:\s+tak)?)"
    r"|(\bin\s+\d+\s+(?:days?|weeks?|months?)\b)"
    r"|(\b(?:today|tomorrow|day after tomorrow|end of (?:the )?month|month end)\b)"
    r"|(\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:\s+\d{4})?\b)"
    r"|(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b)"
    r"|(\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b)"
    r"|(\b(?:" + "|".join(WEEKDAYS) + r")\b(?:\s+tak)?)",
    re.IGNORECASE,
)
_PRICE = re.compile(r"(?:₹|\brs\.?|\binr)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lakhs|l)?\b|\b(\d[\d,]*(?:\.\d+)?)\s*(?:rs|rupees|inr|/-)"
                    r"|\b(?:price|cost|estimate[d]?|approx\.?|about|around|@)\s*(?:is|of|:)?\s*(?:₹|rs\.?)?\s*(\d[\d,]*(?:\.\d+)?)",
                    re.IGNORECASE)


@dataclass
class Parsed:
    items: list[tuple[str, Decimal | None, str | None]] = field(default_factory=list)  # (text, qty, uom)
    plant: str | None = None
    need_by: date | None = None
    need_by_text: str = ""
    urgent_words: list[str] = field(default_factory=list)
    price: Decimal | None = None
    yes: bool = False
    no: bool = False


def plant_aliases(plants: dict[str, Plant]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for code, p in plants.items():
        aliases[code.lower()] = code
        for w in re.findall(r"[a-z]+", p.name.lower()):
            if w not in ("plant", "site", "the", "unit"):
                aliases[w] = code
    return aliases


def find_plant(text: str, plants: dict[str, Plant]) -> str | None:
    low = text.lower()
    found = []
    for alias, code in plant_aliases(plants).items():
        m = re.search(rf"\b{re.escape(alias)}\b", low)
        if m:
            found.append((m.start(), code))
    codes = {c for _, c in found}
    if len(codes) == 1:
        return codes.pop()
    if len(codes) > 1:  # e.g. "Pune - Bhosari" is one plant; prefer the most specific, first mention
        return sorted(found)[0][1]
    return None


def next_weekday(today: date, weekday: int, *, next_week: bool) -> date:
    if next_week:
        monday_next = today + timedelta(days=7 - today.weekday())
        return monday_next + timedelta(days=weekday)
    ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def parse_date_phrase(phrase: str, today: date) -> date | None:
    p = phrase.strip().lower().removesuffix(" tak").strip()
    if not p:
        return None
    for i, wd in enumerate(WEEKDAYS):
        if re.fullmatch(rf"(?:next|coming)\s+{wd}", p):
            return next_weekday(today, i, next_week=p.startswith("next"))
        if re.fullmatch(rf"(?:this\s+)?{wd}", p):
            return next_weekday(today, i, next_week=False)
    if p in ("today",):
        return today
    if p == "tomorrow":
        return today + timedelta(days=1)
    if p == "day after tomorrow":
        return today + timedelta(days=2)
    if p in ("next week",):
        return next_weekday(today, 0, next_week=True)
    if p in ("end of month", "end of the month", "month end", "this month"):
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    if p == "next month":
        return (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    m = re.fullmatch(r"in\s+(\d+)\s+(day|days|week|weeks|month|months)", p)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        return today + timedelta(days=n * (1 if unit.startswith("day") else 7 if unit.startswith("week") else 30))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", p)
    if m:
        day = int(m.group(1))
        try:
            d = today.replace(day=day)
        except ValueError:
            return None
        if d < today:
            d = (today.replace(day=28) + timedelta(days=4)).replace(day=day)
        return d
    import dateparser

    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", p).replace(" of ", " ")
    parsed = dateparser.parse(cleaned, settings={
        "RELATIVE_BASE": datetime(today.year, today.month, today.day), "PREFER_DATES_FROM": "future",
        "DATE_ORDER": "DMY"})
    return parsed.date() if parsed else None


def find_date(text: str, today: date) -> tuple[date | None, str]:
    for m in _DATE_PHRASE.finditer(text):
        phrase = next(g for g in m.groups() if g)
        d = parse_date_phrase(phrase, today)
        if d is not None:
            return d, m.group(0).strip()
    return None, ""


def find_price(text: str) -> Decimal | None:
    m = _PRICE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(3) or m.group(4)
    try:
        value = to_decimal(raw)
    except MoneyError:
        return None
    unit = (m.group(2) or "").lower()
    if unit == "k":
        value *= 1000
    elif unit in ("lakh", "lakhs", "l"):
        value *= 100000
    return value


def _clean_item_text(text: str, plants: dict[str, Plant]) -> str:
    s = text
    for alias in plant_aliases(plants):
        s = re.sub(rf"\b{re.escape(alias)}\b", " ", s, flags=re.IGNORECASE)
    tokens = [t for t in re.split(r"\s+", s) if t]
    kept = [t.strip(",;:!?") for t in tokens if t.lower().strip(",.!?;:") not in FILLER]
    return re.sub(r"\s+", " ", " ".join(kept)).strip(" ,.;:-!?")


def split_items(text: str) -> list[str]:
    """Split a multi-item request on 'and' / ',' / ';' / newlines when each part has a quantity."""
    parts = re.split(r"\n|;|,|\band\b|\baur\b|\bplus\b|&", text, flags=re.IGNORECASE)
    with_qty = [p for p in parts if _QTY.search(p)]
    return [p.strip() for p in parts if p.strip()] if len(with_qty) > 1 else [text]


_INTENT_BEFORE = re.compile(r"(?:need|want|require|qty|quantity|x|order|of|chahiye)\s*[:=]?\s*$", re.IGNORECASE)


def _pick_quantity(chunk: str) -> re.Match[str] | None:
    """Prefer a number with a unit, then one after an intent word or at the start, else the last."""
    cands = list(_QTY.finditer(chunk))
    if not cands:
        return None
    with_unit = [m for m in cands if m.group(2)]
    if with_unit:
        return with_unit[-1]
    intent = [m for m in cands if _INTENT_BEFORE.search(chunk[: m.start()]) or not chunk[: m.start()].strip()]
    if intent:
        return intent[0]
    return cands[-1]


def parse(text: str, plants: dict[str, Plant], today: date) -> Parsed:
    out = Parsed()
    out.yes = bool(YES.search(text))
    out.no = bool(NO.search(text))
    out.plant = find_plant(text, plants)
    out.need_by, out.need_by_text = find_date(text, today)
    out.urgent_words = sorted({m.group(0).lower() for m in URGENT.finditer(text)})
    out.price = find_price(text)
    body = text
    if out.need_by_text:
        body = body.replace(out.need_by_text, " ")
    body = _PRICE.sub(" ", body)
    for chunk in split_items(body):
        qty: Decimal | None = None
        uom: str | None = None
        item_text = chunk
        best = _pick_quantity(chunk)
        if best is not None:
            try:
                qty = to_decimal(best.group(1).replace(",", ""))
            except MoneyError:
                qty = None
            uom = UNIT_WORD.get((best.group(2) or "").lower()) if best.group(2) else None
            item_text = chunk[: best.start()] + " " + chunk[best.end():]
        else:
            w = re.search(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", chunk, re.IGNORECASE)
            if w:
                qty = Decimal(_NUMBER_WORDS[w.group(1).lower()])
                item_text = chunk[: w.start()] + " " + chunk[w.end():]
        item_text = URGENT.sub(" ", item_text)
        cleaned = _clean_item_text(item_text, plants)
        if cleaned or qty is not None:
            out.items.append((cleaned, qty, uom))
    return out
