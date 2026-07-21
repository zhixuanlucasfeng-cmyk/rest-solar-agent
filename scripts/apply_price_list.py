"""
Match the 2026-07-01 Cameroon price list to rows in the `products` table and
write price_xaf — the local Douala retail price the customer-facing chatbot
quotes via app/agent/orchestrator.py's _retrieve_catalog_context(). Never
touches price_cny (the separate China ex-factory cost figure used by the
get_quote tool for a from-scratch landed-cost calculation); this sheet
doesn't contain that number.

Deliberately conservative: a product is only priced when its spec maps to
exactly one price-list row AND that row's spec isn't shared by another
price-list row at a different price (e.g. the price list has two different
12V*100AH GEL batteries in different packaging at 56000 vs 48000 FCFA —
both are skipped since there's no reliable way to tell which DB row is
which). Skipped/unmatched products keep whatever price_xaf they already had
(None by default), so the chatbot still says "price on request" for them
rather than risk quoting the wrong number.

Categories covered: solar panels (by exact LxWxH dimensions), GEL/AGM
batteries (by voltage + Ah), LiFePO4 batteries (by exact kWh, skipping
range specs like "5-17kWh"), and the "Inverter" (not off-grid) section by
exact kW. Charge controllers and the "Others" bucket (freezers/lights/fans/
cables) are skipped: the products table stores those as coarse families
(e.g. one RTNT row covers the whole 2-60A range) that don't map cleanly to
the price list's per-amperage/per-model rows.

20% markup applied (protects distributor margin — see
scripts/ingest_price_list_2026.py's docstring for the earlier incident this
guards against). The lowest-quantity price-list column (single-unit retail)
is used, since a chatbot answering "how much does X cost" is a retail
question, not a bulk-order one.

Run: python scripts/apply_price_list.py [--dry-run]
"""
import argparse
import re
import sqlite3
from pathlib import Path

from openpyxl import load_workbook

SOURCE_XLSX = Path("data/price_list/restar_prices_cameroon_20260701_base.xlsx")
DB_PATH = Path("data/rest_solar.db")
MARKUP = 1.2


def parse_sheet():
    """Yields (top_category, spec, single_unit_marked_up_price) for every
    priced row. top_category comes from the last 'Model' header row seen."""
    wb = load_workbook(SOURCE_XLSX, data_only=True)
    ws = wb.active
    top_category = None
    for row in ws.iter_rows(min_row=1, values_only=True):
        col1, col2 = row[1], row[2]
        if col1 is None:
            continue
        if col2 == "Model":
            top_category = str(col1).strip()
            continue
        if top_category is None:
            continue
        price = row[3]
        if not isinstance(price, (int, float)):
            continue
        spec = str(col2).strip() if col2 is not None else ""
        yield top_category, spec, round(price * MARKUP)


def _dims(s: str | None) -> tuple[int, ...] | None:
    if not s:
        return None
    nums = re.findall(r"\d+", s)
    return tuple(int(n) for n in nums[:3]) if len(nums) >= 3 else None


def _first_number(s: str | None) -> float | None:
    if not s:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", s)
    return float(m.group(1)) if m else None


def _voltage_tokens(s: str | None) -> set[str]:
    if not s:
        return set()
    return {t.strip() for t in re.split(r"[/,]", s) if t.strip()}


def build_dict(pairs: list[tuple], keyfn) -> dict:
    """Groups (key_input, price) pairs by keyfn(key_input); returns
    {key: price} only for keys where every pair agrees on the same price
    (ambiguous keys with conflicting prices are dropped)."""
    grouped: dict = {}
    for key_input, price in pairs:
        key = keyfn(key_input)
        if key is None:
            continue
        grouped.setdefault(key, set()).add(price)
    return {k: v.pop() for k, v in grouped.items() if len(v) == 1}


def match_panels(sheet_rows) -> dict[tuple, int]:
    pairs = [(spec, price) for cat, spec, price in sheet_rows if cat == "Solar panel"]
    return build_dict(pairs, _dims)


