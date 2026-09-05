/**
 * Class colour palette — single source of truth.
 * Mirrors the class taxonomy from avr25d/perception/labelmap.py.
 *
 * RULE: Nobody hard-codes a hex value anywhere else in the frontend.
 * Import from here. If the colours disagree between the viewer and
 * the HUD, a judge will notice.
 */

export const CLASS_COLOURS = {
  UNLABELED:             0x808080,  // grey
  DRIVABLE:              0x00C853,  // green — the road
  NON_DRIVABLE_TERRAIN:  0xFFD600,  // amber — grass, dirt
  STATIC_OBSTACLE:       0xD50000,  // red — walls, buildings
  DYNAMIC_OBJECT:        0x2979FF,  // blue — vehicles, people
} as const;

export type ClassName = keyof typeof CLASS_COLOURS;

// Map from class_id (uint8 in the FrameMessage) to colour
export const CLASS_ID_TO_COLOUR: number[] = [
  CLASS_COLOURS.UNLABELED,            // 0
  CLASS_COLOURS.DRIVABLE,             // 1
  CLASS_COLOURS.NON_DRIVABLE_TERRAIN, // 2
  CLASS_COLOURS.STATIC_OBSTACLE,      // 3
  CLASS_COLOURS.DYNAMIC_OBJECT,       // 4
];

// For the HUD legend — human-readable names
export const CLASS_NAMES: string[] = [
  'Unlabeled',
  'Drivable',
  'Non-drivable Terrain',
  'Static Obstacle',
  'Dynamic Object',
];

// ── Elevation shading (FR-25 toggle) ───────────────────────────────
// A perceptually-uniform ramp (plasma). Chosen because it stays
// monotonic in greyscale — it survives a bad projector and reads
// correctly for colour-blind judges, same test as the class colours.
//
// This is NOT a class colour: elevation shading answers "how high",
// class colour answers "what is it". Never mix them in one view.

export const ELEVATION_RAMP: number[] = [
  0x0D0887, // low
  0x7E03A8,
  0xCC4778,
  0xF89540,
  0xF0F921, // high
];

/**
 * Sample the elevation ramp at t ∈ [0, 1].
 * Returns sRGB components in [0, 1] — the caller decides the colour space.
 * Kept free of any Three.js import so the HUD can use it too.
 */
export function elevationRampRGB(t: number): [number, number, number] {
  const clamped = t < 0 ? 0 : t > 1 ? 1 : t;
  const scaled = clamped * (ELEVATION_RAMP.length - 1);
  const i = Math.min(Math.floor(scaled), ELEVATION_RAMP.length - 2);
  const f = scaled - i;

  const a = ELEVATION_RAMP[i];
  const b = ELEVATION_RAMP[i + 1];

  const ar = (a >> 16) & 0xff, ag = (a >> 8) & 0xff, ab = a & 0xff;
  const br = (b >> 16) & 0xff, bg = (b >> 8) & 0xff, bb = b & 0xff;

  return [
    (ar + (br - ar) * f) / 255,
    (ag + (bg - ag) * f) / 255,
    (ab + (bb - ab) * f) / 255,
  ];
}

/** Elevation range, in metres, that the ramp spans. */
export const ELEVATION_RANGE = { min: -2.0, max: 6.0 };

// ── Decision layer (View 4, FR-25) ─────────────────────────────────
// Risk is a three-state verdict from the planner, not a continuum.
// Distinct in greyscale as well as hue: LOW is lightest, HIGH darkest.

export const RISK_COLOURS = {
  LOW:    0x69F0AE,   // green
  MEDIUM: 0xFFC400,   // amber
  HIGH:   0xFF5252,   // red
} as const;

export type RiskLevel = keyof typeof RISK_COLOURS;

export function riskColour(risk: string): number {
  return RISK_COLOURS[risk as RiskLevel] ?? RISK_COLOURS.MEDIUM;
}

/** Route styling. The selected route reads as the decision; the other is context. */
export const ROUTE_COLOURS = {
  PRIMARY:     0x40C4FF,   // blue — the default path
  ALTERNATIVE: 0xB388FF,   // violet — the reroute
  UNSELECTED:  0x546E7A,   // slate — drawn, but visibly not chosen
} as const;

/** Predicted trajectory of a tracked object. */
export const TRACK_PREDICTION_COLOUR = 0xFF80AB;
