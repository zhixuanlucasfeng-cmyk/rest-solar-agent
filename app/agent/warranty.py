"""
Classifies a RESTAR solar panel model number into its official warranty
family, per "RESTAR Limited Manufacturer's Warranty for Crystalline Solar
Photovoltaic Modules" (effective 2026-01-01).

RT7V/RT8H/RT8L/RT8S/RT8X are real catalog model prefixes not listed in
RESTAR's official family table. Per user decision (2026-07-15), they are
treated as the same "half_cell" family as the documented RT7/RT8 models
(same generation, same 15yr/30yr/83% terms), flagged `assumed: True` so
they can be corrected later without re-deriving the rest of the catalog.
This flag is for internal/data purposes only — never surface it to
customers in a chat reply.
"""
import re

WARRANTY_FAMILIES = {
    "cutting_cell": {"product_years": 10, "performance_years": 20, "output_pct_en": "≥80.7%", "output_pct_fr": "≥80,7 %"},
    "full_cell":    {"product_years": 12, "performance_years": 25, "output_pct_en": "≥80.7%", "output_pct_fr": "≥80,7 %"},
    "half_cell":    {"product_years": 15, "performance_years": 30, "output_pct_en": "≥83%",   "output_pct_fr": "≥83 %"},
    "bifacial":     {"product_years": 15, "performance_years": 30, "output_pct_en": "≥84.95%", "output_pct_fr": "≥84,95 %"},
}

_FULL_CELL_PREFIXES = ("RT6S", "RT6C", "RT6D", "RT6F", "RT6E", "RT6G")
_HALF_CELL_PREFIXES = ("RT7K", "RT7I", "RT7V", "RT8V", "RT8K", "RT8I", "RT8H", "RT8L", "RT8S", "RT8X", "RT9Y", "RT9N", "RT9T", "RT9K", "RT9H")
_HALF_CELL_ASSUMED = ("RT7V", "RT8H", "RT8L", "RT8S", "RT8X")

_MODEL_RE = re.compile(r"RT[A-Z0-9-]+")


def classify_panel_warranty(model: str | None) -> dict | None:
    """Return the warranty dict for a panel model, or None if unrecognized."""
    if not model:
        return None
    upper = model.upper()
    match = _MODEL_RE.search(upper)
    if not match:
        return None
    m = match.group(0)

    if m.startswith("RTM"):
        family = "cutting_cell"
    elif m.startswith(_FULL_CELL_PREFIXES):
        family = "full_cell"
    elif m.startswith(_HALF_CELL_PREFIXES):
        family = "bifacial" if ("-BD" in m or "-DG" in m) else "half_cell"
    else:
        return None

    result = dict(WARRANTY_FAMILIES[family])
    result["assumed"] = any(m.startswith(p) for p in _HALF_CELL_ASSUMED)
    return result
