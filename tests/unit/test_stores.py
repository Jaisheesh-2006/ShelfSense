# PROMPT
# Task:
#   - Unit-test the pluggable store registry (ADR-0028): auto-discovery, lookup, and that the two
#     shipped stores (ST1008, ST1009) are well-formed and point at their clip folders.
# Context:
#   - Each store is one module in shelfsense_common.stores exposing STORE_CONFIG; the package
#     auto-discovers them. The detector/analytics/API read it, so a new store is drop-in.
# Constraints:
#   - Pure: assert on the loaded StoreConfig objects only. No video, no network, no filesystem.
# Output:
#   - Tests: get_store round-trips ST1008/ST1009 and returns None for unknown; all_stores is sorted
#     and includes both; DEFAULT_STORE_ID resolves; ST1008 has CAM3 entrance + CAM5 floor mask with
#     corrected filenames; ST1009 has two entrances + a product + a billing cam, its own clips_dir,
#     and a pinned synthetic clip_start; every camera carries a usable file + zone.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the pluggable multi-store registry."""

from __future__ import annotations

from shelfsense_common.contracts import CameraRole, StoreConfig
from shelfsense_common.stores import DEFAULT_STORE_ID, all_stores, get_store, store_ids


def test_get_store_roundtrip_and_unknown():
    assert get_store("ST1008").store_id == "ST1008"
    assert get_store("ST1009").store_id == "ST1009"
    assert get_store("NOPE") is None


def test_all_stores_sorted_and_includes_both():
    ids = [s.store_id for s in all_stores()]
    assert ids == sorted(ids)  # deterministic order
    assert {"ST1008", "ST1009"} <= set(ids)
    assert store_ids() == sorted(set(store_ids()))


def test_default_store_resolves():
    assert get_store(DEFAULT_STORE_ID) is not None


def test_every_store_is_valid_and_addressable():
    for store in all_stores():
        assert isinstance(store, StoreConfig)
        assert store.store_id and store.store_name
        assert store.clips_dir  # each store knows where its clips live (relative to CCTV_DIR)
        assert store.cameras, "a store must have at least one camera"
        for cam in store.cameras:
            assert cam.file.strip()  # a real clip filename
            assert cam.primary_zone is not None
            if cam.role is CameraRole.ENTRANCE:
                assert cam.entrance_line is not None  # entrances need a counting line


def test_st1008_matches_corrected_dataset():
    st = get_store("ST1008")
    assert st.clips_dir == "Store_1/Store 1"
    entrance = st.entrance_camera
    assert entrance is not None and entrance.camera_id == "CAM3"
    assert entrance.file == "CAM 3 - entry.mp4"  # corrected dataset filename
    cam5 = st.camera("CAM5")
    assert cam5 is not None and cam5.floor_region is not None  # checkout mirror/display mask
    # All four customer cameras (CAM4 stockroom dropped in the corrected dataset).
    assert {c.camera_id for c in st.customer_cameras} == {"CAM1", "CAM2", "CAM3", "CAM5"}


def test_st1009_store2_shape():
    st = get_store("ST1009")
    assert st.clips_dir == "Store_2/Store 2"
    assert st.clip_start_iso is not None  # pinned to one synthetic day (clips span real days)
    roles = [c.role for c in st.cameras]
    assert roles.count(CameraRole.ENTRANCE) == 2  # two entrances
    assert CameraRole.PRODUCT in roles  # a shelf/zone camera
    assert CameraRole.CHECKOUT in roles  # billing
    assert {c.camera_id for c in st.cameras} == {"ENTRY1", "ENTRY2", "ZONE", "BILLING"}
