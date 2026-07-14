"""
Build bilingual (EN/FR) knowledge-base chunks for the 2026 product catalog
and embed/upsert them into the existing ChromaDB collection used by the
chat agent's RAG retriever. Idempotent (upsert by deterministic doc_id).

Run: python scripts/ingest_catalog_rag.py
"""
import json
from pathlib import Path

from app.rag.embedder import embed_batch
from app.rag.retriever import upsert

CATALOG = Path("data/catalog_2026/products.json")

CATEGORY_LABEL = {
    "solar_panels": ("Solar Panels", "Panneaux Solaires"),
    "inverters": ("Inverters", "Onduleurs"),
    "batteries": ("Batteries", "Batteries"),
    "ess": ("Energy Storage System (ESS)", "Système de Stockage d'Énergie (ESS)"),
    "charge_controllers": ("Charge Controllers", "Régulateurs de Charge"),
    "other": ("Accessories", "Accessoires"),
}

SUBCAT_LABEL_FR = {
    "AGM Battery": "Batterie AGM",
    "GEL Battery": "Batterie GEL",
    "LiFePO4 Battery": "Batterie LiFePO4",
    "MPPT Controller": "Régulateur MPPT",
    "PWM Controller": "Régulateur PWM",
    "Off-Grid Inverter": "Onduleur Hors Réseau",
    "Hybrid Inverter": "Onduleur Hybride",
    "Grid-Tied Inverter": "Onduleur Raccordé au Réseau",
    "Other Inverter": "Onduleur (Autre)",
}

FEATURE_FR = {
    "TOPCon": "TOPCon (haute efficacité)",
    "Full Black": "Tout Noir",
    "Black Frame": "Cadre Noir",
    "Bifacial": "Bifacial",
    "Dual Glass": "Double Verre",
    "LiFePO4": "LiFePO4",
    "Built-in BMS": "BMS intégré",
    "IP65": "Étanchéité IP65",
    "IP67": "Étanchéité IP67",
    "WiFi Monitoring": "Surveillance WiFi",
    "Bluetooth": "Bluetooth",
}

USE_CASE_LABEL = {
    "home_backup": ("home backup power", "alimentation de secours résidentielle"),
    "shop_fridge": ("shop/business refrigeration", "réfrigération pour commerce/boutique"),
    "borehole_pump": ("borehole/water pumping", "pompage d'eau/forage"),
    "street_lighting": ("street and area lighting", "éclairage public"),
    "business_ess": ("business/commercial energy storage", "stockage d'énergie commercial/entreprise"),
    "high_efficiency": ("high-efficiency premium installations", "installations premium haute efficacité"),
    "business_high_watt": ("large commercial solar arrays", "grandes installations solaires commerciales"),
    "lifepo4": ("long-life lithium storage", "stockage lithium longue durée"),
}


def spec_line_en(r: dict) -> str:
    bits = []
    if r["wattage"]: bits.append(f"power {r['wattage']}")
    if r["power_kw"]: bits.append(f"power {r['power_kw']}")
    if r["capacity_ah"]: bits.append(f"capacity {r['capacity_ah']}")
    if r["capacity_kwh"]: bits.append(f"capacity {r['capacity_kwh']}")
    if r["voltage"]: bits.append(f"voltage {r['voltage']}")
    if r["dimensions"]: bits.append(f"dimensions {r['dimensions']}")
    return ", ".join(bits)


def spec_line_fr(r: dict) -> str:
    bits = []
    if r["wattage"]: bits.append(f"puissance {r['wattage']}")
    if r["power_kw"]: bits.append(f"puissance {r['power_kw']}")
    if r["capacity_ah"]: bits.append(f"capacité {r['capacity_ah']}")
    if r["capacity_kwh"]: bits.append(f"capacité {r['capacity_kwh']}")
    if r["voltage"]: bits.append(f"tension {r['voltage']}")
    if r["dimensions"]: bits.append(f"dimensions {r['dimensions']}")
    return ", ".join(bits)


