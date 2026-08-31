"""Range-binned accuracy and object recall.  §6.11, FR-33, FR-34.  T-B3, T-B4.

An overall mIoU hides the thing PS-6 is actually about.  A segmenter can score
well overall and be useless past 30 m, which is precisely where an adaptive
grid has to justify itself — and the Day 3 geometric run was exactly that
shape: 0.290 at 0-10 m, 0.291 at 10-30 m, 0.196 at 30-60 m, and 0.000 beyond
60 m on 1,152 points a scan.  The last number is the interesting one, and only
binning surfaces it.

Three conventions are fixed here rather than left implicit, because each one
silently moves a headline number:

**Bins are half-open upward,** ``[0,10) [10,30) [30,60) [60,100]``, with the
last closed so that a return at exactly the 100 m envelope is counted.  Every
point lands in exactly one bin or is marked ``-1`` for outside the envelope;
T-B3 asserts the partition rather than sampling it.

**Range is horizontal.**  ``sqrt(x^2 + y^2)``, matching how §3 defines the ring
radii, so a point 40 m up a building face at 20 m ground range bins at 20 m.

**mIoU excludes VOID.**  Ground-truth *unlabeled* is about 2% of KITTI points;
SemanticKITTI excludes it and so do the published 0.823 / 0.868 figures.  A
class absent from both prediction and truth scores ``NaN`` and drops out of the
mean — scoring it 0.0 would penalise the model for a class nobody asked about.
"""

from __future__ import annotations

import numpy as np

from ..perception import labelmap as lm

#: FR-33's bins, as edges.  Four bins, five edges.
BIN_EDGES_M: tuple[float, ...] = (0.0, 10.0, 30.0, 60.0, 100.0)

BIN_NAMES: tuple[str, ...] = ("0-10m", "10-30m", "30-60m", "60-100m")

#: Marker for a point outside the sensing envelope.  Not a bin.
OUTSIDE: int = -1

#: "Things", in the stuff/things sense: classes whose instances are countable
#: objects.  Road and terrain have no object identity, so object recall over
#: them is meaningless (FR-34).
OBJECT_CLASSES: tuple[int, ...] = (lm.STATIC_OBSTACLE, lm.DYNAMIC_OBJECT)

#: An object with fewer returns than this is not scored.  At 12 m a pothole
#: gets 49 returns and a distant pole can get 3; calling a 3-point object a
#: miss measures the HDL-64E's beam pitch, not the segmenter.
DEFAULT_MIN_POINTS: int = 5

#: Fraction of an object's points that must carry the right class for it to
#: count as recalled.  A majority — anything lower lets one lucky point
#: "detect" an object.
DEFAULT_HIT_FRACTION: float = 0.5


def horizontal_range(xyz: np.ndarray) -> np.ndarray:
    """``sqrt(x^2 + y^2)`` in float64, matching the §3 ring radii."""
    x = xyz[:, 0].astype(np.float64, copy=False)
    y = xyz[:, 1].astype(np.float64, copy=False)
    return np.sqrt(x * x + y * y)


def assign_bins(xyz: np.ndarray) -> np.ndarray:
    """Bin index per point, or ``OUTSIDE`` beyond the 100 m envelope.

    ``np.searchsorted(..., side="right") - 1`` gives the half-open-upward
    convention directly, so there is no chain of comparisons to get subtly
    wrong at a boundary.
    """
    r = horizontal_range(xyz)
    idx = np.searchsorted(np.asarray(BIN_EDGES_M), r, side="right") - 1
    idx = idx.astype(np.int64)
    # r exactly at the final edge lands one past the last bin; pull it back so
    # the envelope is closed.
    idx[r == BIN_EDGES_M[-1]] = len(BIN_NAMES) - 1
    idx[(r < BIN_EDGES_M[0]) | (r > BIN_EDGES_M[-1])] = OUTSIDE
    return idx


# --- confusion, IoU, mIoU --------------------------------------------------

