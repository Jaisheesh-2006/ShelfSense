"""Learned appearance embedding for cross-view / cross-camera Re-ID (ADR-0036).

The colour-histogram signature (`reid.py`) is **view-dependent**: the same person seen from the
front vs the back yields different histograms, so the gallery mints a new id — over-splitting one
shopper (especially moving staff) into several `visitor_id`s. A learned CNN embedding is far more
view-invariant: it encodes appearance / shape / texture, so the front and back of the same person
land close together in feature space and Re-ID collapses them to one identity.

Gate-safe + pluggable (like the VLM): `build_embedder` returns ``None`` when disabled or torch /
torchvision is unavailable, so the detector falls back to the colour histogram and the acceptance
gate never depends on it. `extract(image, x, y, w, h) -> unit vector` matches the histogram's
`appearance_signature` signature, so it drops straight into the accumulation in `main.py`.

Backbone: a torchvision ImageNet model (reliable, already a transitive dep via ultralytics). A true
person-Re-ID network (OSNet) would be stronger; the backbone is swappable via `reid_cnn_model` and a
real Re-ID checkpoint can replace it here without touching callers.
"""

from __future__ import annotations

import numpy as np

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)
# Person crops are resized to a portrait Re-ID aspect ratio (height, width).
_CROP_H, _CROP_W = 256, 128


class ReIDEmbedder:
    """Extracts an L2-normalised appearance embedding from a person crop with a CNN backbone."""

    def __init__(self, model_name: str) -> None:
        import torch
        from torchvision import models

        builders = {
            "mobilenet_v3_large": (
                models.mobilenet_v3_large, models.MobileNet_V3_Large_Weights.IMAGENET1K_V2,
            ),
            "mobilenet_v3_small": (
                models.mobilenet_v3_small, models.MobileNet_V3_Small_Weights.IMAGENET1K_V1,
            ),
            "resnet50": (models.resnet50, models.ResNet50_Weights.IMAGENET1K_V2),
        }
        if model_name not in builders:
            raise ValueError(f"unknown reid model {model_name!r}; choose one of {list(builders)}")
        ctor, weights = builders[model_name]
        net = ctor(weights=weights)
        net.eval()
        # Drop the classifier head → a pooled feature extractor.
        if model_name.startswith("mobilenet"):
            self._net = torch.nn.Sequential(net.features, net.avgpool, torch.nn.Flatten())
        else:  # resnet family: everything up to (but not including) the fc layer
            self._net = torch.nn.Sequential(*list(net.children())[:-1], torch.nn.Flatten())
        self._net.eval()
        self._torch = torch
        self._mean = torch.tensor(_IMAGENET_MEAN).view(1, 3, 1, 1)
        self._std = torch.tensor(_IMAGENET_STD).view(1, 3, 1, 1)
        with torch.no_grad():  # probe the output dimensionality
            self._dim = int(self._net(torch.zeros(1, 3, _CROP_H, _CROP_W)).shape[-1])

    @property
    def dim(self) -> int:
        return self._dim

    def extract(self, image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
        """Return a unit-norm embedding for the person box (zeros for an empty/clipped crop)."""
        import cv2

        torch = self._torch
        ih, iw = image.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(iw, x + w), min(ih, y + h)
        if x1 <= x0 or y1 <= y0:
            return np.zeros(self._dim, dtype=np.float32)
        crop = cv2.resize(image[y0:y1, x0:x1], (_CROP_W, _CROP_H))
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
        tensor = (tensor - self._mean) / self._std
        with torch.no_grad():
            vec = self._net(tensor).squeeze(0).numpy().astype(np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec


def build_embedder(settings, log) -> ReIDEmbedder | None:
    """Construct the learned Re-ID embedder, or ``None`` to keep the colour-histogram fallback.

    Returns ``None`` (logging why) when `reid_backend` != "cnn" or torch/torchvision is missing, so
    callers degrade to `appearance_signature` and the gate is never coupled to the embedder.
    """
    if settings.reid_backend.lower() != "cnn":
        return None
    try:
        embedder = ReIDEmbedder(settings.reid_cnn_model)
    except ImportError as err:
        log.warning("reid_embedder_sdk_missing", error=str(err))
        return None
    except Exception as err:  # noqa: BLE001 — bad model/weights: fall back, don't crash the pass
        log.warning("reid_embedder_failed", error=str(err))
        return None
    log.info("reid_embedder_enabled", model=settings.reid_cnn_model, dim=embedder.dim)
    return embedder
