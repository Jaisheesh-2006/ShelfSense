"""Vision-Language Model client for the OFFLINE detection pass (ADR-0027/0031).

Pluggable multi-provider: the default is **Groq** (multimodal Llama-4 Scout — what we actually ran);
**Gemini** is also supported. The detector can ask a VLM two narrow, high-value questions while it
generates events:

  * **staff vs customer** — once per tracked person (replaces the per-store uniform-COLOUR heuristic
    in `staff.py`, which is brittle when a customer happens to wear the staff colour);
  * **camera zone** — once per camera (replaces the hand-mapped `primary_zone` in `zones.py`),
    by reading the shelves the camera actually shows.

Design constraints (all enforced here or by the caller):
  * **Gate-safe.** The SDK is imported lazily; `build_vlm_client` returns ``None`` when the VLM is
    disabled, the key is absent, or the package isn't installed — so the heuristic path always works
    and `docker compose up` needs no key/network.
  * **Sparse + cached.** Calls are per-person / per-camera (a handful per clip), and every verdict
    is cached to disk (`JsonFileCache`), so re-runs are free and deterministic and the cache can be
    committed for reproducible replay.
  * **Schema-neutral.** Verdicts only feed the existing `is_staff` / `zone_id` fields; the reason
    and confidence are returned for logging/eval, never added to the event (page-5 schema).

The prompts are module-level constants so they can be quoted verbatim in CHOICES.md (Part D).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

# --- Verdict value objects -------------------------------------------------------------------


@dataclass(frozen=True)
class StaffVerdict:
    """A staff/customer judgement for one person crop."""

    is_staff: bool
    confidence: float  # 0..1, the model's self-reported confidence
    reason: str
    source: str = "vlm"  # "vlm" | "heuristic" | "cache" — for observability/eval


@dataclass(frozen=True)
class ZoneVerdict:
    """A zone label for one camera frame; `zone` is one of the candidate zones supplied."""

    zone: str
    confidence: float
    reason: str
    source: str = "vlm"


@dataclass(frozen=True)
class DemographicsVerdict:
    """A coarse demographic prediction for one person crop (ADR-0040).

    `gender` is "M"/"F"/None and `age_bucket` a coarse band/None — both are *predictions* from body,
    build, hair and clothing (the face is blurred), each with its own self-reported confidence so a
    hesitant guess can be down-weighted or dropped. They feed event metadata, never a hard count.
    """

    gender: str | None  # "M" | "F" | None (unknown)
    gender_confidence: float
    age_bucket: str | None  # coarse band ("child"/"teen"/"adult"/"senior") | None
    age_confidence: float
    reason: str
    source: str = "vlm"


class VLMClient(Protocol):
    """The narrow surface the detector depends on (a real provider client or a test fake)."""

    def classify_staff(
        self, image_bgr: np.ndarray, staff_hint: str | None = None
    ) -> StaffVerdict: ...

    def classify_zone(
        self,
        image_bgr: np.ndarray,
        candidate_zones: list[str],
        floor_plan_bgr: np.ndarray | None = None,
    ) -> ZoneVerdict: ...

    def classify_demographics(self, image_bgr: np.ndarray) -> DemographicsVerdict: ...


# --- Prompts (quoted in CHOICES.md / INTERVIEW_QA.md) ----------------------------------------

STAFF_PROMPT = (
    "You are an expert visual analyst examining a "
    "cropped CCTV image of a person in a retail "
    "beauty store. "
    "Your task is to classify whether this person "
    "is a STORE EMPLOYEE (staff) or a CUSTOMER "
    "(shopper).\n"
    "EVIDENCE TO CONSIDER:\n"
    "- Uniforms, lanyards, ID badges, aprons, or "
    "earpieces strongly indicate STAFF.\n"
    "- Casual clothing, coats, carrying personal "
    "bags, or shopping baskets strongly indicate "
    "CUSTOMER.\n"
    "- Standing behind a counter or restocking "
    "shelves indicates STAFF.\n"
    "- If you are unsure or the image is too blurry "
    "to distinguish a uniform, default to "
    "'customer' with low confidence.\n"
    "Respond with ONLY a JSON object exactly like "
    "this: "
    '{"label": "staff" | "customer", '
    '"confidence": <float 0.0-1.0>, '
    '"reason": "<concise reason>"}'
)


def build_staff_prompt(staff_hint: str | None) -> str:
    """Add optional store-specific uniform context to the base staff prompt."""
    hint = (staff_hint or "").strip()
    if not hint:
        return STAFF_PROMPT
    return f"{STAFF_PROMPT}\n\nStore-specific context: {hint}"


DEMOGRAPHICS_PROMPT = (
    "You are a retail-analytics vision model looking at a "
    "cropped CCTV image of ONE shopper in a beauty store. "
    "The FACE IS BLURRED for privacy, so judge ONLY from "
    "body build, posture, hair, and clothing.\n"
    "Estimate two COARSE attributes. PREFER 'unknown' with "
    "low confidence when the crop is occluded, tiny, or "
    "ambiguous — do not guess.\n"
    "Respond with ONLY a JSON object exactly like this: "
    '{"gender": "male" | "female" | "unknown", '
    '"gender_confidence": <float 0.0-1.0>, '
    '"age_bucket": "child" | "teen" | "adult" | "senior" '
    '| "unknown", '
    '"age_confidence": <float 0.0-1.0>, '
    '"reason": "<concise reason>"}'
)


def build_zone_prompt(candidate_zones: list[str]) -> str:
    """Build the zone-classification prompt constrained to the caller's zone vocabulary."""
    options = ", ".join(candidate_zones)
    return (
        "You are analysing one CCTV frame from a single fixed camera inside a retail beauty store. "
        "Identify the PRIMARY retail zone this camera covers, based on the shelves, products, "
        "fixtures, and signage visible. Choose exactly one label from this list, verbatim: "
        f"[{options}]. If none clearly fits, choose the closest and report low confidence. "
        'Respond with ONLY a JSON object: {"zone": "<one of the labels>", '
        '"confidence": <number 0..1>, "reason": "<short reason>"}.'
    )


