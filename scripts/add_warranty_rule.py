"""
One-time, idempotent: adds the panel-warranty guardrail Rule to the DB.
Deliberately separate from seed.py, which also tries to (re-)embed FAQ
files into ChromaDB — a path that ImportErrors in a clean environment
since torch/sentence-transformers/chromadb were removed from
requirements.txt (see DONE_SUMMARY.md / commit 8c88b34). This script only
touches the `rules` table.

Run: PYTHONPATH=. .venv/bin/python3 scripts/add_warranty_rule.py
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import Rule

RULE = {
    "name": "panel_warranty",
    "trigger": "warranty/guarantee/broken/defect/claim/garantie/défaut/panne/réclamation/cassé",
    "body": (
        "For solar PANEL (not battery) warranty questions: RESTAR's official "
        "policy (effective 2026-01-01) gives every panel two warranties "
        "starting from the purchase date — a product-defect warranty (10-15 "
        "years depending on panel type) and a performance warranty (20-30 "
        "years, guaranteeing 80.7%-84.95% of rated output). Give the exact "
        "figures from the retrieved catalog match for the specific model "
        "asked about. If the model isn't identified, state the general range "
        "(10-15 year product / 20-30 year performance) and ask for the model "
        "number printed on the panel's label — never invent exact figures "
        "for an unidentified model. For a broken/defective panel, tell the "
        "customer to contact Rest Solar on WhatsApp with the panel's serial "
        "number, photos of the issue, and proof of purchase; warn them not "
        "to remove or damage the serial number label; and note that RESTAR "
        "must be notified within 3 months of discovering the defect. "
        "Mention honestly when damage sounds excluded (e.g. lightning, "
        "flood, storm, improper installation, and unauthorized repairs are "
        "NOT covered). If unsure about any warranty detail, say a human "
        "from Rest Solar will confirm rather than guessing."
    ),
    "priority": 3,
}


async def main():
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(Rule.name))).scalars().all()
        if RULE["name"] in existing:
            print(f"Rule '{RULE['name']}' already exists — skipping.")
            return
        db.add(Rule(**RULE))
        await db.commit()
        print(f"Rule '{RULE['name']}' added.")


if __name__ == "__main__":
    asyncio.run(main())