def product_chunk_en(r: dict) -> str:
    cat_en, _ = CATEGORY_LABEL[r["category"]]
    subcat = f" ({r['subcategory']})" if r["subcategory"] else ""
    specs = spec_line_en(r)
    feats = ", ".join(r["features"]) if r["features"] else None
    lines = [
        f"Q: What are the specifications of the Restar Solar {r['model']}?",
        f"A: {r['model']} is a {cat_en}{subcat} from Restar Solar's 2026 catalog (SKU {r['sku']}).",
    ]
    if specs:
        lines.append(f"Key specs: {specs}.")
    if feats:
        lines.append(f"Features: {feats}.")
    lines.append(
        "Price is quoted on request based on order volume and shipping — contact Rest Solar for a quote. "
        f"A full datasheet PDF is available for download (product SKU {r['sku']})."
    )
    return " ".join(lines)


def product_chunk_fr(r: dict) -> str:
    _, cat_fr = CATEGORY_LABEL[r["category"]]
    subcat = SUBCAT_LABEL_FR.get(r["subcategory"], r["subcategory"]) if r["subcategory"] else None
    subcat_str = f" ({subcat})" if subcat else ""
    specs = spec_line_fr(r)
    feats = ", ".join(FEATURE_FR.get(f, f) for f in r["features"]) if r["features"] else None
    lines = [
        f"Q: Quelles sont les spécifications du {r['model']} de Restar Solar ?",
        f"R: {r['model']} fait partie de la catégorie {cat_fr}{subcat_str} du catalogue Restar Solar 2026 (référence {r['sku']}).",
    ]
    if specs:
        lines.append(f"Caractéristiques principales : {specs}.")
    if feats:
        lines.append(f"Fonctionnalités : {feats}.")
    lines.append(
        "Le prix est communiqué sur demande selon le volume de commande et le transport — contactez Rest Solar pour un devis. "
        f"Une fiche technique PDF complète est disponible au téléchargement (référence produit {r['sku']})."
    )
    return " ".join(lines)


def category_overview_chunks(records: list[dict]) -> list[tuple[str, str, dict]]:
    """One EN + one FR chunk per category summarizing the range."""
    chunks = []
    by_cat: dict[str, list[dict]] = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r)

    for cat, items in by_cat.items():
        cat_en, cat_fr = CATEGORY_LABEL[cat]
        models = ", ".join(sorted({i["model"] for i in items}))[:800]
        chunks.append((
            f"cat_overview_{cat}_en",
            f"Q: What {cat_en.lower()} does Rest Solar carry? "
            f"A: Rest Solar's 2026 catalog includes {len(items)} {cat_en.lower()} products from Restar Solar, "
            f"covering models such as: {models}. Ask about a specific model for full specs, or ask for a "
            f"recommendation by use case (home backup, shop refrigeration, borehole pumping, street lighting, "
            f"or business energy storage).",
            {"language": "en", "category": cat, "source_file": "catalog_2026", "kind": "category_overview"},
        ))
        chunks.append((
            f"cat_overview_{cat}_fr",
            f"Q: Quels {cat_fr.lower()} propose Rest Solar ? "
            f"R: Le catalogue Restar Solar 2026 comprend {len(items)} produits de la catégorie {cat_fr.lower()}, "
            f"incluant des modèles tels que : {models}. Demandez un modèle précis pour les spécifications complètes, "
            f"ou demandez une recommandation selon votre usage (secours résidentiel, réfrigération commerciale, "
            f"pompage de forage, éclairage public, ou stockage d'énergie pour entreprise).",
            {"language": "fr", "category": cat, "source_file": "catalog_2026", "kind": "category_overview"},
        ))
    return chunks


