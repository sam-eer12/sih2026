// types.ts — what the HUD reads, and where each field comes from.
//
// Two sources, and the distinction matters:
//
//   stats / mode / frameId  — straight off the FrameMessage. Never computed
//                             here. One source of truth means the HUD and
//                             results.json cannot disagree (WORK_DISTRIBUTION
//                             §5.2).
//   perf / uniform / capacity — read from Shubham's SceneHandle getters. The
//                             viewer already measures these; recomputing them
//                             would be a second answer to the same question.

import type { FrameStats } from '../../lib/protocol';
import type { PerfReport } from '../viewer/perfMeter';
import type { UniformStats } from '../viewer/uniformGrid';

export interface HudSnapshot {
  /** FrameMessage.frame_id — the frame index (FR-28). */
  frameId: number;
  /**
   * FrameMessage.mode, verbatim (FR-6).
   *
   * Deliberately not interpreted. `--fixtures` reports "geometric", the same
   * string a real geometric run reports, and the wire carries nothing that
   * separates them. Inventing a "fixtures" label here would mean the badge
   * asserting something the pipeline never told us — exactly the failure mode
   * FR-6 exists to prevent. If the demo needs to distinguish them, the server
   * has to say so on the wire.
   */
  mode: string;
  stats: FrameStats;
  /** Rendering-side measurements from the viewer (T-V6). */
  perf: PerfReport;
  /** The uniform-grid side of the A/B comparison. */
  uniform: UniformStats;
  /** Cell capacity of the grid the active view represents. */
  capacity: number;
}

/** Returns the current snapshot, or null before the first frame arrives. */
export type HudSampler = () => HudSnapshot | null;
