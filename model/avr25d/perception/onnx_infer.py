"""ONNX Runtime CPU inference for range-image segmentation.  FR-1, FR-3, FR-6.

The network is a range-image CNN with pretrained SemanticKITTI weights, exported
to ONNX by ``tools/export_onnx.py`` and dynamically quantised to int8.  It runs
on ``CPUExecutionProvider`` and nothing else: no CUDA, no sparse-convolution
extension, no compiled kernel to build on a judge's laptop.  That is FR-3, and
it is the reason the projection in ``range_proj`` exists at all.

Two surfaces, deliberately:

``infer_range_image``
    The IMPLEMENTATION_PLAN §6.6 contract — a range image in, per-pixel class
    ids out.  This is the network and only the network, which is what the
    latency benchmark wants to time in isolation.

``__call__(xyz, intensity)``
    Points in, one of the five PRD §6.1 classes per point out.  §6.6 writes
    ``__call__`` as the per-pixel form, but ``GeometricSegmenter`` already
    promises that the two segmenters are interchangeable, and FR-6 makes the
    choice a runtime flag.  Interchangeable means identical call signatures, so
    the whole-pipeline form takes ``__call__`` and the per-pixel form gets a
    name.  Anything else turns ``--infer network`` back into a code path.

The network predicts 20 SemanticKITTI learning ids; ``labelmap`` merges those
to the five AVR classes.  The merge happens **before** the k-NN vote, not after:
voting in 5-class space is what the taxonomy actually cares about, it stops
three different vehicle classes splitting the vehicle vote against one road
neighbour, and it keeps the vote array at ``n x 5`` instead of ``n x 20``.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from ..config import Config, load_config
from . import labelmap
from .range_proj import from_range_image, to_range_image


class OnnxSegmenter:
    """Callable wrapper with the same surface as ``GeometricSegmenter`` (FR-6)."""

    mode = "network"

    def __init__(
        self,
        model_path: str | Path,
        cfg: Config | None = None,
        providers: tuple[str, ...] = ("CPUExecutionProvider",),
    ):
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"no ONNX model at {path}")

        available = ort.get_available_providers()
        unavailable = [p for p in providers if p not in available]
        if unavailable:
            raise ValueError(
                f"execution provider(s) {', '.join(unavailable)} not built into "
                f"this onnxruntime (available: {', '.join(available)})"
            )

        self.cfg = load_config() if cfg is None else cfg
        self.model_path = path
        self._session = ort.InferenceSession(str(path), providers=list(providers))

        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        if len(inp.shape) != 4:
            raise ValueError(f"expected a 4D NCHW input, got shape {inp.shape}")
        if inp.shape[1] != 5:
            raise ValueError(
                f"model takes {inp.shape[1]} channels; the range image supplies 5 "
                "channels (range, x, y, z, intensity) — see range_proj.normalised"
            )

        # A statically shaped model is the authority on its own input size.
        # Projecting at a resolution the weights were not trained for produces a
        # plausible-looking, entirely wrong segmentation, so it is not a setting.
        img = self.cfg.perception.range_image
        self.h = inp.shape[2] if isinstance(inp.shape[2], int) else img.h
        self.w = inp.shape[3] if isinstance(inp.shape[3], int) else img.w
        self.fov_up = float(img.fov_up)
        self.fov_down = float(img.fov_down)

        out = self._session.get_outputs()[0]
        self.n_classes = out.shape[1] if isinstance(out.shape[1], int) else None

        knn = self.cfg.perception.knn
        self._knn = dict(
            k=int(knn.k),
            search=int(knn.search),
            cutoff=float(knn.cutoff),
            sigma=float(knn.sigma),
        )

        self._last_latency_ms = 0.0
        self._last_timings_ms: dict[str, float] = {}

    # -- the §6.6 contract --------------------------------------------------

    def infer_range_image(self, net_in: np.ndarray) -> np.ndarray:
        """Normalised range image ``float32[1,5,h,w]`` -> ``int64[h,w]`` class ids."""
        logits = self._session.run(None, {self._input_name: net_in})[0]
        return np.asarray(logits).argmax(axis=1)[0].astype(np.int64)

    # -- the interchangeable surface ---------------------------------------

    def __call__(self, xyz: np.ndarray, intensity: np.ndarray) -> np.ndarray:
        """Points -> one AVR class per point (FR-1), occluded points included."""
        t0 = time.perf_counter()
        proj = to_range_image(
            xyz,
            intensity,
            h=self.h,
            w=self.w,
            fov_up=self.fov_up,
            fov_down=self.fov_down,
        )
        t1 = time.perf_counter()
        pred = self.infer_range_image(proj.normalised())
        t2 = time.perf_counter()
        avr = labelmap.LEARNING_TO_AVR[np.clip(pred, 0, labelmap.N_LEARNING - 1)]
        labels = from_range_image(
            avr,
            proj.px,
            proj.py,
            xyz,
            proj_range=proj.proj_range,
            **self._knn,
        )
        t3 = time.perf_counter()

        self._last_timings_ms = {
            "project": (t1 - t0) * 1000.0,
            "infer": (t2 - t1) * 1000.0,
            "reproject": (t3 - t2) * 1000.0,
        }
        self._last_latency_ms = (t3 - t0) * 1000.0
        return labels

    # -- measured, and reported as measured --------------------------------

    @property
    def providers(self) -> tuple[str, ...]:
        """What the session actually resolved to, not what was asked for."""
        return tuple(self._session.get_providers())

    @property
    def last_latency_ms(self) -> float:
        return self._last_latency_ms

    @property
    def last_timings_ms(self) -> dict[str, float]:
        """Per-stage breakdown of the last call, for the HUD and the benchmark."""
        return dict(self._last_timings_ms)