# --- Helpers ---------------------------------------------------------------------------------


def encode_jpeg(image_bgr: np.ndarray, quality: int = 85) -> bytes:
    """Encode a BGR (OpenCV) image as JPEG bytes for upload. Raises on encode failure."""
    import cv2  # local import: keep this module importable without OpenCV (e.g. unit tests)

    ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("cv2.imencode failed to encode image as JPEG")
    return buf.tobytes()


def extract_json(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating ```json fences / surrounding prose.

    Pure + unit-testable. Raises ValueError if no JSON object can be found.
    """
    s = text.strip()
    if s.startswith("```"):  # strip a ```json ... ``` fence
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if 0 <= start < end:
            return json.loads(s[start : end + 1])
        raise ValueError(f"no JSON object in model reply: {text!r}") from None


def _as_confidence(value: object) -> float:
    """Coerce a model-reported confidence to a clamped float in [0, 1] (0.0 on garbage)."""
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def parse_staff_reply(text: str) -> StaffVerdict:
    """Turn a raw model reply into a StaffVerdict (pure; validates the label)."""
    obj = extract_json(text)
    label = str(obj.get("label", "")).strip().lower()
    return StaffVerdict(
        is_staff=label == "staff",
        confidence=_as_confidence(obj.get("confidence")),
        reason=str(obj.get("reason", "")).strip()[:200],
    )


_GENDER_MAP = {"male": "M", "m": "M", "female": "F", "f": "F"}
_AGE_BUCKETS = {"child", "teen", "adult", "senior"}


def parse_demographics_reply(text: str) -> DemographicsVerdict:
    """Turn a raw model reply into a DemographicsVerdict (pure; snaps to known labels else None)."""
    obj = extract_json(text)
    gender_raw = str(obj.get("gender", "")).strip().lower()
    age_raw = str(obj.get("age_bucket", "")).strip().lower()
    return DemographicsVerdict(
        gender=_GENDER_MAP.get(gender_raw),
        gender_confidence=_as_confidence(obj.get("gender_confidence")),
        age_bucket=age_raw if age_raw in _AGE_BUCKETS else None,
        age_confidence=_as_confidence(obj.get("age_confidence")),
        reason=str(obj.get("reason", "")).strip()[:200],
    )


def parse_zone_reply(text: str, candidate_zones: list[str]) -> ZoneVerdict:
    """Turn a raw model reply into a ZoneVerdict, snapping the label to a known candidate.

    A label outside the candidate set is treated as no-confidence so the caller keeps its default.
    """
    obj = extract_json(text)
    raw = str(obj.get("zone", "")).strip()
    lookup = {z.lower(): z for z in candidate_zones}
    zone = lookup.get(raw.lower(), "")
    confidence = _as_confidence(obj.get("confidence")) if zone else 0.0
    return ZoneVerdict(
        zone=zone or raw,
        confidence=confidence,
        reason=str(obj.get("reason", "")).strip()[:200],
    )


# --- Persistent verdict cache ----------------------------------------------------------------


class JsonFileCache:
    """A tiny persistent string->dict cache backed by a JSON file (atomic writes).

    Used to memoise VLM verdicts across runs so the offline pass is cheap and reproducible. Loads
    lazily and tolerates a missing/corrupt file (starts empty). Not concurrency-safe — the detector
    is single-process.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {}

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def set(self, key: str, value: dict) -> None:
        self._data[key] = value
        self._flush()

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


# --- Clients ---------------------------------------------------------------------------------


class _BaseVLMClient:
    """Shared classify_* logic over an abstract `_generate(image, prompt, *extra) -> str`.

    Subclasses implement `_generate` for one provider; the staff/zone prompts + parsing are common,
    so adding a provider is just a new `_generate`.
    """

    def _generate(self, image_bgr: np.ndarray, prompt: str, *extra_images: np.ndarray) -> str:
        raise NotImplementedError

    def classify_staff(self, image_bgr: np.ndarray, staff_hint: str | None = None) -> StaffVerdict:
        return parse_staff_reply(self._generate(image_bgr, build_staff_prompt(staff_hint)))

    def classify_zone(
        self,
        image_bgr: np.ndarray,
        candidate_zones: list[str],
        floor_plan_bgr: np.ndarray | None = None,
    ) -> ZoneVerdict:
        prompt = build_zone_prompt(candidate_zones)
        extra = (floor_plan_bgr,) if floor_plan_bgr is not None else ()
        return parse_zone_reply(self._generate(image_bgr, prompt, *extra), candidate_zones)

    def classify_demographics(self, image_bgr: np.ndarray) -> DemographicsVerdict:
        return parse_demographics_reply(self._generate(image_bgr, DEMOGRAPHICS_PROMPT))


class GeminiVLMClient(_BaseVLMClient):
    """Calls Google Gemini. The SDK is imported lazily in __init__, so importing this module never
    requires `google-genai`; constructing it does (via `build_vlm_client`, which guards it)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        temperature: float = 0.0,
    ) -> None:
        from google import genai  # lazy: only needed when the VLM is actually enabled
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._temperature = temperature

    def _generate(self, image_bgr: np.ndarray, prompt: str, *extra_images: np.ndarray) -> str:
        types = self._types
        parts: Any = [
            types.Part.from_bytes(data=encode_jpeg(img), mime_type="image/jpeg")
            for img in (image_bgr, *extra_images)
        ]
        parts.append(prompt)
        config = types.GenerateContentConfig(
            temperature=self._temperature,
            response_mime_type="application/json",
            http_options=types.HttpOptions(timeout=int(self._timeout_s * 1000)),
        )
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=parts, config=config
                )
                return resp.text or ""
            except Exception as err:  # noqa: BLE001 — transient API errors; retry then propagate
                last_err = err
                if attempt < self._max_retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Gemini call failed after retries: {last_err}") from last_err


