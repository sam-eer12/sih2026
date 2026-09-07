// protocol.ts — binary FrameMessage decode. Mirrors avr25d/server/protocol.py,
// which is FROZEN. If this file and that one disagree, this one is wrong.
//
// Wire layout (little-endian):
//   [4 bytes]           header_len — uint32
//   [header_len bytes]  UTF-8 JSON header; typed-array fields carry a sentinel
//                       string such as "uint32[41990]" in place of their data
//   [payload bytes...]  the typed arrays themselves, in declaration order:
//                         cells:   cell_id u32, ring u16, bin u16, z_ground f32,
//                                  z_obstacle f32, roughness f32, slope f32,
//                                  class_id u8, confidence u8, flags u8
//                         refined: parent_id u32, quadrant u8, z_ground f32,
//                                  z_obstacle f32, class_id u8, flags u8
//
// tracks, decision and stats live entirely in the JSON header — they are small
// and JSON.parse is not on the hot path.
//
// ── On "zero copies" ──────────────────────────────────────────────────────
// IMPLEMENTATION_PLAN.md §6.14 describes this decode as zero-copy. It cannot
// be, and the reason is arithmetic rather than opinion: a typed-array view
// needs its byte offset to be a multiple of its element size, the payload
// begins at 4 + header_len, and header_len is whatever the JSON happened to
// weigh. Measured against the live fixture server the payload starts at byte
// 1122 — 1122 % 4 == 2 — so a direct Uint32Array view over the received buffer
// throws RangeError on the very first frame, every frame.
//
// So the payload is copied once, contiguously, into its own ArrayBuffer. From
// offset 0 the cell arrays are self-aligning: cell_id at 0, ring at 4n, bin at
// 6n, the four float32 fields at 8n/12n/16n/20n — every offset a multiple of
// its element size for any n. Only `refined` can still land badly, because the
// cells block is 27n bytes and 27n % 4 == 0 only when n % 4 == 0; alignedView
// absorbs that case with a second, much smaller copy.
//
// One 1.1 MB memcpy per frame is far cheaper than the ~42,000 per-cell matrix
// writes the viewer already does downstream, and it is the only correct option
// without padding the frozen header. Raised with Anuj — see docs/progress/navya.md.

// ── Wire shapes ───────────────────────────────────────────────────────────
// These mirror the dataclasses in protocol.py. CellArrays is structurally
// identical to components/viewer/types.ts so the viewer consumes what this
// returns without a cast and without Shubham changing a line.

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

/** Sub-cell overlay for far-field cells that were refined 2x2 (FR-17). */
export interface RefinedArrays {
  n: number;
  parent_id: Uint32Array;
  quadrant: Uint8Array;
  z_ground: Float32Array;
  z_obstacle: Float32Array;
  class_id: Uint8Array;
  flags: Uint8Array;
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
  /** Predicted future positions as [x, y] pairs. */
  predicted: number[][];
}

export interface Decision {
  route: number[][];
  alternative: number[][];
  selected: 'primary' | 'alternative';
  risk: 'LOW' | 'MEDIUM' | 'HIGH';
  eta_s: number;
  reason: string;
}

// A type alias, deliberately, NOT an interface. components/viewer/types.ts
// types stats as { [key: string]: number | string }, and TypeScript only gives
// implicit index signatures to type aliases — an interface would fail to
// satisfy it and the viewer would stop accepting decoded frames.
export type FrameStats = {
  fps: number;
  t_perception_ms: number;
  t_projection_ms: number;
  t_analysis_ms: number;
  t_refine_ms: number;
  t_decision_ms: number;
  t_serialise_ms: number;
  t_total_ms: number;
  n_points: number;
  /** FR-10: must equal n_points on every frame. */
  n_points_conserved: number;
  n_cells_occupied: number;
  n_cells_total: number;
  mem_bytes: number;
  baseline_mem_bytes: number;
  reduction: number;
};

export interface FrameMessage {
  frame_id: number;
  t_sec: number;
  /** FR-6 perception mode: "live" | "cached" | "geometric". */
  mode: string;
  cells: CellArrays;
  refined: RefinedArrays;
  tracks: Track[];
  decision: Decision;
  stats: FrameStats;
}

export class ProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProtocolError';
  }
}

// ── Field tables — order is the wire contract ─────────────────────────────

type Ctor =
  | Uint32ArrayConstructor
  | Uint16ArrayConstructor
  | Uint8ArrayConstructor
  | Float32ArrayConstructor;

/** numpy dtype name -> the view constructor, for validating the sentinels. */
const CELL_FIELDS: ReadonlyArray<readonly [keyof CellArrays, Ctor, string]> = [
  ['cell_id', Uint32Array, 'uint32'],
  ['ring', Uint16Array, 'uint16'],
  ['bin', Uint16Array, 'uint16'],
  ['z_ground', Float32Array, 'float32'],
  ['z_obstacle', Float32Array, 'float32'],
  ['roughness', Float32Array, 'float32'],
  ['slope', Float32Array, 'float32'],
  ['class_id', Uint8Array, 'uint8'],
  ['confidence', Uint8Array, 'uint8'],
  ['flags', Uint8Array, 'uint8'],
] as const;

const REFINED_FIELDS: ReadonlyArray<readonly [keyof RefinedArrays, Ctor, string]> = [
  ['parent_id', Uint32Array, 'uint32'],
  ['quadrant', Uint8Array, 'uint8'],
  ['z_ground', Float32Array, 'float32'],
  ['z_obstacle', Float32Array, 'float32'],
  ['class_id', Uint8Array, 'uint8'],
  ['flags', Uint8Array, 'uint8'],
] as const;

