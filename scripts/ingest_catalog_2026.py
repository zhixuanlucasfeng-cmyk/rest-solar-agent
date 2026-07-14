"""
Load the 2026 product catalog (data/catalog_2026/products.json) into the
`products` table. Idempotent: upserts by sku.

Run: python scripts/ingest_catalog_2026.py
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import Product

CATALOG = Path("data/catalog_2026/products.json")

# Cameroon market featured use-case flags, keyed by sku prefix pattern / model heuristics.
FEATURED_USE_CASES = {
    # solar water pumps
    "dc water pump": ("borehole_pump", "Solar Pump Inverter", "Solar Pump Inverter"),
}


def build_name(rec: dict) -> str:
    bits = [rec["category_en"].rstrip("s") if False else rec["category_en"]]
    name = f"{rec['model']}"
    if rec.get("wattage"):
        name += f" {rec['wattage']}"
    elif rec.get("power_kw"):
        name += f" {rec['power_kw']}"
    elif rec.get("capacity_kwh"):
        name += f" {rec['capacity_kwh']}"
    elif rec.get("capacity_ah") and rec.get("voltage"):
        name += f" {rec['voltage']} {rec['capacity_ah']}"
    return name.strip()


def use_case_tags(rec: dict) -> list[str]:
    """Best-effort use-case tagging for Cameroon market recommendation logic."""
    blob = (rec["title_raw"] + " " + rec["category"] + " " + (rec["subcategory"] or "")).lower()
    tags = []
    if rec["category"] == "solar_panels":
        tags.append("home_backup")
        try:
            w = int(rec["wattage"].split("-")[-1].replace("W", "")) if rec.get("wattage") else 0
        except ValueError:
            w = 0
        if w >= 450:
            tags.append("business_high_watt")
        if "topcon" in blob or "TOPCon" in rec["features"]:
            tags.append("high_efficiency")
    if rec["category"] == "inverters":
        if rec.get("subcategory") == "Off-Grid Inverter":
            tags.append("home_backup")
        if rec.get("subcategory") == "Hybrid Inverter":
            tags.append("home_backup")
            tags.append("business_ess")
        if "pump" in blob:
            tags.append("borehole_pump")
        if "micro" in blob:
            tags.append("home_backup")
    if rec["category"] == "batteries":
        tags.append("home_backup")
        if rec.get("subcategory") == "LiFePO4 Battery":
            tags.append("lifepo4")
            tags.append("business_ess")
    if rec["category"] == "ess":
        tags.append("business_ess")
        tags.append("home_backup")
    if rec["category"] == "charge_controllers":
        tags.append("home_backup")
    if rec["category"] == "other":
        if "water pump" in blob:
            tags.append("borehole_pump")
        if "freezer" in blob or "refrigerator" in blob or "fridge" in blob:
            tags.append("shop_fridge")
        if "street light" in blob or "flood light" in blob:
            tags.append("street_lighting")
        if "fan" in blob:
            tags.append("home_backup")
    return sorted(set(tags))


async def ingest():
    records = json.loads(CATALOG.read_text(encoding="utf-8"))
    created, updated = 0, 0
    async with AsyncSessionLocal() as db:
        for rec in records:
            result = await db.execute(select(Product).where(Product.sku == rec["sku"]))
            product = result.scalar_one_or_none()
            tags = use_case_tags(rec)
            is_featured = any(t in tags for t in (
                "borehole_pump", "shop_fridge", "street_lighting", "business_ess",
            )) or (rec["category"] == "batteries" and rec.get("subcategory") == "LiFePO4 Battery") or (
                rec["category"] == "solar_panels" and "high_efficiency" in tags
            )

            fields = dict(
                name=build_name(rec),
                sku=rec["sku"],
                price_cny=None,
                price_xaf=None,
                weight_kg=None,
                stock=0,
                category=rec["category"],
                subcategory=rec["subcategory"],
                model=rec["model"],
                wattage=rec["wattage"],
                power_kw=rec["power_kw"],
                capacity_ah=rec["capacity_ah"],
                capacity_kwh=rec["capacity_kwh"],
                voltage=rec["voltage"],
                dimensions=rec["dimensions"],
                features=", ".join(rec["features"]),
                datasheet_path=rec["datasheet_path"],
                image_path=rec["image_path"],
                featured=is_featured,
                use_cases=", ".join(tags),
            )

            if product is None:
                db.add(Product(**fields))
                created += 1
            else:
                for k, v in fields.items():
                    setattr(product, k, v)
                updated += 1
        await db.commit()
    print(f"Ingested catalog: {created} created, {updated} updated, {len(records)} total")


if __name__ == "__main__":
    asyncio.run(ingest())