def confusion(
    truth: np.ndarray, pred: np.ndarray, n_classes: int = lm.N_CLASSES
) -> np.ndarray:
    """``cm[t, p]`` — ground-truth class ``t`` predicted as ``p``."""
    t = np.asarray(truth, dtype=np.int64).ravel()
    p = np.asarray(pred, dtype=np.int64).ravel()
    if t.shape != p.shape:
        raise ValueError(f"truth {t.shape} and prediction {p.shape} differ in length")
    flat = np.bincount(t * n_classes + p, minlength=n_classes * n_classes)
    return flat.reshape(n_classes, n_classes)


def iou_per_class(cm: np.ndarray) -> np.ndarray:
    """Per-class IoU, ``NaN`` where the class appears in neither truth nor
    prediction.  ``TP / (TP + FP + FN)``."""
    tp = np.diag(cm).astype(np.float64)
    union = cm.sum(axis=1) + cm.sum(axis=0) - tp
    with np.errstate(invalid="ignore", divide="ignore"):
        iou = np.where(union > 0, tp / union, np.nan)
    return iou


def drop_excluded_truth(cm: np.ndarray, exclude: tuple[int, ...]) -> np.ndarray:
    """Zero the ground-truth rows of excluded classes.

    Excluding VOID from the *mean* is not enough, and the difference is not
    cosmetic: a point whose ground truth is *unlabeled* but which the model
    called DRIVABLE would still count as a false positive against DRIVABLE and
    depress its IoU for a point nobody was ever asked to classify.  Dropping
    the row removes those points from the evaluation entirely, which is what
    "SemanticKITTI excludes unlabeled" actually means.

    Deliberately **not** symmetric: the excluded *column* stays.  Predicting
    VOID on a genuinely labelled point is a refusal to answer and counts as a
    false negative against the real class.  The network never predicts VOID so
    this is moot for it, but the geometric segmenter can, and forgiving it
    would flatter the weaker of the two baselines.
    """
    cm = cm.copy()
    for c in exclude:
        cm[c, :] = 0
    return cm


def miou(cm: np.ndarray, exclude: tuple[int, ...] = (lm.VOID,)) -> float:
    """Mean IoU over the classes that are present, VOID excluded by default."""
    iou = iou_per_class(drop_excluded_truth(cm, exclude))
    keep = np.ones(iou.size, dtype=bool)
    for c in exclude:
        keep[c] = False
    vals = iou[keep]
    vals = vals[~np.isnan(vals)]
    return float(vals.mean()) if vals.size else float("nan")


def _accuracy(cm: np.ndarray, exclude: tuple[int, ...] = (lm.VOID,)) -> float:
    """Point accuracy over the same points mIoU scores, for consistency."""
    scored = drop_excluded_truth(cm, exclude)
    total = scored.sum()
    return float(np.diag(scored).sum() / total) if total else float("nan")


def _nan_to_none(x: float) -> float | None:
    """``results.json`` carries ``null`` for undefined, never a silent 0.0."""
    return None if x is None or np.isnan(x) else round(float(x), 6)


def _score_block(cm: np.ndarray, exclude: tuple[int, ...]) -> dict:
    n = int(cm.sum())
    scored = drop_excluded_truth(cm, exclude)
    iou = iou_per_class(scored)
    return {
        # n_points is every point in the bin, so the bins still sum to the
        # scan (T-B3); n_points_scored is what the metrics were computed over,
        # which is smaller wherever ground-truth VOID was present.
        "n_points": n,
        "n_points_scored": int(scored.sum()),
        "miou": _nan_to_none(miou(cm, exclude=exclude)) if n else None,
        "accuracy": _nan_to_none(_accuracy(cm, exclude=exclude)) if n else None,
        "iou": {
            lm.CLASS_NAMES[c]: _nan_to_none(iou[c]) for c in range(lm.N_CLASSES)
        },
        "truth_share": {
            lm.CLASS_NAMES[c]: (round(float(cm[c].sum() / n), 6) if n else None)
            for c in range(lm.N_CLASSES)
        },
    }


