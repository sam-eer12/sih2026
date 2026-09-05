// perfMeter.ts — honest frame timing for T-V6.
//
// Two separate costs, measured separately, because they happen in different
// places and conflating them hides the real bottleneck:
//
//   render — the requestAnimationFrame loop. What "FPS" normally means.
//   push   — updateCells/updatePoints writing n instances into GPU buffers.
//            Runs on the WebSocket callback at the stream rate, NOT in rAF.
//
// A viewer can render at a happy 60 FPS while pushFrame blocks the main
// thread for 40 ms every frame. Reporting only the first number would call
// that healthy.

const WINDOW = 240;   // frames retained for percentile maths (~4 s at 60 FPS)

export interface PerfReport {
  fps: number;          // mean over the window
  fpsLow: number;       // 1%-low: mean of the slowest 1% of frames
  pushAvgMs: number;
  pushMaxMs: number;
  instances: number;
  frames: number;
}

export class PerfMeter {
  private frameTimes = new Float32Array(WINDOW);
  private frameCount = 0;
  private lastFrameAt = 0;

  private pushTimes = new Float32Array(WINDOW);
  private pushCount = 0;

  private instances = 0;

  recordFrame(now: number): void {
    if (this.lastFrameAt > 0) {
      this.frameTimes[this.frameCount % WINDOW] = now - this.lastFrameAt;
      this.frameCount++;
    }
    this.lastFrameAt = now;
  }

  recordPush(ms: number, instances: number): void {
    this.pushTimes[this.pushCount % WINDOW] = ms;
    this.pushCount++;
    this.instances = instances;
  }

  report(): PerfReport {
    const n = Math.min(this.frameCount, WINDOW);
    if (n === 0) {
      return { fps: 0, fpsLow: 0, pushAvgMs: 0, pushMaxMs: 0, instances: this.instances, frames: 0 };
    }

    const frames = Array.from(this.frameTimes.subarray(0, n));
    const meanMs = frames.reduce((a, b) => a + b, 0) / n;

    // 1%-low: the slowest frames are what a judge sees as a stutter.
    const sorted = [...frames].sort((a, b) => b - a);
    const lowN = Math.max(1, Math.floor(n * 0.01));
    const lowMean = sorted.slice(0, lowN).reduce((a, b) => a + b, 0) / lowN;

    const p = Math.min(this.pushCount, WINDOW);
    const pushes = Array.from(this.pushTimes.subarray(0, p));
    const pushAvg = p ? pushes.reduce((a, b) => a + b, 0) / p : 0;
    const pushMax = p ? Math.max(...pushes) : 0;

    return {
      fps: 1000 / meanMs,
      fpsLow: 1000 / lowMean,
      pushAvgMs: pushAvg,
      pushMaxMs: pushMax,
      instances: this.instances,
      frames: this.frameCount,
    };
  }

  reset(): void {
    this.frameCount = 0;
    this.pushCount = 0;
    this.lastFrameAt = 0;
  }
}

export function formatReport(r: PerfReport): string {
  return (
    `${r.fps.toFixed(1)} FPS (1% low ${r.fpsLow.toFixed(1)}) · ` +
    `push ${r.pushAvgMs.toFixed(1)} ms avg / ${r.pushMaxMs.toFixed(1)} ms max · ` +
    `${r.instances.toLocaleString()} instances`
  );
}
