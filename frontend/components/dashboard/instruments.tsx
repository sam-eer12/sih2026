// instruments.tsx — the readout primitives.
//
// Every value drawn here comes from a real frame: `stats` off the wire, the
// viewer's own `perf`/`uniform` getters, or the planner's decision and tracks.
// Nothing is synthesised. Histories are the real sampled values buffered
// client-side so a trend can be seen — the samples themselves are unmodified.
//
// SVG rather than a charting library: these are small, fixed-purpose readouts
// and a dependency would cost more than the forty lines it replaced.
'use client';

import { useEffect, useRef, useState } from 'react';

export const LIDAR = '#22d3ee';    // cyan — sensor returns
export const ADAPTIVE = '#a78bfa'; // violet — adaptive processing
export const OK = '#34d399';
export const WARN = '#fbbf24';
export const RISK = '#f87171';

/**
 * A bounded history of one real field, sampled on its own timer.
 *
 * The append happens inside the interval callback rather than during render or
 * synchronously in an effect body — both of which are the wrong place to
 * mutate, and the linter is right to say so. Fixed length, so the buffer
 * cannot grow without bound over a long session.
 *
 * `select` must be defined at module scope: a fresh function identity every
 * render would tear down and rebuild the interval four times a second.
 */
export function useSeries<T>(
  sample: () => T | null,
  select: (snapshot: T) => number | undefined,
  hz = 4,
  length = 64
): number[] {
  const [series, setSeries] = useState<number[]>([]);
  useEffect(() => {
    const id = window.setInterval(() => {
      const snapshot = sample();
      if (!snapshot) return;
      const value = select(snapshot);
      if (typeof value !== 'number' || !Number.isFinite(value)) return;
      setSeries((prev) => (prev.length >= length ? [...prev.slice(1), value] : [...prev, value]));
    }, 1000 / hz);
    return () => window.clearInterval(id);
  }, [sample, select, hz, length]);
  return series;
}

/* ── Sparkline ───────────────────────────────────────────────────────── */

export function Sparkline({
  values,
  colour,
  height = 30,
  max,
}: {
  values: number[];
  colour: string;
  height?: number;
  max?: number;
}) {
  if (values.length < 2) {
    return <div style={{ height }} className="w-full" />;
  }
  const hi = max ?? Math.max(...values, 1);
  const w = 100;
  const step = w / (values.length - 1);
  const y = (v: number) => height - (Math.min(v, hi) / hi) * (height - 2) - 1;

  const line = values.map((v, i) => `${i * step},${y(v)}`).join(' ');
  const area = `0,${height} ${line} ${w},${height}`;
  const id = `spark-${colour.replace('#', '')}`;

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={colour} stopOpacity="0.28" />
          <stop offset="100%" stopColor={colour} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${id})`} />
      <polyline
        points={line}
        fill="none"
        stroke={colour}
        strokeWidth="1.2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/* ── Stacked stage bar ───────────────────────────────────────────────── */

export function StageBar({
  stages,
  budgetMs,
}: {
  stages: { label: string; ms: number; colour: string }[];
  budgetMs: number;
}) {
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-white/5">
      {stages.map((s) => (
        <span
          key={s.label}
          title={`${s.label} ${s.ms.toFixed(2)} ms`}
          className="h-full transition-[width] duration-500 ease-out"
          style={{
            width: `${Math.min((s.ms / budgetMs) * 100, 100)}%`,
            background: s.colour,
          }}
        />
      ))}
    </div>
  );
}

/* ── Arc gauge ───────────────────────────────────────────────────────── */

export function Arc({
  fraction,
  colour,
  size = 62,
  children,
}: {
  fraction: number;
  colour: string;
  size?: number;
  children?: React.ReactNode;
}) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(fraction) ? fraction : 0));
  const r = 26;
  const circ = Math.PI * r; // half circle
  return (
    <div className="relative" style={{ width: size, height: size * 0.62 }}>
      <svg viewBox="0 0 64 36" className="w-full" aria-hidden="true">
        <path
          d={`M 6 32 A ${r} ${r} 0 0 1 58 32`}
          fill="none"
          stroke="currentColor"
          className="text-white/8"
          strokeWidth="4"
          strokeLinecap="round"
        />
        <path
          d={`M 6 32 A ${r} ${r} 0 0 1 58 32`}
          fill="none"
          stroke={colour}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - clamped)}
          style={{ transition: 'stroke-dashoffset 600ms cubic-bezier(0.16,1,0.3,1)' }}
        />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center">{children}</div>
    </div>
  );
}

/* ── Plan view ───────────────────────────────────────────────────────────
   Top-down plot of the real track positions and the real route polyline, in
   the sensor frame. Drawn to a canvas because it redraws on every sample and
   a canvas costs less than replacing a few hundred SVG nodes. */

export interface PlanTrack { id: number; x: number; y: number; colour: string }

export function PlanView({
  tracks,
  route,
  alternative,
  extentM = 45,
}: {
  tracks: PlanTrack[];
  route?: number[][];
  alternative?: number[][];
  extentM?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(rect.width, 1);
    const h = Math.max(rect.height, 1);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;
    const scale = Math.min(w, h) / 2 / extentM;
    // Sensor frame: x forward, y left. Screen: x right, y down.
    const px = (x: number, y: number): [number, number] => [cx - y * scale, cy - x * scale];

    // Range rings, so a distance can be read off the plot.
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth = 1;
    for (const ring of [15, 30, 45]) {
      if (ring > extentM) continue;
      ctx.beginPath();
      ctx.arc(cx, cy, ring * scale, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
    ctx.moveTo(0, cy); ctx.lineTo(w, cy);
    ctx.stroke();

    const path = (pts: number[][] | undefined, colour: string, dash: number[]) => {
      if (!pts || pts.length < 2) return;
      ctx.save();
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1.6;
      ctx.setLineDash(dash);
      ctx.beginPath();
      pts.forEach((p, i) => {
        const [sx, sy] = px(p[0], p[1]);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
      });
      ctx.stroke();
      ctx.restore();
    };
    path(alternative, 'rgba(167,139,250,0.55)', [3, 3]);
    path(route, ADAPTIVE, []);

    // Ego marker.
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.beginPath();
    ctx.moveTo(cx, cy - 5); ctx.lineTo(cx - 3.5, cy + 4); ctx.lineTo(cx + 3.5, cy + 4);
    ctx.closePath();
    ctx.fill();

    for (const t of tracks) {
      const [sx, sy] = px(t.x, t.y);
      ctx.fillStyle = t.colour;
      ctx.beginPath();
      ctx.arc(sx, sy, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = t.colour;
      ctx.globalAlpha = 0.28;
      ctx.beginPath();
      ctx.arc(sx, sy, 7, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }, [tracks, route, alternative, extentM]);

  return <canvas ref={ref} className="h-[104px] w-full" aria-label="Top-down track and route plot" />;
}
