// sceneDressing.ts — reference geometry and atmosphere for the scene.
//
// Everything in here is DECORATION. It carries no sensor data and is derived
// from no frame: range rings, radial spokes, a horizon glow and a rotating
// sweep. It exists to give the cloud somewhere to sit and a sense of scale.
//
// ── Why rings and not a lattice ──────────────────────────────────────────
// The skeleton's THREE.GridHelper was removed on purpose: a square lattice is
// indistinguishable from the cell grid, and this is a view whose entire
// subject is cell size. Concentric range rings cannot be confused for cells —
// they read as distance markings — and they carry the one piece of structure
// worth showing, which is where the adaptive law changes: 5 cm cells inside
// the 10 m knee, coarsening to 50 cm out at the 100 m envelope.
//
// gridShader.ts still draws the actual cell boundaries, on the G toggle.

import * as THREE from 'three';

const LIDAR = 0x22d3ee;    // cyan — the near field, at full resolution
const ADAPTIVE = 0xa78bfa; // violet — the coarsening far field

/** Ring radii in metres. 10 m is the knee; 100 m is the envelope. */
const RINGS: { r: number; colour: number; opacity: number }[] = [
  { r: 10, colour: LIDAR, opacity: 0.5 },
  { r: 25, colour: LIDAR, opacity: 0.22 },
  { r: 50, colour: ADAPTIVE, opacity: 0.2 },
  { r: 100, colour: ADAPTIVE, opacity: 0.14 },
];

export interface SceneDressing {
  group: THREE.Group;
  /** Advance the sweep. Called from the render loop with seconds elapsed. */
  update: (elapsedS: number) => void;
  dispose: () => void;
}

export function createSceneDressing(): SceneDressing {
  const group = new THREE.Group();
  // Behind the cloud, and never writing depth, so it can never occlude a
  // real return or fight with the instanced cells.
  group.renderOrder = -1;

  const disposables: { dispose: () => void }[] = [];

  const track = <T extends THREE.BufferGeometry | THREE.Material>(x: T): T => {
    disposables.push(x);
    return x;
  };

  // ── Range rings ────────────────────────────────────────────────────
  for (const { r, colour, opacity } of RINGS) {
    const geometry = track(new THREE.RingGeometry(r - 0.06, r + 0.06, 192));
    const material = track(
      new THREE.MeshBasicMaterial({
        color: colour,
        transparent: true,
        opacity,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
    );
    const ring = new THREE.Mesh(geometry, material);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    group.add(ring);
  }

  // ── Radial spokes ──────────────────────────────────────────────────
  // Twelve bearings. Enough to read orientation while orbiting, few enough
  // that they never resemble a grid.
  const spokePoints: number[] = [];
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    spokePoints.push(Math.cos(a) * 6, 0.02, Math.sin(a) * 6);
    spokePoints.push(Math.cos(a) * 100, 0.02, Math.sin(a) * 100);
  }
  const spokeGeometry = track(new THREE.BufferGeometry());
  spokeGeometry.setAttribute('position', new THREE.Float32BufferAttribute(spokePoints, 3));
  const spokeMaterial = track(
    new THREE.LineBasicMaterial({ color: 0x334155, transparent: true, opacity: 0.34, depthWrite: false })
  );
  group.add(new THREE.LineSegments(spokeGeometry, spokeMaterial));

  // ── Ground wash ────────────────────────────────────────────────────
  // A disc that fades out with radius, so the cloud sits on something rather
  // than floating in a void. Written as a shader because a texture for one
  // radial gradient is not worth the asset.
  const washGeometry = track(new THREE.CircleGeometry(120, 96));
  const washMaterial = track(
    new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: {
        uNear: { value: new THREE.Color(0x0d213a) },
        uFar: { value: new THREE.Color(0x070a14) },
      },
      vertexShader: `
        varying float vR;
        void main() {
          vR = length(position.xy) / 120.0;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        uniform vec3 uNear;
        uniform vec3 uFar;
        varying float vR;
        void main() {
          float a = smoothstep(1.0, 0.0, vR) * 0.55;
          gl_FragColor = vec4(mix(uFar, uNear, 1.0 - vR), a);
        }`,
    })
  );
  const wash = new THREE.Mesh(washGeometry, washMaterial);
  wash.rotation.x = -Math.PI / 2;
  wash.position.y = -0.04;
  group.add(wash);

  // ── Scan sweep ─────────────────────────────────────────────────────
  // A soft wedge that rotates once every SWEEP_PERIOD_S. Additive and dim: it
  // should register as the scene breathing, not as a spinning graphic. It is
  // decoration — the sensor's real rate is on the telemetry rail.
  const SWEEP_PERIOD_S = 6;
  const sweepGeometry = track(new THREE.CircleGeometry(100, 64, 0, Math.PI / 5));
  const sweepMaterial = track(
    new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: { uColour: { value: new THREE.Color(LIDAR) } },
      vertexShader: `
        varying vec2 vXy;
        void main() {
          vXy = position.xy;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        uniform vec3 uColour;
        varying vec2 vXy;
        void main() {
          float r = length(vXy) / 100.0;
          // Brightest at the leading edge, fading behind it and with range.
          float lead = smoothstep(0.0, 0.55, atan(vXy.y, vXy.x) / ${(Math.PI / 5).toFixed(4)});
          float a = (1.0 - lead) * smoothstep(1.0, 0.15, r) * 0.16;
          gl_FragColor = vec4(uColour * a, a);
        }`,
    })
  );
  const sweep = new THREE.Mesh(sweepGeometry, sweepMaterial);
  sweep.rotation.x = -Math.PI / 2;
  sweep.position.y = 0.05;
  group.add(sweep);

  return {
    group,
    update(elapsedS: number) {
      sweep.rotation.z = -(elapsedS / SWEEP_PERIOD_S) * Math.PI * 2;
    },
    dispose() {
      for (const d of disposables) d.dispose();
      group.clear();
    },
  };
}
