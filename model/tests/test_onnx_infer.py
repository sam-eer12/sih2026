"""ONNX Runtime CPU segmenter.  FR-1, FR-3, FR-6 — tests T-P1, T-P3.

The tests build their own tiny ONNX graphs rather than leaning on the exported
checkpoint.  A 1x1 convolution with zero weights and a biased class makes the
network's answer known in advance, so the assertions are about the wrapper —
providers, shapes, the 20 -> 5 merge, honest timing — and not about whether
SqueezeSegV2 happens to be right about a patch of road.  It also means the
suite runs on a machine that has never downloaded a checkpoint.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest
from onnx import TensorProto, checker, helper, numpy_helper, save_model

from avr25d.perception import labelmap
from avr25d.perception.onnx_infer import OnnxSegmenter

H, W = 8, 32
N_CLASSES = 20


def _write_model(path, winner, n_in=5, h=H, w=W, n_out=N_CLASSES):
    """A model that answers ``winner`` for every pixel, whatever the input."""
    weight = numpy_helper.from_array(
        np.zeros((n_out, n_in, 1, 1), np.float32), "w"
    )
    bias = np.zeros(n_out, np.float32)
    bias[winner] = 1.0
    graph = helper.make_graph(
        [helper.make_node("Conv", ["input", "w", "b"], ["logits"], kernel_shape=[1, 1])],
        "stub",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, n_in, h, w])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, n_out, h, w])],
        [weight, numpy_helper.from_array(bias, "b")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    checker.check_model(model)
    save_model(model, str(path))
    return path


@pytest.fixture(scope="module")
def road_model(tmp_path_factory):
    # learning id 9 is "road" -> DRIVABLE
    return _write_model(tmp_path_factory.mktemp("m") / "road.onnx", 9)


@pytest.fixture(scope="module")
def car_model(tmp_path_factory):
    # learning id 1 is "car" -> DYNAMIC_OBJECT
    return _write_model(tmp_path_factory.mktemp("m") / "car.onnx", 1)


@pytest.fixture(scope="module")
def scan():
    rng = np.random.default_rng(20260830)
    n = 4000
    az = rng.uniform(-np.pi, np.pi, n)
    el = np.deg2rad(rng.uniform(-24.0, 2.0, n))
    r = rng.uniform(4.0, 60.0, n)
    xyz = np.stack(
        [r * np.cos(el) * np.cos(az), r * np.cos(el) * np.sin(az), r * np.sin(el)],
        axis=1,
    ).astype(np.float32)
    return xyz, rng.random(n).astype(np.float32)


# --------------------------------------------------------------------------
# T-P3 — CPU only, on every platform
# --------------------------------------------------------------------------


def test_TP3_session_runs_on_the_cpu_execution_provider_alone(road_model, scan):
    seg = OnnxSegmenter(road_model)
    assert seg.providers == ("CPUExecutionProvider",)
    labels = seg(*scan)
    assert labels.shape == (scan[0].shape[0],)


def test_TP3_a_provider_the_runtime_does_not_have_is_refused(road_model):
    missing = "NoSuchExecutionProvider"
    assert missing not in ort.get_available_providers()
    with pytest.raises(ValueError, match=missing):
        OnnxSegmenter(road_model, providers=(missing,))


def test_a_missing_model_file_names_the_path(tmp_path):
    absent = tmp_path / "not_here.onnx"
    with pytest.raises(FileNotFoundError, match="not_here.onnx"):
        OnnxSegmenter(absent)


# --------------------------------------------------------------------------
# The §6.6 surface — per-pixel class ids
# --------------------------------------------------------------------------


def test_infer_range_image_returns_one_class_id_per_pixel(road_model):
    seg = OnnxSegmenter(road_model)
    net_in = np.zeros((1, 5, H, W), np.float32)
    pred = seg.infer_range_image(net_in)
    assert pred.shape == (H, W)
    assert pred.dtype == np.int64
    assert np.all(pred == 9)


def test_the_image_size_comes_from_the_model_not_a_constant(road_model):
    seg = OnnxSegmenter(road_model)
    assert (seg.h, seg.w) == (H, W)


def test_a_model_that_does_not_take_five_channels_is_rejected(tmp_path):
    path = _write_model(tmp_path / "three.onnx", 9, n_in=3)
    with pytest.raises(ValueError, match="5 channels"):
        OnnxSegmenter(path)


# --------------------------------------------------------------------------
# T-P1 — one AVR label per input point
# --------------------------------------------------------------------------


def test_TP1_every_point_gets_exactly_one_label_in_the_five_class_range(
    road_model, scan
):
    xyz, intensity = scan
    labels = OnnxSegmenter(road_model)(xyz, intensity)
    assert labels.shape == (xyz.shape[0],)
    assert labels.dtype == np.uint8
    assert labels.min() >= 0 and labels.max() <= 4


def test_network_classes_are_merged_through_the_learning_table(
    road_model, car_model, scan
):
    xyz, intensity = scan
    road = OnnxSegmenter(road_model)(xyz, intensity)
    car = OnnxSegmenter(car_model)(xyz, intensity)

    assert np.all(road == labelmap.LEARNING_TO_AVR[9])
    assert np.all(car == labelmap.LEARNING_TO_AVR[1])
    assert labelmap.LEARNING_TO_AVR[9] != labelmap.LEARNING_TO_AVR[1]


def test_an_empty_scan_produces_no_labels(road_model):
    labels = OnnxSegmenter(road_model)(
        np.zeros((0, 3), np.float32), np.zeros(0, np.float32)
    )
    assert labels.shape == (0,)
    assert labels.dtype == np.uint8


# --------------------------------------------------------------------------
# FR-6 interchangeability and honest timing
# --------------------------------------------------------------------------


def test_mode_names_the_perception_path_for_the_hud(road_model):
    assert OnnxSegmenter(road_model).mode == "network"


def test_latency_is_measured_on_a_real_call_not_declared(road_model, scan):
    seg = OnnxSegmenter(road_model)
    assert seg.last_latency_ms == 0.0
    seg(*scan)
    assert seg.last_latency_ms > 0.0


def test_the_stage_breakdown_accounts_for_the_whole_call(road_model, scan):
    seg = OnnxSegmenter(road_model)
    seg(*scan)
    stages = seg.last_timings_ms
    assert set(stages) == {"project", "infer", "reproject"}
    assert sum(stages.values()) == pytest.approx(seg.last_latency_ms, rel=0.05)


def test_it_is_a_drop_in_for_the_geometric_segmenter(road_model, cfg, scan):
    from avr25d.perception.geometric_seg import GeometricSegmenter

    net = OnnxSegmenter(road_model)
    geo = GeometricSegmenter(cfg)
    for seg in (net, geo):
        labels = seg(*scan)
        assert labels.shape == (scan[0].shape[0],)
        assert labels.dtype == np.uint8
        assert isinstance(seg.mode, str)
        assert seg.last_latency_ms > 0.0


# --------------------------------------------------------------------------
# The real exported checkpoint, when it has been built
# --------------------------------------------------------------------------

MODEL_DIR = Path(__file__).resolve().parents[1] / "data" / "models"
EXPORTED = sorted(MODEL_DIR.glob("squeezesegV2*.onnx"))


@pytest.mark.skipif(not EXPORTED, reason="run tools/export_onnx.py first")
@pytest.mark.parametrize("path", EXPORTED, ids=lambda p: p.stem)
def test_TP3_the_exported_checkpoint_segments_a_scan_on_cpu(path, scan):
    seg = OnnxSegmenter(path)
    assert seg.providers == ("CPUExecutionProvider",)
    assert (seg.h, seg.w) == (64, 2048)
    assert seg.n_classes == 20

    labels = seg(*scan)
    assert labels.shape == (scan[0].shape[0],)
    assert labels.min() >= 0 and labels.max() <= 4
    assert seg.last_latency_ms > 0.0