def evaluate(
    pred: np.ndarray,
    truth: np.ndarray,
    xyz: np.ndarray,
    *,
    exclude: tuple[int, ...] = (lm.VOID,),
) -> dict:
    """Overall and per-bin accuracy for one scan or a whole sequence (FR-33)."""
    bins = assign_bins(xyz)
    inside = bins >= 0
    pred = np.asarray(pred).ravel()
    truth = np.asarray(truth).ravel()

    out = {
        "bin_edges_m": list(BIN_EDGES_M),
        "excluded_classes": [lm.CLASS_NAMES[c] for c in exclude],
        "n_points_outside_envelope": int((~inside).sum()),
        "overall": _score_block(confusion(truth[inside], pred[inside]), exclude),
        "bins": {},
    }
    for i, name in enumerate(BIN_NAMES):
        m = bins == i
        out["bins"][name] = _score_block(confusion(truth[m], pred[m]), exclude)
    return out


class BinnedAccumulator:
    """Streaming form of :func:`evaluate`, for a whole sequence.

    271 scans x 125,718 points is 34 M points; holding their coordinates to
    evaluate in one pass costs about 400 MB for no reason.  A confusion matrix
    is additive, so the harness accumulates one per bin and one overall, and
    the point arrays are freed after each scan.

    Equality with the all-at-once path is asserted in the tests, so the
    streaming route is not a second, unverified metric.
    """

    def __init__(self, exclude: tuple[int, ...] = (lm.VOID,)) -> None:
        self._exclude = exclude
        self._overall = np.zeros((lm.N_CLASSES, lm.N_CLASSES), dtype=np.int64)
        self._bins = [
            np.zeros((lm.N_CLASSES, lm.N_CLASSES), dtype=np.int64)
            for _ in BIN_NAMES
        ]
        self._outside = 0
        self.n_scans = 0

    def add(self, pred: np.ndarray, truth: np.ndarray, xyz: np.ndarray) -> None:
        """Fold one scan in."""
        bins = assign_bins(xyz)
        inside = bins >= 0
        pred = np.asarray(pred).ravel()
        truth = np.asarray(truth).ravel()

        self._overall += confusion(truth[inside], pred[inside])
        for i in range(len(BIN_NAMES)):
            m = bins == i
            if m.any():
                self._bins[i] += confusion(truth[m], pred[m])
        self._outside += int((~inside).sum())
        self.n_scans += 1

    def result(self) -> dict:
        """The same document :func:`evaluate` returns."""
        return {
            "bin_edges_m": list(BIN_EDGES_M),
            "excluded_classes": [lm.CLASS_NAMES[c] for c in self._exclude],
            "n_points_outside_envelope": self._outside,
            "overall": _score_block(self._overall, self._exclude),
            "bins": {
                name: _score_block(self._bins[i], self._exclude)
                for i, name in enumerate(BIN_NAMES)
            },
        }


# --- object recall (FR-34, T-B4) -------------------------------------------