def use_case_chunks(records: list[dict]) -> list[tuple[str, str, dict]]:
    chunks = []
    tag_to_items: dict[str, list[dict]] = {}
    for r in records:
        for tag in (r.get("use_cases_computed") or []):
            tag_to_items.setdefault(tag, []).append(r)

    use_case_intro_en = {
        "home_backup": "For home backup power in Cameroon (protecting against ECAM/ENEO outages), Rest Solar recommends pairing an off-grid or hybrid inverter (RT-ES, RT-K, or RT-HY series) with AGM, GEL, or LiFePO4 batteries and enough solar panel wattage for your daily load.",
        "shop_fridge": "For a shop or business refrigerator/freezer running on solar, Rest Solar recommends our dedicated solar freezer/refrigerator units combined with sufficient panel wattage and a battery bank sized for overnight operation.",
        "borehole_pump": "For borehole or water pumping, Rest Solar recommends our DC water pumps paired with a dedicated Solar Pump Inverter, sized to the well depth and daily water volume needed.",
        "street_lighting": "For street or area lighting, Rest Solar offers all-in-one Solar Street Lights and Solar Flood Lights with built-in battery and panel, requiring no separate wiring.",
        "business_ess": "For business or commercial energy storage, Rest Solar recommends the SmartCube ESS series (residential 3.6-10kW up to commercial installations up to 233kWh) paired with RT-HY or RT-T hybrid inverters.",
    }
    use_case_intro_fr = {
        "home_backup": "Pour une alimentation de secours résidentielle au Cameroun (contre les coupures ECAM/ENEO), Rest Solar recommande d'associer un onduleur hors réseau ou hybride (série RT-ES, RT-K, ou RT-HY) à des batteries AGM, GEL ou LiFePO4, avec une puissance de panneaux solaires adaptée à votre consommation journalière.",
        "shop_fridge": "Pour un réfrigérateur/congélateur de boutique ou d'entreprise fonctionnant à l'énergie solaire, Rest Solar recommande nos congélateurs/réfrigérateurs solaires dédiés, combinés à une puissance de panneaux suffisante et un parc de batteries dimensionné pour un fonctionnement nocturne.",
        "borehole_pump": "Pour le pompage d'eau ou de forage, Rest Solar recommande nos pompes à eau DC associées à un onduleur de pompe solaire dédié, dimensionné selon la profondeur du puits et le volume d'eau journalier requis.",
        "street_lighting": "Pour l'éclairage public ou de zone, Rest Solar propose des lampadaires solaires et projecteurs solaires tout-en-un avec batterie et panneau intégrés, sans câblage séparé nécessaire.",
        "business_ess": "Pour le stockage d'énergie commercial ou d'entreprise, Rest Solar recommande la série SmartCube ESS (de 3,6-10kW résidentiel jusqu'à 233kWh pour installations commerciales), associée à des onduleurs hybrides RT-HY ou RT-T.",
    }

    for tag, items in tag_to_items.items():
        if tag not in use_case_intro_en:
            continue
        models = ", ".join(sorted({i["model"] for i in items}))[:500]
        chunks.append((
            f"usecase_{tag}_en",
            f"Q: What do you recommend for {USE_CASE_LABEL[tag][0]}? "
            f"A: {use_case_intro_en[tag]} Relevant models in stock: {models}.",
            {"language": "en", "category": "use_case", "source_file": "catalog_2026", "kind": "use_case", "tag": tag},
        ))
        chunks.append((
            f"usecase_{tag}_fr",
            f"Q: Que recommandez-vous pour {USE_CASE_LABEL[tag][1]} ? "
            f"R: {use_case_intro_fr[tag]} Modèles disponibles concernés : {models}.",
            {"language": "fr", "category": "use_case", "source_file": "catalog_2026", "kind": "use_case", "tag": tag},
        ))
    return chunks


def main():
    records = json.loads(CATALOG.read_text(encoding="utf-8"))

    # reuse the same use-case tagging logic as the DB ingestion script
    import importlib.util
    spec = importlib.util.spec_from_file_location("ingest_catalog_2026", "scripts/ingest_catalog_2026.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for r in records:
        r["use_cases_computed"] = mod.use_case_tags(r)

    doc_ids, texts, metadatas = [], [], []

    for r in records:
        doc_ids.append(f"product_{r['sku']}_en")
        texts.append(product_chunk_en(r))
        metadatas.append({
            "language": "en", "category": r["category"], "sku": r["sku"],
            "source_file": "catalog_2026", "kind": "product",
        })
        doc_ids.append(f"product_{r['sku']}_fr")
        texts.append(product_chunk_fr(r))
        metadatas.append({
            "language": "fr", "category": r["category"], "sku": r["sku"],
            "source_file": "catalog_2026", "kind": "product",
        })

    for doc_id, text, meta in category_overview_chunks(records):
        doc_ids.append(doc_id)
        texts.append(text)
        metadatas.append(meta)

    for doc_id, text, meta in use_case_chunks(records):
        doc_ids.append(doc_id)
        texts.append(text)
        metadatas.append(meta)

    print(f"Embedding {len(texts)} chunks (this runs a local sentence-transformers model, may take a minute)...")
    embeddings = embed_batch(texts)
    for doc_id, text, vec, meta in zip(doc_ids, texts, embeddings, metadatas):
        upsert(doc_id, text, vec, meta)

    print(f"Upserted {len(texts)} knowledge-base chunks into ChromaDB "
          f"({len(records)} products x2 languages + category overviews + use-case chunks)")


if __name__ == "__main__":
    main()
