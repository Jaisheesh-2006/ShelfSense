"""Staff/customer decision that prefers a VLM verdict, with the heuristic as a fallback (ADR-0027).

`StaffClassifier` (staff.py) decides staff by a per-store uniform-COLOUR match (black for Store_1,
pink for Store_2; ADR-0032) — cheap but brittle (a customer in the staff colour is misflagged).
This decider keeps that classifier as an always-available fallback and, when a VLM is configured,
overrides it with a per-person staff/customer judgement from the model.

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
from app.vlm import DemographicsVerdict, JsonFileCache, StaffVerdict, VLMClient


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
        override_margin: float,
        log,
        crop_dump_dir: str = "",
        classify_demographics: bool = False,
    ) -> None:
        self._heuristic = heuristic
        self._vlm = vlm if classify_staff else None
        # Demographics use the SAME model but an independent toggle, so a harvest can predict
        # gender/age with staff-VLM off (ADR-0040) without disturbing the staff classification.
        self._demographics_vlm = vlm if classify_demographics else None
        self._cache = cache
        self._store_id = store_id
        self._staff_hint = staff_hint
        self._staff_hint_key = _hint_key(staff_hint)
        self._min_confidence = min_confidence
        self._override_margin = override_margin
        self._log = log
        self._crop_dump_dir = crop_dump_dir  # if set, dump one labelled crop per visitor (proof)
        self._decision_logged: set[str] = set()  # visitor_ids whose decision we've logged once
        # Largest-area crop seen per (camera, track) — the representative image we send to the VLM.
        self._crops: dict[tuple[str, int], tuple[np.ndarray, float]] = {}
        # Foot-point of that representative crop (full-frame px) — the demographics hotspot (0040).
        self._crop_foot: dict[tuple[str, int], tuple[float, float]] = {}
        self._verdicts: dict[str, StaffVerdict] = {}  # by visitor_id
        self._failed: set[str] = set()  # visitor_ids whose VLM call errored this run
        self._track_visitor: dict[tuple[str, int], str] = {}  # (cam,track) -> visitor (for dumps)
        self._decisions: dict[str, dict] = {}  # visitor_id -> {score, is_staff, source} (for dumps)

    # --- frame-time inputs (delegated / accumulated) -----------------------------------------

    def observe(self, camera_id: str, track_id: int, color_score: float) -> None:
        """Fold one frame's uniform-colour score into the heuristic (the fallback signal)."""
        self._heuristic.observe(camera_id, track_id, color_score)

    def observe_crop(self, camera_id: str, track_id: int, image: np.ndarray, bbox) -> None:
        """Keep the largest-area person crop per track — best image to show the VLM (or to dump)."""
        if self._vlm is None and self._demographics_vlm is None and not self._crop_dump_dir:
            return  # no VLM (staff or demographics) and no dump → never need crops
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
            # Foot-point (bottom-centre, full-frame px): the representative hotspot for this person.
            self._crop_foot[key] = (float(bbox.x + bbox.w / 2.0), float(bbox.y + bbox.h))

    # --- decision ----------------------------------------------------------------------------

    def is_staff(
        self, camera_id: str, track_id: int, visitor_id: str | None, dwell_ms: int = 0
    ) -> bool:
        """True if staff — VLM baseline + heuristic high-confidence override (ADR-0032).

        The VLM is the cross-store baseline (it generalises to any store). Where a store has a
        **distinctive uniform**, a decisive per-store colour match — score at least
        `override_margin` above the threshold — **overrides** the VLM to staff (a confident but
        wrong VLM cannot demote known uniformed staff, e.g. Store_1's black). This is asymmetric:
        a LOW colour score is NOT proof of "customer" (the uniform may be occluded / the person in
        a back room), so it does not override — it defers to the VLM, with the heuristic threshold
        as the fallback only when the VLM can't decide (off / no crop / low confidence / error).
        """
        if visitor_id is not None:
            self._track_visitor[(camera_id, track_id)] = visitor_id
        score = self._heuristic.mean_color_score(camera_id, track_id)
        threshold = self._heuristic.threshold

        if score >= threshold + self._override_margin:
            decision, source = True, "heuristic_override"
        else:
            verdict = self._vlm_verdict(camera_id, track_id, visitor_id)
            if verdict is not None and verdict.confidence >= self._min_confidence:
                decision, source = verdict.is_staff, f"vlm_{verdict.source}"
            else:
                decision = self._heuristic.is_staff(camera_id, track_id, dwell_ms)
                source = "heuristic_fallback"

        self._log_decision(visitor_id, score, threshold, decision, source)
        return decision

    def _log_decision(
        self, visitor_id: str | None, score: float, threshold: float, decision: bool, source: str
    ) -> None:
        """Emit one explainable staff decision per visitor (observability / calibration aid)."""
        if visitor_id is None or visitor_id in self._decision_logged:
            return
        self._decision_logged.add(visitor_id)
        self._decisions[visitor_id] = {
            "score": round(score, 3),
            "is_staff": decision,
            "source": source,
        }
        self._log.info(
            "staff_decision",
            visitor=visitor_id,
            colour_score=round(score, 3),
            threshold=threshold,
            is_staff=decision,
            source=source,
        )

    def dump_crops(self) -> None:
        """Write one labelled crop per visitor to `crop_dump_dir` (proof / adjudication aid).

        No-op unless `crop_dump_dir` is set. Picks the largest crop seen across the visitor's tracks
        and names the file by visitor, classification and colour score so the people behind the
        numbers can be eyeballed (e.g. to confirm a borderline staff/customer call).
        """
        if not self._crop_dump_dir:
            return
        import os

        import cv2

        os.makedirs(self._crop_dump_dir, exist_ok=True)
        best: dict[str, tuple[np.ndarray, float]] = {}  # visitor -> (crop, area)
        for (cam, track), (crop, area) in self._crops.items():
            vid = self._track_visitor.get((cam, track))
            if vid is None:
                continue
            if vid not in best or area > best[vid][1]:
                best[vid] = (crop, area)
        for vid, (crop, _area) in best.items():
            d = self._decisions.get(vid, {})
            label = "STAFF" if d.get("is_staff") else "cust"
            score = d.get("score", 0.0)
            source = d.get("source", "na")
            name = f"{self._store_id}_{vid}_{label}_c{score:.2f}_{source}.jpg"
            cv2.imwrite(os.path.join(self._crop_dump_dir, name), crop)
        self._log.info("staff_crops_dumped", store=self._store_id, count=len(best))

    def demographics_by_visitor(self) -> dict[str, dict]:
        """Per-visitor coarse demographics (VLM) + a representative foot-point hotspot (ADR-0040).

        Mirrors `dump_crops`: pick the largest crop per visitor, ask the VLM for gender + age band
        (cached), and return ``{visitor_id: {gender_pred, age_bucket, confidences, hotspot_x/y}}``.
        Empty without a demographics VLM. This NEVER affects counts — it only feeds event metadata
        via the offline merge, so the validated unique/funnel numbers are untouched.
        """
        if self._demographics_vlm is None:
            return {}
        best: dict[str, tuple[np.ndarray, float, tuple[str, int]]] = {}
        for (cam, track), (crop, area) in self._crops.items():
            vid = self._track_visitor.get((cam, track))
            if vid is None:
                continue
            if vid not in best or area > best[vid][1]:
                best[vid] = (crop, area, (cam, track))

        out: dict[str, dict] = {}
        for vid, (crop, _area, key) in best.items():
            verdict = self._demographics_verdict(vid, crop)
            if verdict is None:
                continue
            fx, fy = self._crop_foot.get(key, (None, None))
            out[vid] = {
                "gender_pred": verdict.gender,
                "gender_confidence": round(verdict.gender_confidence, 3),
                "age_bucket": verdict.age_bucket,
                "age_confidence": round(verdict.age_confidence, 3),
                "hotspot_x": round(fx, 1) if fx is not None else None,
                "hotspot_y": round(fy, 1) if fy is not None else None,
                "reason": verdict.reason,
            }
        return out

    def _demographics_verdict(
        self, visitor_id: str, crop: np.ndarray
    ) -> DemographicsVerdict | None:
        """Cached/fresh demographics verdict for a visitor; None on error (kept out of events)."""
        cache_key = f"demographics:{self._store_id}:{visitor_id}"
        cached = self._cache.get(cache_key) if self._cache is not None else None
        if cached is not None:
            return DemographicsVerdict(
                gender=cached.get("gender"),
                gender_confidence=float(cached.get("gender_confidence", 0.0)),
                age_bucket=cached.get("age_bucket"),
                age_confidence=float(cached.get("age_confidence", 0.0)),
                reason=str(cached.get("reason", "")),
                source="cache",
            )
        try:
            verdict = self._demographics_vlm.classify_demographics(crop)  # type: ignore[union-attr]
        except Exception as err:  # noqa: BLE001 — degrade (null demographics), don't crash the pass
            self._log.warning("vlm_demographics_failed", visitor=visitor_id, error=str(err))
            return None
        if self._cache is not None:
            self._cache.set(
                cache_key,
                {
                    "gender": verdict.gender,
                    "gender_confidence": verdict.gender_confidence,
                    "age_bucket": verdict.age_bucket,
                    "age_confidence": verdict.age_confidence,
                    "reason": verdict.reason,
                },
            )
        self._log.info(
            "vlm_demographics",
            visitor=visitor_id,
            gender=verdict.gender,
            age_bucket=verdict.age_bucket,
            gender_conf=round(verdict.gender_confidence, 3),
        )
        return verdict

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
