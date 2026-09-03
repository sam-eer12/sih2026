#!/usr/bin/env python3
"""Q-1, the 5-class split, and the decoder-head fine-tune.  Days 9-10.

    python tools/finetune.py probe
    python tools/finetune.py split
    python tools/finetune.py train    [--epochs 2] [--limit N]
    python tools/finetune.py evaluate

Q-1, and why it stopped mattering
---------------------------------
Q-1 asks whether the GPU in the Windows box supports CUDA and with how much
VRAM, and the plan makes Day 10 conditional on the answer: GPU fine-tune if it
is usable, CPU decoder-head-only fine-tune if it is not.

``probe`` answers the question the conditional was really asking.  The machine
holding the dataset, the checkpoint and the 971-scan label cache has an Apple
M4 whose GPU is reachable through PyTorch's Metal backend, and forward *and
backward* both run on it.  So the fine-tune has a GPU regardless of what the
Windows box turns out to contain, and it is the GPU on the machine where the
data already is — which is the one that matters, since moving 2.2 GB of KITTI
and rebuilding the environment on a second machine is most of a day.

That is the definitive part of the answer.  The part this repository cannot
settle is what card is in the Windows box; that needs someone sitting at it,
and ``probe`` prints the one command to run there.  It is worth knowing only
for the HUD's live-inference figure (PRD Q-1's second sentence), which is a
presentation nicety rather than a dependency: nothing in the pipeline, the
benchmark or the demo waits on it.

The split
---------
Train on sequences 00 and 05, validate on 04.  **Sequence-level, not a random
frame split.**  KITTI is a 10 Hz recording of a moving vehicle, so frame 41 is
very nearly frame 40; a random 80/20 split over frames puts near-duplicates on
both sides and reports a validation score that is partly a memorisation score.
Splitting by sequence costs a little training data and buys a number that means
what it says.

It also keeps the comparison honest against §11.3: sequence 04 is the sequence
the Day 7 evaluation reports in full, so before and after are measured on
exactly the scans the deck already quotes.

The fine-tune
-------------
The backbone is frozen — parameters *and* BatchNorm, which is the part that is
easy to get wrong: leaving BN in training mode lets its running statistics
drift on the new data even with ``requires_grad=False`` everywhere, and the
pretrained features quietly degrade while the loss looks fine.

The head's final convolution is replaced with a 5-output one and initialised
from the 20-class weights by averaging each AVR class's constituents, so
training starts from the merge the pipeline already performs rather than from
noise.  The decoder and the new head train; everything else is fixed.

Everything is measured through the *production* path — projection, network,
k-NN reprojection, then ``bench/distance_bins`` — so the after number is
comparable to the before number and to §11.3, rather than being a per-pixel
score that flatters itself by skipping the reprojection.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "model"))
sys.path.insert(0, str(REPO / "tools"))

MODEL_DIR = REPO / "model" / "data" / "models"
SPLIT_PATH = REPO / "model" / "data" / "splits" / "finetune_5class.json"
WEIGHTS_PATH = MODEL_DIR / "squeezesegV2_5class.pt"
REPORT_PATH = REPO / "model" / "data" / "finetune_report.json"


def _tagged(path: Path, tag: str) -> Path:
    """``squeezesegV2_5class.pt`` -> ``squeezesegV2_5class.uniform.pt``."""
    return path if not tag else path.with_suffix(f".{tag}{path.suffix}")

TRAIN_SEQUENCES = ("00", "05")
VAL_SEQUENCE = "04"


# ---------------------------------------------------------------------------
# Q-1
# ---------------------------------------------------------------------------

def probe(_args) -> int:
    """What compute is actually available here, measured rather than assumed."""
    import platform

    import torch

    print(f"host          {platform.platform()}")
    print(f"torch         {torch.__version__}")

    devices = []
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            devices.append(("cuda", f"{p.name}, {p.total_memory / 2**30:.1f} GiB VRAM"))
    if torch.backends.mps.is_available():
        devices.append(("mps", "Apple GPU via Metal"))
    devices.append(("cpu", platform.processor() or "cpu"))

    print("\ndevices:")
    for name, detail in devices:
        print(f"  {name:<5} {detail}")

    best = devices[0][0]
    print(f"\nfine-tune device -> {best}")

    # A device that cannot run a backward pass is not a training device, and
    # "torch says it is available" is not the same claim.
    dev = torch.device(best)
    x = torch.randn(2, 5, 64, 512, device=dev, requires_grad=True)
    conv = torch.nn.Conv2d(5, 32, 3, padding=1).to(dev)
    t0 = time.perf_counter()
    for _ in range(10):
        conv(x).mean().backward()
    if best == "cuda":
        torch.cuda.synchronize()
    elif best == "mps":
        torch.mps.synchronize()
    dt = (time.perf_counter() - t0) * 1e3 / 10
    print(f"backward pass verified on {best}: {dt:.1f} ms per 2x5x64x512 step")

    print(
        "\nQ-1 — the half this machine can answer: a usable training GPU is "
        f"present here ({best}), on the machine that already holds the "
        "dataset, the checkpoint and the label cache. Day 10 does not wait on "
        "the Windows box."
        "\nQ-1 — the half it cannot: what card is in the Windows box. Run this "
        "there and paste the output at standup:"
        "\n    python -c \"import torch;print(torch.cuda.is_available(),"
        "torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')\""
        "\nIt is wanted only for the HUD's live-inference number (PRD Q-1); no "
        "module, benchmark or demo path depends on the answer."
    )
    return 0


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------

def _sequence_frames(sequence: str) -> list[str]:
    from avr25d.io.kitti import KittiSequence

    seq = KittiSequence(REPO / "model" / "data" / "kitti", sequence)
    return [seq[i].frame_id for i in range(len(seq))]


def _class_histogram(sequence: str, stride: int) -> list[int]:
    from avr25d.io.kitti import KittiSequence
    from avr25d.perception import labelmap

    seq = KittiSequence(REPO / "model" / "data" / "kitti", sequence)
    hist = np.zeros(5, dtype=np.int64)
    for i in range(0, len(seq), stride):
        hist += np.bincount(seq[i].avr_label, minlength=5)[:5]
    return hist.tolist()


def split(args) -> int:
    """Assemble and write the 5-class fine-tuning split (Day 9)."""
    from avr25d.perception import labelmap

    train = {s: _sequence_frames(s) for s in TRAIN_SEQUENCES}
    val = {VAL_SEQUENCE: _sequence_frames(VAL_SEQUENCE)}

    overlap = set().union(*train.values()) & set(val[VAL_SEQUENCE])
    # Frame ids repeat across sequences ("000000" exists in all three), so the
    # meaningful uniqueness check is on the qualified id, not the bare one.
    qualified_train = {f"{s}/{f}" for s, fs in train.items() for f in fs}
    qualified_val = {f"{VAL_SEQUENCE}/{f}" for f in val[VAL_SEQUENCE]}
    assert not (qualified_train & qualified_val), "train/val leak"

    print("counting class frequencies (every 5th scan)...")
    hist_train = np.zeros(5, dtype=np.int64)
    for s in TRAIN_SEQUENCES:
        hist_train += np.asarray(_class_histogram(s, args.hist_stride))
    hist_val = np.asarray(_class_histogram(VAL_SEQUENCE, args.hist_stride))

    # Inverse-frequency loss weights over the four real classes.  VOID is the
    # ignore class and gets weight 0 rather than a large one: it is 'unlabelled',
    # not a thing to predict, and weighting it up teaches the network to
    # predict "I don't know" on exactly the points §11.3 scores.
    freq = hist_train[1:] / max(hist_train[1:].sum(), 1)
    weights = 1.0 / (freq + args.weight_eps)
    weights = weights / weights.mean()

    doc = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "taxonomy": {
            "n_classes": 5,
            "names": list(labelmap.CLASS_NAMES),
            "ignore_index": int(labelmap.VOID),
        },
        "policy": (
            "sequence-level split: KITTI is a 10 Hz recording, so consecutive "
            "frames are near-duplicates and a random frame split leaks the "
            "validation set into training. Validating on a sequence never "
            "trained on is the only split that measures generalisation."
        ),
        "train": {
            "sequences": list(TRAIN_SEQUENCES),
            "n_frames": sum(len(v) for v in train.values()),
            "frames": {s: train[s] for s in TRAIN_SEQUENCES},
            "class_points_sampled": hist_train.tolist(),
        },
        "val": {
            "sequences": [VAL_SEQUENCE],
            "n_frames": len(val[VAL_SEQUENCE]),
            "frames": val,
            "class_points_sampled": hist_val.tolist(),
            "note": (
                "sequence 04 is the sequence §11.3 reports in full, so before "
                "and after are measured on the scans the deck already quotes"
            ),
        },
        "loss_weights": [0.0] + [round(float(w), 4) for w in weights],
        "hist_stride": args.hist_stride,
    }
    SPLIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_PATH.write_text(json.dumps(doc, indent=2) + "\n")

    print(f"\ntrain {doc['train']['n_frames']} frames over "
          f"{', '.join(TRAIN_SEQUENCES)}")
    print(f"val   {doc['val']['n_frames']} frames over {VAL_SEQUENCE}")
    print(f"{'class':<24} {'train pts':>14} {'share':>8} {'weight':>8}")
    for i, name in enumerate(labelmap.CLASS_NAMES):
        share = hist_train[i] / max(hist_train.sum(), 1)
        w = doc["loss_weights"][i]
        print(f"{name:<24} {hist_train[i]:>14,} {share:>7.2%} {w:>8.3f}")
    print(f"\nwrote {SPLIT_PATH.relative_to(REPO)}")
    return 0


# ---------------------------------------------------------------------------
# Model surgery
# ---------------------------------------------------------------------------

def _build_5class_model(device):
    """Pretrained SqueezeSegV2 with a 5-output head, backbone frozen."""
    import torch
    import torch.nn as nn
    from export_onnx import load_checkpoint

    from avr25d.perception import labelmap

    model, arch = load_checkpoint(REPO / "model" / "data" / "checkpoints" / "squeezesegV2")

    old = model.head[1]                       # Conv2d(last, 20, 3, padding=1)
    new = nn.Conv2d(old.in_channels, 5, kernel_size=3, stride=1, padding=1)
    with torch.no_grad():
        # Initialise each AVR class from the mean of the learning ids that map
        # into it, so the network starts at the merge the pipeline already
        # performs instead of at random.
        for avr in range(5):
            members = np.flatnonzero(labelmap.LEARNING_TO_AVR == avr)
            if members.size == 0:
                continue
            idx = torch.as_tensor(members, dtype=torch.long)
            new.weight[avr] = old.weight[idx].mean(dim=0)
            new.bias[avr] = old.bias[idx].mean()
    model.head[1] = new

    for p in model.backbone.parameters():
        p.requires_grad = False

    return model.to(device), arch


def _freeze_backbone_bn(model):
    """BatchNorm in the frozen backbone must be in eval mode.

    ``requires_grad = False`` stops the affine parameters learning; it does
    *nothing* to the running mean and variance, which keep updating on every
    forward pass in training mode.  The pretrained features then drift on the
    new data while the loss curve looks perfectly healthy.
    """
    import torch.nn as nn

    for m in model.backbone.modules():
        if isinstance(m, nn.modules.batchnorm._BatchNorm):
            m.eval()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _frame_tensors(scan, h, w, fov_up, fov_down):
    """One scan -> (net_in float32[5,h,w], target int64[h,w])."""
    from avr25d.perception.range_proj import to_range_image

    proj = to_range_image(scan.xyz, scan.intensity, h=h, w=w,
                          fov_up=fov_up, fov_down=fov_down)
    net_in = proj.normalised()[0]

    # The label image is filled in the same farthest-first order the range
    # image uses, so the pixel's label belongs to the point whose range the
    # pixel carries.  Any other order silently pairs a near point's range with
    # a far point's class.
    target = np.zeros((h, w), dtype=np.int64)
    order = np.argsort(-proj.point_range, kind="stable")
    target[proj.py[order], proj.px[order]] = scan.avr_label[order]
    return net_in, target, proj


def _iter_split(section: str, doc: dict, limit: int | None = None):
    from avr25d.io.kitti import KittiSequence

    root = REPO / "model" / "data" / "kitti"
    for seq_name in doc[section]["sequences"]:
        seq = KittiSequence(root, seq_name, limit=limit)
        for i in range(len(seq)):
            yield seq_name, seq[i]


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train(args) -> int:
    import torch
    import torch.nn as nn

    doc = json.loads(SPLIT_PATH.read_text())
    device = torch.device(args.device or _best_device())
    print(f"device {device}")

    model, arch = _build_5class_model(device)
    sensor = arch["dataset"]["sensor"]
    h, w = int(sensor["img_prop"]["height"]), int(sensor["img_prop"]["width"])
    fov_up, fov_down = float(sensor["fov_up"]), float(sensor["fov_down"])
    print(f"range image {h}x{w}, fov {fov_down}..{fov_up} deg")

    trainable = [p for p in model.parameters() if p.requires_grad]
    n_train = sum(p.numel() for p in trainable)
    n_total = sum(p.numel() for p in model.parameters())
    print(f"training {n_train:,} of {n_total:,} parameters "
          f"({n_train / n_total:.0%}) — backbone frozen")

    if args.uniform_weights:
        # The inverse-frequency weights optimise recall on the rare classes by
        # construction.  Running the same schedule with uniform weights is what
        # separates "fine-tuning does not help" from "this loss did not target
        # mIoU" — without it the comparison has one point and invites the
        # question.
        loss_weights = [0.0] + [1.0] * 4
    else:
        loss_weights = doc["loss_weights"]
    weights = torch.tensor(loss_weights, dtype=torch.float32, device=device)
    criterion = nn.CrossEntropyLoss(weight=weights, ignore_index=0)
    opt = torch.optim.Adam(trainable, lr=args.lr)

    frames = list(_iter_split("train", doc, limit=args.limit))
    print(f"{len(frames)} training scans, {args.epochs} epoch(s)")

    rng = np.random.default_rng(args.seed)
    model.train()
    _freeze_backbone_bn(model)

    for epoch in range(args.epochs):
        order = rng.permutation(len(frames))
        running, seen, t0 = 0.0, 0, time.perf_counter()
        for step, idx in enumerate(order, 1):
            _, scan = frames[idx]
            net_in, target, _ = _frame_tensors(scan, h, w, fov_up, fov_down)
            x = torch.from_numpy(net_in).unsqueeze(0).to(device)
            y = torch.from_numpy(target).unsqueeze(0).to(device)

            opt.zero_grad(set_to_none=True)
            loss = criterion(model(x), y)
            loss.backward()
            opt.step()

            running += float(loss.detach())
            seen += 1
            if step % 25 == 0 or step == len(order):
                rate = seen / (time.perf_counter() - t0)
                print(f"  epoch {epoch + 1}/{args.epochs}  {step}/{len(order)}  "
                      f"loss {running / seen:.4f}  {rate:.1f} scan/s", flush=True)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": model.state_dict(),
        "arch": arch,
        "n_classes": 5,
        "epochs": args.epochs,
        "lr": args.lr,
        "seed": args.seed,
        "train_sequences": list(TRAIN_SEQUENCES),
        "loss_weights": loss_weights,
        "weighting": "uniform" if args.uniform_weights else "inverse-frequency",
    }, _tagged(WEIGHTS_PATH, args.tag))
    print(f"wrote {_tagged(WEIGHTS_PATH, args.tag).relative_to(REPO)}")
    return 0


def _best_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ---------------------------------------------------------------------------
# Evaluate — before vs after, through the production path
# ---------------------------------------------------------------------------

def _score(predict, doc, limit, label) -> dict:
    """Run ``predict(scan) -> per-point AVR labels`` over val and score it."""
    from avr25d.bench import distance_bins

    acc = distance_bins.BinnedAccumulator()
    recall = distance_bins.RecallAccumulator()
    n = 0
    for _, scan in _iter_split("val", doc, limit=limit):
        pred = predict(scan)
        acc.add(pred, scan.avr_label, scan.xyz)
        recall.add(pred, scan.avr_label, scan.instance, scan.xyz)
        n += 1
        if n % 25 == 0:
            print(f"  {label}: {n}", end="\r", flush=True)
    print()
    return {"n_scans": n, "accuracy": acc.result(), "object_recall": recall.result()}


def evaluate(args) -> int:
    import torch

    from avr25d import load_config
    from avr25d.perception import labelmap
    from avr25d.perception.onnx_infer import OnnxSegmenter
    from avr25d.perception.range_proj import from_range_image, to_range_image

    doc = json.loads(SPLIT_PATH.read_text())
    cfg = load_config()
    knn = {k: getattr(cfg.perception.knn, k) for k in ("k", "search", "cutoff", "sigma")}

    print("BEFORE — pretrained 20-class network, merged by labelmap")
    onnx_path = REPO / "model" / str(cfg.perception.model)
    onnx = OnnxSegmenter(onnx_path, cfg=cfg)
    before = _score(lambda scan: onnx(scan.xyz, scan.intensity),
                    doc, args.limit, "before")

    print("AFTER — fine-tuned 5-class head")
    ckpt = torch.load(_tagged(WEIGHTS_PATH, args.tag), map_location="cpu",
                      weights_only=False)
    device = torch.device(args.device or _best_device())
    model, arch = _build_5class_model(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    sensor = arch["dataset"]["sensor"]
    h, w = int(sensor["img_prop"]["height"]), int(sensor["img_prop"]["width"])
    fov_up, fov_down = float(sensor["fov_up"]), float(sensor["fov_down"])

    def predict(scan):
        proj = to_range_image(scan.xyz, scan.intensity, h=h, w=w,
                              fov_up=fov_up, fov_down=fov_down)
        with torch.no_grad():
            x = torch.from_numpy(proj.normalised()).to(device)
            pred = model(x).argmax(dim=1)[0].to("cpu").numpy().astype(np.int64)
        # Same k-NN reprojection the production path uses, so the two numbers
        # are measured through the same pipeline rather than one of them
        # skipping the step where labels move back onto points.
        return from_range_image(pred, proj.px, proj.py, scan.xyz,
                                proj_range=proj.proj_range, **knn)

    after = _score(predict, doc, args.limit, "after")

    def _overall(block):
        o = block["accuracy"]["overall"]
        r = block["object_recall"]["overall"]
        return o["miou"], o["accuracy"], r["recall"]

    b_miou, b_acc, b_rec = _overall(before)
    a_miou, a_acc, a_rec = _overall(after)

    report = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "val_sequence": VAL_SEQUENCE,
        "train_sequences": list(TRAIN_SEQUENCES),
        "n_val_scans": after["n_scans"],
        "before": before,
        "after": after,
        "delta": {
            "miou": round(a_miou - b_miou, 6),
            "point_accuracy": round(a_acc - b_acc, 6),
            "object_recall": round(a_rec - b_rec, 6),
        },
        "training": {k: ckpt[k] for k in ("epochs", "lr", "seed", "weighting")},
        "note": (
            "before is the pretrained 20-class network merged to 5 by "
            "labelmap; after is the same backbone with a fine-tuned decoder "
            "and a 5-output head. Both are scored on sequence 04, which "
            "neither was trained on, through the identical projection, "
            "inference and k-NN reprojection path."
        ),
    }
    _tagged(REPORT_PATH, args.tag).write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n{'':<18}{'before':>10}{'after':>10}{'delta':>10}")
    for name, b, a in (("mIoU", b_miou, a_miou),
                       ("point accuracy", b_acc, a_acc),
                       ("object recall", b_rec, a_rec)):
        print(f"{name:<18}{b:>10.4f}{a:>10.4f}{a - b:>+10.4f}")
    print("\nper class IoU:")
    bi = before["accuracy"]["overall"]["iou"]
    ai = after["accuracy"]["overall"]["iou"]
    for cname in labelmap.CLASS_NAMES:
        b, a = bi.get(cname), ai.get(cname)
        if b is None and a is None:
            continue
        bs = "—" if b is None else f"{b:.4f}"
        as_ = "—" if a is None else f"{a:.4f}"
        d = "" if (b is None or a is None) else f"{a - b:+.4f}"
        print(f"  {cname:<24}{bs:>10}{as_:>10}{d:>10}")
    print(f"\nwrote {_tagged(REPORT_PATH, args.tag).relative_to(REPO)}")
    return 0


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tools/finetune.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="Q-1: what compute is here").set_defaults(fn=probe)

    sp = sub.add_parser("split", help="assemble the 5-class split")
    sp.add_argument("--hist-stride", type=int, default=5)
    sp.add_argument("--weight-eps", type=float, default=0.02)
    sp.set_defaults(fn=split)

    tr = sub.add_parser("train", help="decoder + head fine-tune")
    tr.add_argument("--epochs", type=int, default=1)
    tr.add_argument("--limit", type=int, default=None)
    tr.add_argument("--lr", type=float, default=1e-3)
    tr.add_argument("--seed", type=int, default=20260906)
    tr.add_argument("--device", default=None)
    tr.add_argument("--uniform-weights", action="store_true",
                    help="train with uniform class weights instead of the "
                         "split's inverse-frequency ones")
    tr.add_argument("--tag", default="",
                    help="suffix for the weights file, so variants coexist")
    tr.set_defaults(fn=train)

    ev = sub.add_parser("evaluate", help="before/after mIoU on the val split")
    ev.add_argument("--limit", type=int, default=None)
    ev.add_argument("--device", default=None)
    ev.add_argument("--tag", default="", help="which trained variant to score")
    ev.set_defaults(fn=evaluate)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
