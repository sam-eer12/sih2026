// format.ts — display helpers.
//
// T-V4: the HUD must never show `NaN` or `undefined`. Every formatter takes
// an unknown-ish number and falls back to an em dash, so a missing field
// reads as "not reported" instead of leaking a JavaScript value onto a
// projector. Formatting only — nothing here computes a displayed quantity.

const MISSING = '—';

function isNum(v: number | undefined | null): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Fixed-decimal number, or an em dash. */
export function num(v: number | undefined | null, dp = 0): string {
  return isNum(v) ? v.toFixed(dp) : MISSING;
}

/** Thousands-separated integer, or an em dash. */
export function count(v: number | undefined | null): string {
  return isNum(v) ? Math.round(v).toLocaleString('en-GB') : MISSING;
}

/** Bytes as MB with one decimal, or an em dash. */
export function megabytes(v: number | undefined | null): string {
  return isNum(v) ? `${(v / 1e6).toFixed(1)} MB` : MISSING;
}

/** Milliseconds, or an em dash. */
export function ms(v: number | undefined | null, dp = 1): string {
  return isNum(v) ? `${v.toFixed(dp)} ms` : MISSING;
}

/** A reduction ratio as "22.67x", or an em dash. */
export function ratio(v: number | undefined | null): string {
  return isNum(v) ? `${v.toFixed(2)}×` : MISSING;
}