def match_gel_agm(sheet_rows, subcat: str) -> dict[tuple, int]:
    """subcat is 'GEL battery' or 'AGM battery'. Key: (voltage_str, ah)."""
    pairs = [(spec, price) for cat, spec, price in sheet_rows if cat == subcat]
    def keyfn(spec):
        m = re.match(r"^\s*([\d.]+V)\s*\*\s*([\d.]+)\s*AH", spec, re.I)
        if not m:
            return None
        return (m.group(1).upper(), float(m.group(2)))
    return build_dict(pairs, keyfn)


def match_lithium_kwh(sheet_rows) -> dict[float, int]:
    pairs = [(spec, price) for cat, spec, price in sheet_rows if cat == "Lithium Battery"]
    def keyfn(spec):
        m = re.search(r"([\d.]+)\s*KW\b", spec, re.I)
        return float(m.group(1)) if m else None
    return build_dict(pairs, keyfn)


def match_inverter_kw(sheet_rows) -> dict[float, int]:
    pairs = [(spec, price) for cat, spec, price in sheet_rows if cat == "Inverter"]
    def keyfn(spec):
        m = re.match(r"^\s*([\d.]+)\s*KW\s*$", spec, re.I)  # excludes "6.2KW Parallelable"
        return float(m.group(1)) if m else None
    return build_dict(pairs, keyfn)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing to the DB")
    args = parser.parse_args()

    sheet_rows = list(parse_sheet())
    panel_prices = match_panels(sheet_rows)
    gel_prices = match_gel_agm(sheet_rows, "GEL battery")
    agm_prices = match_gel_agm(sheet_rows, "AGM battery")
    lithium_prices = match_lithium_kwh(sheet_rows)
    inverter_prices = match_inverter_kw(sheet_rows)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, sku, name, category, subcategory, wattage, power_kw, "
        "capacity_ah, capacity_kwh, voltage, dimensions FROM products"
    )
    products = cur.fetchall()

    updates: list[tuple[int, int, str]] = []  # (product_id, price_xaf, reason)
    for p in products:
        price = None
        reason = ""
        if p["category"] == "solar_panels":
            dims = _dims(p["dimensions"])
            if dims in panel_prices:
                price, reason = panel_prices[dims], f"dimensions {dims}"
        elif p["category"] == "batteries" and p["subcategory"] == "GEL Battery":
            for vtok in _voltage_tokens(p["voltage"]):
                ah = _first_number((p["capacity_ah"] or "").replace("Ah", "").replace("AH", ""))
                key = (vtok.upper(), ah)
                if key in gel_prices:
                    price, reason = gel_prices[key], f"GEL {key}"
                    break
        elif p["category"] == "batteries" and p["subcategory"] == "AGM Battery":
            for vtok in _voltage_tokens(p["voltage"]):
                ah = _first_number((p["capacity_ah"] or "").replace("Ah", "").replace("AH", ""))
                key = (vtok.upper(), ah)
                if key in agm_prices:
                    price, reason = agm_prices[key], f"AGM {key}"
                    break
        elif p["category"] == "batteries" and p["subcategory"] == "LiFePO4 Battery":
            kwh = _first_number((p["capacity_kwh"] or "").replace("kWh", "").replace("KWh", "").replace("KW", ""))
            if kwh in lithium_prices:
                price, reason = lithium_prices[kwh], f"Li {kwh}kWh"
        elif p["category"] == "inverters":
            kw = _first_number((p["power_kw"] or "").replace("kW", "").replace("KW", ""))
            if kw in inverter_prices:
                price, reason = inverter_prices[kw], f"Inverter {kw}kW"

        if price is not None:
            updates.append((p["id"], price, f"{p['sku']} {p['name']!r} <- {reason}"))

    print(f"Parsed {len(sheet_rows)} priced rows from {SOURCE_XLSX.name}.")
    print(f"Matched {len(updates)} of {len(products)} products:\n")
    for pid, price, reason in updates:
        print(f"  #{pid:>3}  {price:>8,} FCFA  {reason}")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        return

    cur.executemany(
        "UPDATE products SET price_xaf = ? WHERE id = ?",
        [(price, pid) for pid, price, _ in updates],
    )
    conn.commit()
    print(f"\nWrote price_xaf for {len(updates)} products to {DB_PATH}.")


if __name__ == "__main__":
    main()
