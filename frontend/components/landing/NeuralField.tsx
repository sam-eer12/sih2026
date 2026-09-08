// NeuralField.tsx — the connective background motif.
//
// Nodes drift; an edge is drawn between any two within a link radius, its
// opacity falling with distance. The pointer carries its own, larger radius,
// so moving through the field recruits nodes into a local cluster.
//
// This is the same idea the grid rests on — proximity decides structure — so
// it is drawn the same way rather than as generic decoration. Nothing here is
// random per frame: positions integrate, so the field has continuity.
//
// 2D canvas, not WebGL: a few hundred nodes and their edges cost less on the
// CPU than a context switch, and the hero already owns a WebGL context. Two
// contexts on one page is how a laptop starts throttling.

'use client';

import { useEffect, useRef } from 'react';

export interface NeuralFieldProps {
  className?: string;
  /** Nodes per million square pixels. Density is resolution-independent. */
  density?: number;
  /** Link radius in CSS pixels. */
  linkRadius?: number;
  colour?: string;
  accent?: string;
}

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** Phase offset so pulses are not synchronised. */
  phase: number;
}

export default function NeuralField({
  className,
  density = 90,
  linkRadius = 132,
  colour = '154, 176, 224',
  accent = '105, 240, 174',
}: NeuralFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Respect a user who has asked for less movement. The field still draws;
    // it simply stops drifting.
    const stillness = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let nodes: Node[] = [];
    let w = 0;
    let h = 0;
    let dpr = 1;

    const pointer = { x: -9999, y: -9999, active: false };
    const POINTER_RADIUS = 190;

    function seed() {
      const target = Math.round((w * h) / 1_000_000 * density);
      nodes = Array.from({ length: Math.max(24, target) }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        phase: Math.random() * Math.PI * 2,
      }));
    }

    function resize() {
      const rect = canvas!.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      dpr = Math.min(window.devicePixelRatio, 2);
      w = rect.width;
      h = rect.height;
      canvas!.width = Math.round(w * dpr);
      canvas!.height = Math.round(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    }

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    function onMove(e: PointerEvent) {
      const r = canvas!.getBoundingClientRect();
      pointer.x = e.clientX - r.left;
      pointer.y = e.clientY - r.top;
      pointer.active = true;
    }
    function onLeave() {
      pointer.active = false;
      pointer.x = -9999;
      pointer.y = -9999;
    }
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerleave', onLeave);

    let raf = 0;
    let t = 0;

    function frame() {
      raf = requestAnimationFrame(frame);
      t += 0.016;
      ctx!.clearRect(0, 0, w, h);

      // ── integrate ──────────────────────────────────────────────
      for (const nd of nodes) {
        if (!stillness) {
          nd.x += nd.vx;
          nd.y += nd.vy;
        }
        // Wrap rather than bounce: a bounce puts a visible wall at the edge.
        if (nd.x < -20) nd.x = w + 20;
        if (nd.x > w + 20) nd.x = -20;
        if (nd.y < -20) nd.y = h + 20;
        if (nd.y > h + 20) nd.y = -20;

        // Drawn toward the pointer, gently, and only within its radius.
        if (pointer.active) {
          const dx = pointer.x - nd.x;
          const dy = pointer.y - nd.y;
          const d = Math.hypot(dx, dy);
          if (d < POINTER_RADIUS && d > 1) {
            nd.x += (dx / d) * 0.42 * (1 - d / POINTER_RADIUS);
            nd.y += (dy / d) * 0.42 * (1 - d / POINTER_RADIUS);
          }
        }
      }

      // ── edges ──────────────────────────────────────────────────
      // O(n²) over a few hundred nodes is ~40k comparisons a frame, which is
      // cheaper than the allocations a spatial index would cost at this size.
      const r2 = linkRadius * linkRadius;
      ctx!.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > r2) continue;
          const alpha = (1 - Math.sqrt(d2) / linkRadius) * 0.34;
          ctx!.strokeStyle = `rgba(${colour}, ${alpha})`;
          ctx!.beginPath();
          ctx!.moveTo(a.x, a.y);
          ctx!.lineTo(b.x, b.y);
          ctx!.stroke();
        }
      }

      // ── pointer edges, drawn brighter and in the accent ────────
      if (pointer.active) {
        for (const nd of nodes) {
          const dx = pointer.x - nd.x;
          const dy = pointer.y - nd.y;
          const d = Math.hypot(dx, dy);
          if (d > POINTER_RADIUS) continue;
          const alpha = (1 - d / POINTER_RADIUS) * 0.5;
          ctx!.strokeStyle = `rgba(${accent}, ${alpha})`;
          ctx!.beginPath();
          ctx!.moveTo(pointer.x, pointer.y);
          ctx!.lineTo(nd.x, nd.y);
          ctx!.stroke();
        }
      }

      // ── nodes ──────────────────────────────────────────────────
      for (const nd of nodes) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.4 + nd.phase);
        const near =
          pointer.active && Math.hypot(pointer.x - nd.x, pointer.y - nd.y) < POINTER_RADIUS;
        const rad = 1.15 + pulse * 0.85 + (near ? 1.1 : 0);

        ctx!.beginPath();
        ctx!.arc(nd.x, nd.y, rad, 0, Math.PI * 2);
        ctx!.fillStyle = near
          ? `rgba(${accent}, ${0.55 + pulse * 0.4})`
          : `rgba(${colour}, ${0.35 + pulse * 0.35})`;
        ctx!.fill();
      }
    }
    frame();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerleave', onLeave);
    };
  }, [density, linkRadius, colour, accent]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
