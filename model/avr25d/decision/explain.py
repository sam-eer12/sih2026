"""Deterministic decision explanation strings.  FR-23, FR-24.
IMPLEMENTATION_PLAN §6.10, Tests T-D5, T-D6.

Owner: Anuj

No LLM (NG-5).  Same input → same string, always.  Re-running the pipeline
on the same recorded scan sequence must produce byte-identical reason strings.

Four templates, keyed on the dominant deciding factor:

    DYNAMIC_BLOCK  — a tracked object is predicted to intersect the primary route
    CLEARANCE      — overhead clearance below vehicle height on the primary route
    NEGATIVE_OBS   — a pothole/negative obstacle blocks the primary route
    TERRAIN        — no threat; primary route selected on terrain quality alone
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..server.protocol import Track


RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True)
class DecisionContext:
    """Everything the explainer needs — assembled by the server per frame."""

    primary:     "Route"
    alternative: "Route"
    selected:    Literal["primary", "alternative"]
    risk:        RiskLevel

    # Optional fields — present when the corresponding factor was decisive
    blocking_track:     Track | None = None
    intersect_time_s:   float | None = None   # t+N s when track crosses route

    clearance_m:        float | None = None   # measured clearance
    clearance_range_m:  float | None = None   # range ahead where it occurs

    pothole_depth_m:    float | None = None
    pothole_range_m:    float | None = None

    mean_traversability: float = 0.91
    max_slope_deg:        float = 0.0
    horizon_s:            float = 4.0

    # Difference in route length (km) for secondary clause
    extra_km:             float = 0.0


def _extra_clause(ctx: DecisionContext) -> str:
    """Secondary clause appended to reroute strings."""
    if ctx.extra_km > 0.005:
        return f" Alternative adds {ctx.extra_km:.1f} km at {ctx.alternative.risk} terrain risk."
    return f" Alternative at {ctx.alternative.risk} terrain risk."


def explain(ctx: DecisionContext) -> str:
    """Return a deterministic, non-empty reason string.  FR-23.

    The dominant factor is chosen in priority order:
      1. Dynamic block (track predicted on route)
      2. Clearance hazard
      3. Negative obstacle
      4. Terrain / nominal

    Parameters
    ----------
    ctx : DecisionContext

    Returns
    -------
    str — never empty, never contains unformatted placeholders.
    """
    # ── 1. Dynamic block ──────────────────────────────────────────────────
    if ctx.blocking_track is not None and ctx.intersect_time_s is not None:
        t  = ctx.blocking_track
        cls_name = "DYNAMIC_OBJECT"
        v  = t.speed
        dt = ctx.intersect_time_s
        return (
            f"Rerouted: track #{t.id} ({cls_name}, {v:.1f} m/s) predicted to "
            f"intersect primary route at t+{dt:.1f} s."
            + _extra_clause(ctx)
        )

    # ── 2. Clearance hazard ────────────────────────────────────────────────
    if ctx.clearance_m is not None and ctx.clearance_range_m is not None:
        from .. import load_config
        try:
            _cfg = load_config()
            h_v = float(_cfg.vehicle.height)
        except Exception:
            h_v = 3.50
        return (
            f"Primary route blocked: overhead clearance {ctx.clearance_m:.2f} m "
            f"below vehicle height {h_v:.2f} m at "
            f"{ctx.clearance_range_m:.0f} m ahead."
            + _extra_clause(ctx)
        )

    # ── 3. Negative obstacle ───────────────────────────────────────────────
    if ctx.pothole_depth_m is not None and ctx.pothole_range_m is not None:
        return (
            f"Primary route blocked: negative obstacle depth "
            f"{ctx.pothole_depth_m:.2f} m at "
            f"{ctx.pothole_range_m:.0f} m ahead."
            + _extra_clause(ctx)
        )

    # ── 4. Nominal terrain ─────────────────────────────────────────────────
    return (
        f"Primary route selected: mean traversability "
        f"{ctx.mean_traversability:.2f}, max slope "
        f"{ctx.max_slope_deg:.1f}°, no dynamic conflicts within "
        f"{ctx.horizon_s:.0f} s."
    )


# ---------------------------------------------------------------------------
# Convenience: build a DecisionContext from pipeline outputs
# ---------------------------------------------------------------------------

def make_context(
    primary:     "Route",
    alternative: "Route",
    tracks:      list[Track],
    cfg,
) -> DecisionContext:
    """Assemble a DecisionContext from the planner and tracker outputs."""
    import numpy as np
    from .planner import Route as _Route  # noqa: F401  (ensure available)

    # Extra distance
    extra_km = round(
        max(0.0, alternative.length_m - primary.length_m) / 1000.0, 3
    )

    # Check if any track is predicted onto the primary corridor
    # (simple check: any predicted point within 2 m of a primary waypoint)
    blocking_track: Track | None = None
    intersect_time_s: float | None = None

    if tracks:
        primary_wps = np.array(primary.waypoints, dtype=np.float64)
        horizon_s = float(cfg.decision.horizon_s)
        dt_per_step = horizon_s / 5.0

        for track in tracks:
            for step_idx, pred in enumerate(track.predicted):
                px, py = float(pred[0]), float(pred[1])
                # Distance from this predicted position to any primary waypoint
                if primary_wps.size:
                    dists = np.linalg.norm(
                        primary_wps - np.array([px, py]), axis=1
                    )
                    if dists.min() < 3.0:   # within 3 m of route
                        blocking_track = track
                        intersect_time_s = round(dt_per_step * (step_idx + 1), 1)
                        break
            if blocking_track:
                break

    selected: Literal["primary", "alternative"] = (
        "alternative" if blocking_track else "primary"
    )
    risk: RiskLevel = (
        alternative.risk if selected == "alternative" else primary.risk
    )

    import numpy as np  # noqa — needed for type narrowing in this scope
    return DecisionContext(
        primary             = primary,
        alternative         = alternative,
        selected            = selected,
        risk                = risk,
        blocking_track      = blocking_track,
        intersect_time_s    = intersect_time_s,
        extra_km            = extra_km,
        horizon_s           = float(cfg.decision.horizon_s),
    )
