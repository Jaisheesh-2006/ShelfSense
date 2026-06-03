"""Staff/customer decision that prefers a VLM verdict, with the heuristic as a fallback (ADR-0027).

`StaffClassifier` (staff.py) decides staff by dark-uniform appearance — accurate for Store_1 (black
uniforms) but brittle across stores (Store_2 staff wear pink). This decider keeps that classifier as
a always-available fallback and, when a VLM is configured, overrides it with a per-person
staff/customer judgement from the model.

Key behaviours:
  * **Decision unit = the global `visitor_id`.** A person resolved across cameras/re-entries gets
    ONE VLM call (cached by visitor_id), matching the "once per tracked person" cost model.
  * **Confidence-gated.** A VLM verdict below `min_confidence`, a person we never captured a crop
    for, or any VLM error falls back to the heuristic — the model can only *improve* the default.
  * **Cached + cheap.** Verdicts persist via `JsonFileCache`, so re-runs make no API calls. A
    within-run failure is remembered so a flaky person isn't retried every event.

`is_staff` keeps the heuristic's `(camera_id, track_id, dwell_ms)` shape plus the resolved
`visitor_id`; passing `visitor_id=None` forces the heuristic path (used for internal billing gates).
"""

from __future__ import annotations

import hashlib

import numpy as np

from app.staff import StaffClassifier
from app.vlm import JsonFileCache, StaffVerdict, VLMClient


class StaffDecider:
    """Heuristic StaffClassifier + optional VLM, preferring the VLM verdict when it is confident."""

    def __init__(
        self,
        heuristic: StaffClassifier,
        vlm: VLMClient | None,
        cache: JsonFileCache | None,
        store_id: str,
        *,
        staff_hint: str | None,
        min_confidence: float,
        classify_staff: bool,
        log,
    ) -> None:
        self._heuristic = heuristic
        self._vlm = vlm if classify_staff else None
        self._cache = cache
        self._store_id = store_id
        self._staff_hint = staff_hint
        self._staff_hint_key = _hint_key(staff_hint)
        self._min_confidence = min_confidence
        self._log = log
        # Largest-area crop seen per (camera, track) — the representative image we send to the VLM.
        self._crops: dict[tuple[str, int], tuple[np.ndarray, float]] = {}
        self._verdicts: dict[str, StaffVerdict] = {}  # by visitor_id
        self._failed: set[str] = set()  # visitor_ids whose VLM call errored this run

    # --- frame-time inputs (delegated / accumulated) -----------------------------------------

    def observe(self, camera_id: str, track_id: int, darkness: float) -> None:
        """Fold one frame's dark-uniform score into the heuristic (the fallback signal)."""
        self._heuristic.observe(camera_id, track_id, darkness)

    def observe_crop(self, camera_id: str, track_id: int, image: np.ndarray, bbox) -> None:
        """Keep the largest-area person crop per track — the best image to show the VLM."""
        if self._vlm is None:
            return  # no VLM → never need crops
        h_img, w_img = image.shape[:2]
        x0, y0 = max(0, int(bbox.x)), max(0, int(bbox.y))
        x1, y1 = min(w_img, int(bbox.x + bbox.w)), min(h_img, int(bbox.y + bbox.h))
        if x1 <= x0 or y1 <= y0:
            return
        area = float((x1 - x0) * (y1 - y0))
        key = (camera_id, track_id)
        prev = self._crops.get(key)
        if prev is None or area > prev[1]:
            self._crops[key] = (image[y0:y1, x0:x1].copy(), area)

    # --- decision ----------------------------------------------------------------------------

    def is_staff(
        self, camera_id: str, track_id: int, visitor_id: str | None, dwell_ms: int = 0
    ) -> bool:
        """True if this person is staff. Uses the VLM verdict when confident, else the heuristic."""
        verdict = self._vlm_verdict(camera_id, track_id, visitor_id)
        if verdict is not None and verdict.confidence >= self._min_confidence:
            return verdict.is_staff
        return self._heuristic.is_staff(camera_id, track_id, dwell_ms)

    def _vlm_verdict(
        self, camera_id: str, track_id: int, visitor_id: str | None
    ) -> StaffVerdict | None:
        """Return a cached/fresh VLM verdict for this visitor, or None to use the heuristic."""
        if self._vlm is None or visitor_id is None or visitor_id in self._failed:
            return None
        if visitor_id in self._verdicts:
            return self._verdicts[visitor_id]

        cache_key = f"staff:{self._store_id}:{self._staff_hint_key}:{visitor_id}"
        cached = self._cache.get(cache_key) if self._cache is not None else None
        if cached is not None:
            verdict = StaffVerdict(
                is_staff=bool(cached.get("is_staff")),
                confidence=float(cached.get("confidence", 0.0)),
                reason=str(cached.get("reason", "")),
                source="cache",
            )
            self._verdicts[visitor_id] = verdict
            return verdict

        crop = self._best_crop_for(visitor_id, camera_id, track_id)
        if crop is None:
            return None  # nothing to send → heuristic
        try:
            verdict = self._vlm.classify_staff(crop, staff_hint=self._staff_hint)
        except Exception as err:  # noqa: BLE001 — degrade to heuristic, don't crash the pass
            self._failed.add(visitor_id)
            self._log.warning("vlm_staff_failed", visitor=visitor_id, error=str(err))
            return None
        self._verdicts[visitor_id] = verdict
        if self._cache is not None:
            self._cache.set(
                cache_key,
                {
                    "is_staff": verdict.is_staff,
                    "confidence": verdict.confidence,
                    "reason": verdict.reason,
                },
            )
        self._log.info(
            "vlm_staff",
            visitor=visitor_id,
            is_staff=verdict.is_staff,
            confidence=round(verdict.confidence, 3),
        )
        return verdict

    def _best_crop_for(self, visitor_id: str, camera_id: str, track_id: int) -> np.ndarray | None:
        """The representative crop to send the VLM: the largest crop seen for this track."""
        crop = self._crops.get((camera_id, track_id))
        return crop[0] if crop is not None else None


def _hint_key(hint: str | None) -> str:
    if not hint:
        return "none"
    digest = hashlib.md5(hint.strip().lower().encode("utf-8")).hexdigest()  # noqa: S324
    return f"hint-{digest[:8]}"
