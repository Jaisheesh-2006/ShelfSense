# PROMPT
# Task: Unit-test the gate-safe `build_embedder` factory — it returns None (→ colour-histogram
#   fallback) when the learned CNN backend is off or unsupported, so the detector and the acceptance
#   gate never hard-depend on torch/torchvision.
# Context: build_embedder(settings, log) constructs a torchvision ReIDEmbedder only when
#   reid_backend == "cnn"; otherwise it returns None and the pipeline uses appearance_signature
#   (reid.py). The "histogram" / unsupported paths must not import torch.
# Constraints: no torch on the tested path; fake settings (SimpleNamespace) + a null logger.
# Output: pytest asserting None for the default histogram backend and any unsupported backend.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).

from __future__ import annotations

from types import SimpleNamespace

from app.embedding import build_embedder


class _NullLog:
    def info(self, *a, **k) -> None: ...
    def warning(self, *a, **k) -> None: ...


def _settings(backend: str) -> SimpleNamespace:
    return SimpleNamespace(reid_backend=backend, reid_cnn_model="mobilenet_v3_large")


def test_build_embedder_none_for_histogram_backend():
    # Default backend → no embedder, no torch import (gate-safe).
    assert build_embedder(_settings("histogram"), _NullLog()) is None


def test_build_embedder_none_for_unknown_backend():
    assert build_embedder(_settings("something-else"), _NullLog()) is None
