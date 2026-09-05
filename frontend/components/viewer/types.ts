// types.ts — the wire shapes the viewer consumes.
//
// These mirror avr25d/server/protocol.py exactly. Navya's lib/protocol.ts
// decodes the binary payload into this shape; the viewer only reads it.
//
// NOTE: the wire carries `ring` and `bin`, NOT cell centres or extents.
// Geometry is derived locally — see ringGeometry.ts.

export interface CellArrays {
  n: number;
  cell_id: Uint32Array;
  ring: Uint16Array;
  bin: Uint16Array;
  z_ground: Float32Array;
  z_obstacle: Float32Array;
  roughness: Float32Array;
  slope: Float32Array;
  class_id: Uint8Array;
  confidence: Uint8Array;
  flags: Uint8Array;
}

export interface FrameStats {
  [key: string]: number | string;
}

export interface Track {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  class_id: number;
  age: number;
  speed: number;
  /** Future positions, [[x, y], ...] — the tracker's forward projection. */
  predicted: number[][];
}

export interface Decision {
  route: number[][];
  alternative: number[][];
  selected: 'primary' | 'alternative' | string;
  risk: 'LOW' | 'MEDIUM' | 'HIGH' | string;
  eta_s: number;
  reason: string;
}

export interface FrameMessage {
  frame_id: number;
  t_sec: number;
  mode: string;
  cells: CellArrays;
  refined?: unknown;
  tracks?: Track[];
  decision?: Decision;
  stats?: FrameStats;
}
