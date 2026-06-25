"""
Run once to populate the database and knowledge base:
    python seed.py
"""
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from app.db.session import engine, AsyncSessionLocal
from app.db.models import Base, Rule
from app.rag.embedder import embed_batch
from app.rag.retriever import upsert

RULES = [
    {
        "name": "low_score_fallback",
        "trigger": "",
        "body": (
            "If no relevant knowledge-base chunks were retrieved "
            "(cosine distance > 0.5), do not attempt to answer from general "
            "knowledge. Say you do not have specific information and offer to "
            "raise a support ticket."
        ),
        "priority": 0,
    },
    {
        "name": "no_invented_prices",
        "trigger": "price/tariff/duty/vat/prix/taxe/cost/coût",
        "body": (
            "You MUST only quote prices and duties from the retrieved "
            "knowledge-base chunks. If no price is found in context, say you "
            "do not have that information and offer a support ticket. "
            "Never invent a number."
        ),
        "priority": 1,
    },
    {
        "name": "cameroon_vat",
        "trigger": "vat/tax/taxe/tva/duty/droit",
        "body": (
            "Cameroon VAT is 19.25%. Never state a different rate unless a "
            "knowledge-base chunk explicitly overrides it."
        ),
        "priority": 2,
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created")

    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(Rule.name))).scalars().all()
        for r in RULES:
            if r["name"] not in existing:
                db.add(Rule(**r))
        await db.commit()
    print(f"✓ {len(RULES)} rules seeded into SQLite")

    seeds_dir = Path("data/seeds")
    for faq_file in sorted(seeds_dir.glob("faqs_*.txt")):
        lang = faq_file.stem.split("_")[1]
        raw = faq_file.read_text(encoding="utf-8").strip()
        blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
        embeddings = embed_batch(blocks)
        for i, (text, vec) in enumerate(zip(blocks, embeddings)):
            doc_id = f"{faq_file.stem}_{i}"
            upsert(doc_id, text, vec, {
                "source_file": faq_file.name,
                "language": lang,
                "chunk_index": i,
            })
        print(f"✓ {len(blocks)} FAQ chunks seeded from {faq_file.name}")


if __name__ == "__main__":
    asyncio.run(seed())