class GroqVLMClient(_BaseVLMClient):
    """Calls a Groq-hosted multimodal model (OpenAI-style chat API) — e.g. Llama-4 Scout. SDK is
    lazily imported. Images go as base64 data URLs; the prompt asks for JSON, parsed by
    `extract_json` (no JSON-mode flag — Groq vision models don't all support it)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        temperature: float = 0.0,
    ) -> None:
        from groq import Groq  # lazy: only needed when provider=groq

        self._client = Groq(api_key=api_key, timeout=timeout_s)
        self._model = model
        self._max_retries = max_retries
        self._temperature = temperature

    def _generate(self, image_bgr: np.ndarray, prompt: str, *extra_images: np.ndarray) -> str:
        import base64

        content: list[dict] = [{"type": "text", "text": prompt}]
        for img in (image_bgr, *extra_images):
            b64 = base64.b64encode(encode_jpeg(img)).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        last_err: Exception | None = None
        messages: Any = [{"role": "user", "content": content}]
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self._temperature,
                )
                return resp.choices[0].message.content or ""
            except Exception as err:  # noqa: BLE001 — transient API errors; retry then propagate
                last_err = err
                if attempt < self._max_retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Groq call failed after retries: {last_err}") from last_err


# provider -> (client class, api-key settings attr, pip hint)
_PROVIDERS: dict[str, tuple[Any, str, str]] = {
    "gemini": (GeminiVLMClient, "gemini_api_key", "pip install google-genai"),
    "groq": (GroqVLMClient, "groq_api_key", "pip install groq"),
}


def build_vlm_client(settings, log) -> VLMClient | None:
    """Construct the configured VLM client, or ``None`` to signal heuristic-only operation.

    Returns ``None`` (logging the reason) when the VLM is disabled, the provider is unsupported, the
    API key is missing, or the SDK isn't installed — so callers degrade gracefully and the gate is
    never coupled to the VLM. Providers: `gemini`, `groq`.
    """
    if not settings.vlm_enabled:
        return None
    entry = _PROVIDERS.get(settings.vlm_provider)
    if entry is None:
        log.warning("vlm_unsupported_provider", provider=settings.vlm_provider)
        return None
    client_cls, key_attr, pip_hint = entry
    api_key = getattr(settings, key_attr, "")
    if not api_key:
        log.warning(
            "vlm_disabled_no_key", provider=settings.vlm_provider, hint=f"set {key_attr.upper()}"
        )
        return None
    try:
        client = client_cls(
            api_key,
            settings.vlm_model,
            timeout_s=settings.vlm_timeout_s,
            max_retries=settings.vlm_max_retries,
        )
    except ImportError:
        log.warning("vlm_sdk_missing", provider=settings.vlm_provider, hint=pip_hint)
        return None
    except Exception as err:  # noqa: BLE001 — bad key/config: fall back rather than crash the pass
        log.warning("vlm_init_failed", error=str(err))
        return None
    log.info("vlm_enabled", provider=settings.vlm_provider, model=settings.vlm_model)
    return client
