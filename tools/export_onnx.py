#!/usr/bin/env python3
"""Export a pretrained SqueezeSegV2 SemanticKITTI checkpoint to ONNX.  Q-4, FR-3.

Q-4 asked which pretrained range-image checkpoint carries a licence permitting
hackathon use.  Answer: **lidar-bonnetal**, from the Photogrammetry and Robotics
Lab at the University of Bonn — MIT licensed, served over plain HTTP with no
account or click-through, and the checkpoint the RangeNet++ paper published.
SalsaNext is also MIT but lives behind a Google Drive interstitial that cannot
be scripted, which matters when the model has to rebuild on a fresh machine.

Of the five available architectures, SqueezeSegV2 is the one this project can
run: 0.94 M parameters and 3.6 MB of weights, against DarkNet21's 92 MB.  On a
CPU-only budget (FR-3, NFR-4) that is the difference between a frame budget and
an apology.

    Architecture below is a faithful reimplementation of
      lidar-bonnetal/train/backbones/squeezesegV2.py
      lidar-bonnetal/train/tasks/semantic/decoders/squeezesegV2.py
      lidar-bonnetal/train/tasks/semantic/modules/segmentator.py
    The MIT License, Copyright (c) 2019 Andres Milioto, Jens Behley,
    Cyrill Stachniss, Photogrammetry and Robotics Lab, University of Bonn.

It is reimplemented rather than vendored so the repository holds no third-party
Python, and it is verified rather than trusted: the published weights are loaded
with ``strict=True``, so a single wrong layer name, channel count or ordering
fails the load instead of silently producing a network that runs and is wrong.

Usage::

    python tools/export_onnx.py --checkpoint model/data/checkpoints/squeezesegV2

Writes ``squeezesegV2_fp32.onnx`` and ``squeezesegV2_int8.onnx`` into
``model/data/models/``, and reports, for each, the agreement with PyTorch on a
real scan.  Numbers printed by this script are measured, not claimed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "model"))

N_CLASSES = 20  # SemanticKITTI learning ids


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


class Fire(nn.Module):
    def __init__(self, inplanes, squeeze_planes, expand1x1, expand3x3, bn_d=0.1):
        super().__init__()
        self.activation = nn.ReLU(inplace=True)
        self.squeeze = nn.Conv2d(inplanes, squeeze_planes, kernel_size=1)
        self.squeeze_bn = nn.BatchNorm2d(squeeze_planes, momentum=bn_d)
        self.expand1x1 = nn.Conv2d(squeeze_planes, expand1x1, kernel_size=1)
        self.expand1x1_bn = nn.BatchNorm2d(expand1x1, momentum=bn_d)
        self.expand3x3 = nn.Conv2d(squeeze_planes, expand3x3, kernel_size=3, padding=1)
        self.expand3x3_bn = nn.BatchNorm2d(expand3x3, momentum=bn_d)

    def forward(self, x):
        x = self.activation(self.squeeze_bn(self.squeeze(x)))
        return torch.cat(
            [
                self.activation(self.expand1x1_bn(self.expand1x1(x))),
                self.activation(self.expand3x3_bn(self.expand3x3(x))),
            ],
            1,
        )


class CAM(nn.Module):
    """Context aggregation module — the V2 in SqueezeSegV2."""

    def __init__(self, inplanes, bn_d=0.1):
        super().__init__()
        self.pool = nn.MaxPool2d(7, 1, 3)
        self.squeeze = nn.Conv2d(inplanes, inplanes // 16, kernel_size=1, stride=1)
        self.squeeze_bn = nn.BatchNorm2d(inplanes // 16, momentum=bn_d)
        self.relu = nn.ReLU(inplace=True)
        self.unsqueeze = nn.Conv2d(inplanes // 16, inplanes, kernel_size=1, stride=1)
        self.unsqueeze_bn = nn.BatchNorm2d(inplanes, momentum=bn_d)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        y = self.pool(x)
        y = self.relu(self.squeeze_bn(self.squeeze(y)))
        y = self.sigmoid(self.unsqueeze_bn(self.unsqueeze(y)))
        return y * x


class FireUp(nn.Module):
    def __init__(self, inplanes, squeeze_planes, expand1x1, expand3x3, bn_d, stride):
        super().__init__()
        self.stride = stride
        self.activation = nn.ReLU(inplace=True)
        self.squeeze = nn.Conv2d(inplanes, squeeze_planes, kernel_size=1)
        self.squeeze_bn = nn.BatchNorm2d(squeeze_planes, momentum=bn_d)
        if stride == 2:
            self.upconv = nn.ConvTranspose2d(
                squeeze_planes, squeeze_planes, kernel_size=[1, 4],
                stride=[1, 2], padding=[0, 1],
            )
        self.expand1x1 = nn.Conv2d(squeeze_planes, expand1x1, kernel_size=1)
        self.expand1x1_bn = nn.BatchNorm2d(expand1x1, momentum=bn_d)
        self.expand3x3 = nn.Conv2d(squeeze_planes, expand3x3, kernel_size=3, padding=1)
        self.expand3x3_bn = nn.BatchNorm2d(expand3x3, momentum=bn_d)

    def forward(self, x):
        x = self.activation(self.squeeze_bn(self.squeeze(x)))
        if self.stride == 2:
            x = self.activation(self.upconv(x))
        return torch.cat(
            [
                self.activation(self.expand1x1_bn(self.expand1x1(x))),
                self.activation(self.expand3x3_bn(self.expand3x3(x))),
            ],
            1,
        )


def _strides(target_os: int) -> list[int]:
    """Reproduce the checkpoint's stride schedule for a given output stride.

    Only the azimuth axis is ever downsampled — 64 rows is one row per beam and
    there is nothing to pool away vertically.
    """
    strides = [2, 2, 2, 2]
    current = 16
    for i, stride in enumerate(reversed(strides)):
        if current == target_os:
            break
        if stride == 2:
            current //= 2
            strides[-1 - i] = 1
    if current != target_os:
        raise ValueError(f"cannot reach output stride {target_os}")
    return strides


class Backbone(nn.Module):
    def __init__(self, params):
        super().__init__()
        depth = 0
        idxs = []
        if params["input_depth"]["range"]:
            depth += 1
            idxs.append(0)
        if params["input_depth"]["xyz"]:
            depth += 3
            idxs.extend([1, 2, 3])
        if params["input_depth"]["remission"]:
            depth += 1
            idxs.append(4)
        self.input_depth = depth
        self.input_idxs = idxs
        bn_d = params["bn_d"]
        s = _strides(params["OS"])
        self.last_channels = 512

        self.conv1a = nn.Sequential(
            nn.Conv2d(depth, 64, kernel_size=3, stride=[1, s[0]], padding=1),
            nn.BatchNorm2d(64, momentum=bn_d),
            nn.ReLU(inplace=True),
            CAM(64, bn_d=bn_d),
        )
        self.conv1b = nn.Sequential(
            nn.Conv2d(depth, 64, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(64, momentum=bn_d),
        )
        self.fire23 = nn.Sequential(
            nn.MaxPool2d(kernel_size=3, stride=[1, s[1]], padding=1),
            Fire(64, 16, 64, 64, bn_d=bn_d),
            CAM(128, bn_d=bn_d),
            Fire(128, 16, 64, 64, bn_d=bn_d),
            CAM(128, bn_d=bn_d),
        )
        self.fire45 = nn.Sequential(
            nn.MaxPool2d(kernel_size=3, stride=[1, s[2]], padding=1),
            Fire(128, 32, 128, 128, bn_d=bn_d),
            Fire(256, 32, 128, 128, bn_d=bn_d),
        )
        self.fire6789 = nn.Sequential(
            nn.MaxPool2d(kernel_size=3, stride=[1, s[3]], padding=1),
            Fire(256, 48, 192, 192, bn_d=bn_d),
            Fire(384, 48, 192, 192, bn_d=bn_d),
            Fire(384, 64, 256, 256, bn_d=bn_d),
            Fire(512, 64, 256, 256, bn_d=bn_d),
        )
        self.dropout = nn.Dropout2d(params["dropout"])

    def _run(self, x, layer, skips, os):
        y = layer(x)
        if y.shape[2] < x.shape[2] or y.shape[3] < x.shape[3]:
            skips[os] = x
            os *= 2
        return y, skips, os

    def forward(self, x):
        x = x[:, self.input_idxs]
        skips = {1: self.conv1b(x)}
        x = self.conv1a(x)
        os = 2
        for layer in (self.fire23, self.dropout, self.fire45,
                      self.dropout, self.fire6789, self.dropout):
            x, skips, os = self._run(x, layer, skips, os)
        return x, skips


class Decoder(nn.Module):
    def __init__(self, params, backbone_os=16, feature_depth=512):
        super().__init__()
        self.backbone_os = backbone_os
        bn_d = params["bn_d"]
        s = list(reversed(_strides(backbone_os)))
        self.firedec10 = FireUp(feature_depth, 64, 128, 128, bn_d=bn_d, stride=s[0])
        self.firedec11 = FireUp(256, 32, 64, 64, bn_d=bn_d, stride=s[1])
        self.firedec12 = FireUp(128, 16, 32, 32, bn_d=bn_d, stride=s[2])
        self.firedec13 = FireUp(64, 16, 32, 32, bn_d=bn_d, stride=s[3])
        self.dropout = nn.Dropout2d(params["dropout"])
        self.last_channels = 64

    def _run(self, x, layer, skips, os):
        feats = layer(x)
        if feats.shape[-1] > x.shape[-1]:
            os //= 2
            feats = feats + skips[os]
        return feats, skips, os

    def forward(self, x, skips):
        os = self.backbone_os
        for layer in (self.firedec10, self.firedec11, self.firedec12, self.firedec13):
            x, skips, os = self._run(x, layer, skips, os)
        return self.dropout(x)


class SqueezeSegV2(nn.Module):
    """Backbone + decoder + head, emitting logits.

    The published model ends in a softmax.  It is dropped here: argmax is
    invariant under softmax, and 20 x 64 x 2048 exponentials per frame is real
    CPU time spent on a value nothing reads.  A caller that wants probabilities
    can soft-max the logits itself.
    """

    def __init__(self, arch, n_classes=N_CLASSES):
        super().__init__()
        self.backbone = Backbone(arch["backbone"])
        self.decoder = Decoder(
            arch["decoder"],
            backbone_os=arch["backbone"]["OS"],
            feature_depth=self.backbone.last_channels,
        )
        self.head = nn.Sequential(
            nn.Dropout2d(p=arch["head"]["dropout"]),
            nn.Conv2d(self.decoder.last_channels, n_classes,
                      kernel_size=3, stride=1, padding=1),
        )

    def forward(self, x):
        y, skips = self.backbone(x)
        return self.head(self.decoder(y, skips))


# ---------------------------------------------------------------------------
# Build, export, verify
# ---------------------------------------------------------------------------


def load_checkpoint(ckpt_dir: Path) -> tuple[SqueezeSegV2, dict]:
    arch = yaml.safe_load((ckpt_dir / "arch_cfg.yaml").read_text())
    model = SqueezeSegV2(arch)
    for attr, fname in (
        ("backbone", "backbone"),
        ("decoder", "segmentation_decoder"),
        ("head", "segmentation_head"),
    ):
        sd = torch.load(ckpt_dir / fname, map_location="cpu", weights_only=True)
        getattr(model, attr).load_state_dict(sd, strict=True)
    return model.eval(), arch


def sample_input(h: int, w: int) -> np.ndarray:
    """A real scan if the KITTI subset is present, otherwise plausible noise."""
    from avr25d.io.kitti import read_velodyne
    from avr25d.perception.range_proj import to_range_image

    scans = sorted((REPO / "model/data/kitti/sequences").glob("*/velodyne/*.bin"))
    if scans:
        xyz, intensity = read_velodyne(scans[0])
        print(f"    verifying against {scans[0].relative_to(REPO)} "
              f"({xyz.shape[0]:,} points)")
    else:
        rng = np.random.default_rng(20260830)
        n = 120_000
        az = rng.uniform(-np.pi, np.pi, n)
        el = np.deg2rad(rng.uniform(-25.0, 3.0, n))
        r = rng.uniform(3.0, 80.0, n)
        xyz = np.stack([r * np.cos(el) * np.cos(az),
                        r * np.cos(el) * np.sin(az),
                        r * np.sin(el)], axis=1).astype(np.float32)
        intensity = rng.random(n).astype(np.float32)
        print("    no KITTI scans on disk — verifying against synthetic noise")
    return to_range_image(xyz, intensity, h=h, w=w).normalised()


def agreement(session, net_in: np.ndarray, reference: np.ndarray) -> tuple[float, float]:
    """-> (fraction of pixels whose argmax matches, median latency in ms)."""
    name = session.get_inputs()[0].name
    session.run(None, {name: net_in})  # warm up
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        out = session.run(None, {name: net_in})[0]
        times.append((time.perf_counter() - t0) * 1000.0)
    got = out.argmax(axis=1)[0]
    return float((got == reference).mean()), float(np.median(times))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--checkpoint", type=Path,
                    default=REPO / "model/data/checkpoints/squeezesegV2")
    ap.add_argument("--out-dir", type=Path, default=REPO / "model/data/models")
    ap.add_argument("--height", type=int, default=64)
    ap.add_argument("--width", type=int, default=2048)
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--no-quantise", action="store_true")
    args = ap.parse_args(argv)

    import onnxruntime as ort

    if not args.checkpoint.is_dir():
        ap.error(f"no checkpoint at {args.checkpoint}; see model/README.md")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] loading {args.checkpoint}")
    model, arch = load_checkpoint(args.checkpoint)
    n_params = sum(p.numel() for p in model.parameters())
    sensor = arch["dataset"]["sensor"]
    print(f"    {n_params/1e6:.3f} M parameters, "
          f"trained at {sensor['img_prop']['height']}x{sensor['img_prop']['width']}, "
          f"fov {sensor['fov_down']}..{sensor['fov_up']} deg")

    print("[2/5] building a verification input")
    net_in = sample_input(args.height, args.width)

    with torch.no_grad():
        torch_out = model(torch.from_numpy(net_in)).numpy()
    reference = torch_out.argmax(axis=1)[0]

    fp32 = args.out_dir / "squeezesegV2_fp32.onnx"
    print(f"[3/5] exporting -> {fp32.name}  (opset {args.opset})")
    torch.onnx.export(
        model,
        torch.from_numpy(net_in),
        str(fp32),
        input_names=["input"],
        output_names=["logits"],
        opset_version=args.opset,
        do_constant_folding=True,
        dynamo=False,
    )

    sess = ort.InferenceSession(str(fp32), providers=["CPUExecutionProvider"])
    acc, ms = agreement(sess, net_in, reference)
    print(f"    {fp32.stat().st_size/1e6:6.2f} MB   "
          f"argmax agrees with PyTorch on {acc*100:.3f}% of pixels   "
          f"{ms:.1f} ms/frame")
    if acc < 0.999:
        print("    !! export does not reproduce PyTorch — do not ship this model")
        return 1

    if args.no_quantise:
        return 0

    int8 = args.out_dir / "squeezesegV2_int8.onnx"
    print(f"[4/5] dynamic int8 quantisation -> {int8.name}")
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        model_input=str(fp32),
        model_output=str(int8),
        weight_type=QuantType.QUInt8,
        extra_options={"MatMulConstBOnly": False},
    )
    sess8 = ort.InferenceSession(str(int8), providers=["CPUExecutionProvider"])
    acc8, ms8 = agreement(sess8, net_in, reference)
    print(f"    {int8.stat().st_size/1e6:6.2f} MB   "
          f"argmax agrees with PyTorch on {acc8*100:.3f}% of pixels   "
          f"{ms8:.1f} ms/frame")

    print("[5/5] summary")
    print(f"    fp32  {fp32.stat().st_size/1e6:6.2f} MB  {ms:6.1f} ms  "
          f"{acc*100:7.3f}% agreement")
    print(f"    int8  {int8.stat().st_size/1e6:6.2f} MB  {ms8:6.1f} ms  "
          f"{acc8*100:7.3f}% agreement")
    if ms8 > ms:
        print("    int8 is not faster here; config should point at the fp32 model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
