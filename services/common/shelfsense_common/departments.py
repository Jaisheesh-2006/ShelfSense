"""Brand → department (category) taxonomy for POS sales.

The corrected POS CSV has `brand_name` but **no department column** (the old `dep_name` is gone —
GROUND_TRUTH.md §2). This module restores a department rollup by mapping each brand to a category,
so the API can report both `top_brand` and `top_department` (ADR-0025).

**Provenance (why these categories, not invented):**
- The store's *own* historical taxonomy, from the now-removed detailed CSV's `dep_name`:
  makeup · skin · hair · bath-and-body · personal-care · fragrance.
- The store layout (GROUND_TRUTH.md §4): a skincare gondola (top wall), a makeup gondola (bottom
  wall), a fragrance/nail unit + makeup tables in the centre, accessories by the checkout.
- Public domain knowledge of these beauty brands for the specific names in the POS.

This is **reference data** (a lookup table), like the zone config — the *output* still varies with
the real sales. Brands we can't confidently classify map to `OTHER` (never guessed). A couple are
genuine judgment calls and are flagged inline; override here if the business disagrees.
"""

from __future__ import annotations

# Canonical department names (lowercase, stable keys for API/grid rendering).
MAKEUP = "makeup"
SKINCARE = "skincare"
HAIRCARE = "haircare"
BATH_AND_BODY = "bath_and_body"
PERSONAL_CARE = "personal_care"
FRAGRANCE = "fragrance"
ACCESSORIES = "accessories"
OTHER = "other"  # unmapped / mixed own-label — surfaced honestly, never silently dropped

# Brand -> department. Keys are matched case-insensitively (see `department_for`).
BRAND_DEPARTMENTS: dict[str, str] = {
    # Makeup (colour cosmetics) — corroborated by the layout's bottom gondola.
    "faces canada": MAKEUP,
    "lakme": MAKEUP,
    "maybelline": MAKEUP,
    "renee": MAKEUP,
    "ny bae": MAKEUP,
    "swiss beauty": MAKEUP,
    "cuffs n lashes": MAKEUP,  # false lashes / eye
    "lo'real": MAKEUP,
    "mars": MAKEUP,
    # Skincare — corroborated by the layout's top gondola.
    "foxtale": SKINCARE,
    "dermdoc": SKINCARE,
    "cosrx": SKINCARE,
    "beauty of joseon": SKINCARE,
    "round lab": SKINCARE,
    "juicy chemistry": SKINCARE,
    "alps goodness": SKINCARE,  # natural skincare (layout shelves it near makeup; brand=skincare)
    "neutrogena": SKINCARE,
    "lotus herbals": SKINCARE,
    "minimalist": SKINCARE,
    "aqualogica": SKINCARE,
    "pilgrim": SKINCARE,
    "garnier": SKINCARE,  # ⚠ judgment call: Garnier spans skin + hair; defaulted to skincare
    # Haircare
    "bare anatomy": HAIRCARE,
    # Bath & body
    "good vibes": BATH_AND_BODY,
    # Personal care / hygiene
    "carmesi": PERSONAL_CARE,
    # Beauty tools / accessories
    "gubb": ACCESSORIES,
    # Own-label spanning every category — not a single department.
    "purplle": OTHER,
}


def department_for(brand: str | None) -> str:
    """Map a brand name to its department; `OTHER` for blank/unknown brands. Case-insensitive."""
    if not brand:
        return OTHER
    return BRAND_DEPARTMENTS.get(brand.strip().lower(), OTHER)
