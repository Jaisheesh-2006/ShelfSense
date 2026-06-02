# PROMPT
# Task:
#   - Unit-test the brand -> department taxonomy used to roll POS sales up to a category.
# Context:
#   - department_for(brand) maps a brand to a department (makeup/skincare/...) via a curated
#     lookup (departments.BRAND_DEPARTMENTS), case-insensitively; unknown/blank brands -> "other".
# Constraints:
#   - Pure: no IO. Assert representative brands, case-insensitivity, the OTHER fallback, and that
#     the map only emits known department constants.
# Output:
#   - Tests below.
"""Unit tests for the brand -> department taxonomy (ADR-0025)."""

from shelfsense_common.departments import (
    BRAND_DEPARTMENTS,
    MAKEUP,
    OTHER,
    SKINCARE,
    department_for,
)

_KNOWN = {
    "makeup", "skincare", "haircare", "bath_and_body", "personal_care",
    "fragrance", "accessories", "other",
}


def test_known_brands_map_to_expected_departments():
    assert department_for("Lakme") == MAKEUP
    assert department_for("Maybelline") == MAKEUP
    assert department_for("Faces Canada") == MAKEUP
    assert department_for("COSRX") == SKINCARE
    assert department_for("Minimalist") == SKINCARE
    assert department_for("Neutrogena") == SKINCARE


def test_case_and_whitespace_insensitive():
    assert department_for("  lAkMe ") == MAKEUP
    assert department_for("FACES CANADA") == MAKEUP


def test_unknown_and_blank_fall_to_other():
    assert department_for("Totally Unknown Brand") == OTHER
    assert department_for("") == OTHER
    assert department_for(None) == OTHER
    assert department_for("Purplle") == OTHER  # own-label, mixed -> deliberately OTHER


def test_map_only_emits_known_departments():
    assert set(BRAND_DEPARTMENTS.values()) <= _KNOWN
