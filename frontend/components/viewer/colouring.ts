// colouring.ts — the one place a cell's colour is decided.
// Shared by the instanced grid (View 3) and the point cloud (View 1) so the
// two representations can never disagree about what a cell looks like.

import * as THREE from 'three';
import {
  CLASS_ID_TO_COLOUR,
  elevationRampRGB,
  ELEVATION_RANGE,
} from '../../lib/palette';

export type ColourMode = 'class' | 'elevation';

const FALLBACK_COLOUR = 0x808080;
const SPAN = ELEVATION_RANGE.max - ELEVATION_RANGE.min;

/**
 * Write the colour for one cell into `out`.
 *
 * Both paths land in the renderer's working colour space: setHex and setRGB
 * are given SRGBColorSpace explicitly, because Three's default for setRGB is
 * the *working* space (linear) — passing sRGB values raw would wash the ramp out.
 */
export function writeCellColour(
  out: THREE.Color,
  mode: ColourMode,
  classId: number,
  zTop: number
): void {
  if (mode === 'class') {
    out.setHex(CLASS_ID_TO_COLOUR[classId] ?? FALLBACK_COLOUR, THREE.SRGBColorSpace);
    return;
  }

  // Fixed range rather than per-frame min/max: an adaptive range would make
  // the whole scene shift colour whenever one tall object enters the scan,
  // which reads as a bug from three metres away.
  const t = (zTop - ELEVATION_RANGE.min) / SPAN;
  const [r, g, b] = elevationRampRGB(t);
  out.setRGB(r, g, b, THREE.SRGBColorSpace);
}