def object_recall(
    pred: np.ndarray,
    truth: np.ndarray,
    instance: np.ndarray,
    xyz: np.ndarray,
    *,
    min_points: int = DEFAULT_MIN_POINTS,
    hit_fraction: float = DEFAULT_HIT_FRACTION,
) -> dict:
    """Fraction of ground-truth objects recovered, by range bin and by class.

    An *object* is a distinct ``(truth class, instance id)`` group in one of
    ``OBJECT_CLASSES`` with a non-zero instance id — SemanticKITTI reserves
    instance 0 for "stuff", which has no object identity to recall.  It counts
    as recalled when at least ``hit_fraction`` of its points were predicted
    with its own class, and it is binned by its **median** point range, which
    is robust to the one stray return a long vehicle can throw.
    """
    pred = np.asarray(pred).ravel()
    truth = np.asarray(truth).ravel()
    instance = np.asarray(instance).ravel()
    r = horizontal_range(xyz)
    bins = assign_bins(xyz)

    is_thing = np.isin(truth, np.asarray(OBJECT_CLASSES)) & (instance != 0)

    # (class, instance) uniquely identifies an object; instance ids are only
    # unique within a class in SemanticKITTI.
    keys = (truth.astype(np.int64) << 32) | instance.astype(np.int64)
    per_bin = {n: {"n_objects": 0, "n_recalled": 0} for n in BIN_NAMES}
    per_class = {
        lm.CLASS_NAMES[c]: {"n_objects": 0, "n_recalled": 0} for c in OBJECT_CLASSES
    }
    n_objects = n_recalled = n_small = 0

    for key in np.unique(keys[is_thing]):
        m = (keys == key) & is_thing
        n_pts = int(m.sum())
        if n_pts < min_points:
            n_small += 1
            continue
        cls = int(truth[m][0])
        hit = float((pred[m] == cls).mean()) >= hit_fraction
        n_objects += 1
        n_recalled += int(hit)

        cname = lm.CLASS_NAMES[cls]
        per_class[cname]["n_objects"] += 1
        per_class[cname]["n_recalled"] += int(hit)

        bin_idx = int(np.median(bins[m]))
        if 0 <= bin_idx < len(BIN_NAMES):
            slot = per_bin[BIN_NAMES[bin_idx]]
            slot["n_objects"] += 1
            slot["n_recalled"] += int(hit)

    return {
        "min_points": min_points,
        "hit_fraction": hit_fraction,
        "n_objects_below_min_points": n_small,
        "overall": _finish_recall({"n_objects": n_objects, "n_recalled": n_recalled}),
        "bins": {k: _finish_recall(v) for k, v in per_bin.items()},
        "classes": {k: _finish_recall(v) for k, v in per_class.items()},
    }


def _finish_recall(d: dict) -> dict:
    d = dict(d)
    d["recall"] = (
        round(d["n_recalled"] / d["n_objects"], 6) if d["n_objects"] else None
    )
    return d


class RecallAccumulator:
    """Object recall summed over a sequence (FR-34).

    Each scan is a fresh detection opportunity: the same truck at frame 10 and
    frame 11 is two chances to see it, not one. Counts therefore add rather
    than de-duplicating by instance id — which is also the only defensible
    reading when the object leaves and re-enters the field of view.
    """

    def __init__(
        self,
        *,
        min_points: int = DEFAULT_MIN_POINTS,
        hit_fraction: float = DEFAULT_HIT_FRACTION,
    ) -> None:
        self.min_points = min_points
        self.hit_fraction = hit_fraction
        self._overall = {"n_objects": 0, "n_recalled": 0}
        self._bins = {n: {"n_objects": 0, "n_recalled": 0} for n in BIN_NAMES}
        self._classes = {
            lm.CLASS_NAMES[c]: {"n_objects": 0, "n_recalled": 0}
            for c in OBJECT_CLASSES
        }
        self._small = 0
        self.n_scans = 0

    def add(
        self,
        pred: np.ndarray,
        truth: np.ndarray,
        instance: np.ndarray,
        xyz: np.ndarray,
    ) -> None:
        one = object_recall(
            pred, truth, instance, xyz,
            min_points=self.min_points, hit_fraction=self.hit_fraction,
        )
        for key in ("n_objects", "n_recalled"):
            self._overall[key] += one["overall"][key]
            for name in BIN_NAMES:
                self._bins[name][key] += one["bins"][name][key]
            for name in self._classes:
                self._classes[name][key] += one["classes"][name][key]
        self._small += one["n_objects_below_min_points"]
        self.n_scans += 1

    def result(self) -> dict:
        return {
            "min_points": self.min_points,
            "hit_fraction": self.hit_fraction,
            "n_objects_below_min_points": self._small,
            "overall": _finish_recall(self._overall),
            "bins": {k: _finish_recall(v) for k, v in self._bins.items()},
            "classes": {k: _finish_recall(v) for k, v in self._classes.items()},
        }
