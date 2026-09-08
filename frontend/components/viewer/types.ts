// types.ts — the wire shapes the viewer consumes.
//
// These are Navya's, re-exported. lib/protocol.ts owns the decode and
// therefore owns the contract; the viewer only reads it. Keeping a parallel
// set of interfaces here was how the two drifted once already — this file had
// `selected: 'primary' | 'alternative' | string` and optional `tracks`, which
// quietly permitted frames the real stream never sends.
//
// The indirection stays so viewer modules import from one place, and so the
// ownership boundary is visible: everything below is defined elsewhere.

export type {
  CellArrays,
  RefinedArrays,
  Track,
  Decision,
  FrameStats,
  FrameMessage,
} from '../../lib/protocol';