/** Bytes one cell occupies across all ten arrays — 27. */
const CELL_STRIDE = CELL_FIELDS.reduce((s, [, C]) => s + C.BYTES_PER_ELEMENT, 0);
/** Bytes one refined sub-cell occupies — 15 (4+1+4+4+1+1). */
const REFINED_STRIDE = REFINED_FIELDS.reduce((s, [, C]) => s + C.BYTES_PER_ELEMENT, 0);

// ── Reader ────────────────────────────────────────────────────────────────

/**
 * A view of `count` elements at `offset`, copying only if the offset is not a
 * multiple of the element size. After the payload slice this fires for the
 * refined block and nothing else.
 */
function alignedView<T extends Ctor>(
  Ctor: T,
  buffer: ArrayBuffer,
  offset: number,
  count: number
): InstanceType<T> {
  const bytes = count * Ctor.BYTES_PER_ELEMENT;
  if (offset + bytes > buffer.byteLength) {
    throw new ProtocolError(
      `payload truncated: need ${offset + bytes} bytes, have ${buffer.byteLength}`
    );
  }
  if (offset % Ctor.BYTES_PER_ELEMENT === 0) {
    return new Ctor(buffer, offset, count) as InstanceType<T>;
  }
  return new Ctor(buffer.slice(offset, offset + bytes)) as InstanceType<T>;
}

/**
 * Check a sentinel such as "uint32[41990]" against the field it stands for.
 * The protocol is frozen, so a mismatch means the backend moved and the right
 * response is a loud failure rather than a plausible-looking wrong picture.
 */
function checkSentinel(
  group: string,
  field: string,
  sentinel: unknown,
  dtype: string,
  n: number
): void {
  const expected = `${dtype}[${n}]`;
  if (sentinel !== expected) {
    throw new ProtocolError(
      `${group}.${field}: header says ${JSON.stringify(sentinel)}, expected "${expected}" ` +
        `— avr25d/server/protocol.py and lib/protocol.ts have diverged`
    );
  }
}

/**
 * Decode one binary FrameMessage.
 *
 * Returns `null` for a zero-length message: the server sends empty frames as
 * keepalives while the pipeline queue is drained (server/app.py), and treating
 * one as a frame throws on every startup.
 */
export function decodeFrame(data: ArrayBuffer): FrameMessage | null {
  if (data.byteLength === 0) return null;

  if (data.byteLength < 4) {
    throw new ProtocolError(
      `too short to contain a header length: ${data.byteLength} bytes`
    );
  }

  const headerLen = new DataView(data).getUint32(0, true); // little-endian
  const payloadStart = 4 + headerLen;
  if (data.byteLength < payloadStart) {
    throw new ProtocolError(
      `message truncated: need ${payloadStart} bytes of header, got ${data.byteLength}`
    );
  }

  const headerText = new TextDecoder('utf-8').decode(new Uint8Array(data, 4, headerLen));
  let header: Record<string, unknown>;
  try {
    header = JSON.parse(headerText);
  } catch (cause) {
    throw new ProtocolError(`header is not valid JSON: ${(cause as Error).message}`);
  }

  const cellsHeader = header.cells as Record<string, unknown>;
  const refinedHeader = header.refined as Record<string, unknown>;
  if (!cellsHeader || !refinedHeader) {
    throw new ProtocolError('header is missing the `cells` or `refined` section');
  }

  const n = cellsHeader.n as number;
  const m = refinedHeader.n as number;
  if (!Number.isInteger(n) || n < 0 || !Number.isInteger(m) || m < 0) {
    throw new ProtocolError(`bad array counts: cells.n=${n}, refined.n=${m}`);
  }

  const expectedBytes = n * CELL_STRIDE + m * REFINED_STRIDE;
  const actualBytes = data.byteLength - payloadStart;
  if (actualBytes < expectedBytes) {
    throw new ProtocolError(
      `payload truncated: ${n} cells + ${m} refined need ${expectedBytes} bytes, got ${actualBytes}`
    );
  }

  // The one copy. See the note at the top of this file.
  const payload = data.slice(payloadStart, payloadStart + expectedBytes);

  let offset = 0;
  const cells = { n } as CellArrays;
  for (const [field, Ctor, dtype] of CELL_FIELDS) {
    checkSentinel('cells', field, cellsHeader[field], dtype, n);
    // @ts-expect-error — field indexes a union of typed-array properties; the
    // FIELDS table is the thing that guarantees each name gets its own type.
    cells[field] = alignedView(Ctor, payload, offset, n);
    offset += n * Ctor.BYTES_PER_ELEMENT;
  }

  const refined = { n: m } as RefinedArrays;
  for (const [field, Ctor, dtype] of REFINED_FIELDS) {
    checkSentinel('refined', field, refinedHeader[field], dtype, m);
    // @ts-expect-error — as above.
    refined[field] = alignedView(Ctor, payload, offset, m);
    offset += m * Ctor.BYTES_PER_ELEMENT;
  }

  return {
    frame_id: header.frame_id as number,
    t_sec: header.t_sec as number,
    mode: header.mode as string,
    cells,
    refined,
    tracks: (header.tracks ?? []) as Track[],
    decision: header.decision as Decision,
    stats: header.stats as FrameStats,
  };
}

/** Bytes on the wire per occupied cell (27) — used by the HUD's throughput readout. */
export const BYTES_PER_CELL = CELL_STRIDE;
/** Bytes on the wire per refined sub-cell (15). */
export const BYTES_PER_REFINED_CELL = REFINED_STRIDE;
