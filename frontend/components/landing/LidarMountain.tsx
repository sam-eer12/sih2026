// LidarMountain.tsx — the hero.
//
// A shaded mountain that becomes a LiDAR point cloud under the cursor.
//
// ── Why it is built this way ──────────────────────────────────────────────
// The two states are the SAME geometry: the mesh is the surface, the points
// are samples of it (see terrain.ts). Nothing is faked from luminance, so the
// transition shows what the product actually does — take a surface and keep
// only what a sensor would return from it.
//
// The reveal is radial from the pointer rather than a global crossfade,
// because that is how a scan behaves: the cloud exists where the beam has
// swept. Points inside the front light up and settle; the mesh dissolves
// behind them.
//
// Colour comes from lib/palette.ts, the same file the viewer uses. The
// landing page and the dashboard therefore speak one colour language, and a
// judge who sees green-is-drivable here reads it correctly there.

'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { buildTerrain, PEAK } from './terrain';
import { CLASS_COLOURS } from '../../lib/palette';

/** How fast the reveal chases the pointer. Lower is heavier. */
const DAMPING = 0.055;

const VERT = /* glsl */ `
uniform float uReveal;      // 0 = surface, 1 = fully scanned
uniform vec3  uFocus;       // world-space pointer position on the terrain
uniform float uTime;
uniform float uRadius;

attribute float aElevation;
attribute float aJitter;

varying float vLit;
varying float vElev;

void main() {
  vElev = aElevation;

  // Distance from the scan origin, normalised by the front radius.
  float d = distance(position.xz, uFocus.xz) / uRadius;

  // Scanned-ness: 1 inside the front, falling off across a soft edge.
  float scanned = smoothstep(1.0, 0.55, d) * uReveal;

  // Points lift off the surface as they are acquired, then settle — the
  // small overshoot is what makes the cloud read as detaching from the mesh
  // rather than being painted onto it.
  float lift = sin(scanned * 3.14159) * 0.55 * aJitter;
  vec3 p = position + vec3(0.0, lift, 0.0);

  // A slow breathing drift, scaled by how acquired the point is, so the
  // cloud feels live rather than frozen.
  p.y += sin(uTime * 1.2 + aJitter * 6.28) * 0.06 * scanned;

  vLit = scanned;

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  // Perspective-correct point size, with acquired points slightly larger.
  gl_PointSize = (1.7 + 2.4 * scanned) * (34.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}
`;

const FRAG = /* glsl */ `
precision highp float;

uniform vec3 uLow;
uniform vec3 uMid;
uniform vec3 uHigh;

varying float vLit;
varying float vElev;

void main() {
  // Round points. Discarding the corners costs nothing and stops the cloud
  // looking like confetti made of squares.
  vec2 c = gl_PointCoord - 0.5;
  float r2 = dot(c, c);
  if (r2 > 0.25) discard;

  if (vLit < 0.01) discard;

  // Elevation banding in the product's own palette: valley floor reads as
  // drivable, the flanks as terrain, the peaks as obstacle.
  vec3 col = mix(uLow, uMid, smoothstep(0.08, 0.42, vElev));
  col = mix(col, uHigh, smoothstep(0.46, 0.86, vElev));

  // Soft core, so dense regions bloom slightly instead of clipping flat.
  float core = 1.0 - smoothstep(0.0, 0.25, r2);
  gl_FragColor = vec4(col * (0.55 + 0.75 * core), vLit);
}
`;

export interface LidarMountainProps {
  className?: string;
}

export default function LidarMountain({ className }: LidarMountainProps) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight, false);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    // Fog tuned to swallow the terrain plate's own edge: without it the
    // square boundary of the height field cuts a visible diamond across the
    // hero and the mountain reads as a model on a table.
    scene.fog = new THREE.Fog(0x070a14, 30, 74);

    const camera = new THREE.PerspectiveCamera(
      42, host.clientWidth / host.clientHeight, 0.1, 400
    );
    camera.position.set(0, 20.5, 44);
    camera.lookAt(4, 3.2, 0);

    // ── Shared geometry ──────────────────────────────────────────
    const t = buildTerrain();

    const positionAttr = new THREE.BufferAttribute(t.positions, 3);
    const normalAttr = new THREE.BufferAttribute(t.normals, 3);
    const elevAttr = new THREE.BufferAttribute(t.elevation, 1);

    const jitter = new Float32Array(t.count);
    for (let i = 0; i < t.count; i++) jitter[i] = Math.random();

    // ── The surface: what it looks like before the beam hits it ──
    const meshGeo = new THREE.BufferGeometry();
    meshGeo.setAttribute('position', positionAttr);
    meshGeo.setAttribute('normal', normalAttr);
    meshGeo.setIndex(new THREE.BufferAttribute(t.indices, 1));

    // Rock that pales toward the ridges, so the silhouette reads at a glance.
    const meshColours = new Float32Array(t.count * 3);
    const rock = new THREE.Color(0x2b3550);
    const scree = new THREE.Color(0x54607f);
    const snow = new THREE.Color(0xdfe7f5);
    const tmp = new THREE.Color();
    for (let i = 0; i < t.count; i++) {
      const e = t.elevation[i];
      tmp.copy(rock).lerp(scree, THREE.MathUtils.smoothstep(e, 0.05, 0.5));
      tmp.lerp(snow, THREE.MathUtils.smoothstep(e, 0.62, 0.95));
      meshColours[i * 3] = tmp.r;
      meshColours[i * 3 + 1] = tmp.g;
      meshColours[i * 3 + 2] = tmp.b;
    }
    meshGeo.setAttribute('color', new THREE.BufferAttribute(meshColours, 3));

    const meshMat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.94,
      metalness: 0.02,
      transparent: true,
      opacity: 1,
      flatShading: false,
    });
    const mesh = new THREE.Mesh(meshGeo, meshMat);

    // Everything lives in one group so the massif can be pushed clear of the
    // headline column without decoupling the mesh from its point cloud.
    const terrain = new THREE.Group();
    terrain.position.x = 11;
    terrain.add(mesh);
    scene.add(terrain);

    // ── The cloud: what the sensor returns ───────────────────────
    const pointGeo = new THREE.BufferGeometry();
    pointGeo.setAttribute('position', positionAttr);
    pointGeo.setAttribute('aElevation', elevAttr);
    pointGeo.setAttribute('aJitter', new THREE.BufferAttribute(jitter, 1));

    const uniforms = {
      uReveal: { value: 0 },
      uFocus: { value: new THREE.Vector3(0, 0, 0) },
      uTime: { value: 0 },
      uRadius: { value: 26 },
      uLow: { value: new THREE.Color(CLASS_COLOURS.DRIVABLE) },
      uMid: { value: new THREE.Color(CLASS_COLOURS.NON_DRIVABLE_TERRAIN) },
      uHigh: { value: new THREE.Color(CLASS_COLOURS.STATIC_OBSTACLE) },
    };

    const pointMat = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const points = new THREE.Points(pointGeo, pointMat);
    terrain.add(points);

    // ── Lighting for the surface state ───────────────────────────
    scene.add(new THREE.AmbientLight(0x93a6d8, 0.75));
    const key = new THREE.DirectionalLight(0xffe9cf, 1.5);
    key.position.set(-26, 30, 16);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x6f8ecf, 0.55);
    rim.position.set(22, 12, -20);
    scene.add(rim);

    // ── Pointer → scan origin ────────────────────────────────────
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -PEAK * 0.32);
    const hit = new THREE.Vector3();

    let targetReveal = 0;
    let reveal = 0;
    const focus = new THREE.Vector3(0, 0, 0);
    const targetFocus = new THREE.Vector3(0, 0, 0);

    function onPointerMove(e: PointerEvent) {
      const r = host!.getBoundingClientRect();
      ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      raycaster.setFromCamera(ndc, camera);
      if (raycaster.ray.intersectPlane(plane, hit)) {
        // Into the group's local frame, or the scan lags the cursor by the
        // offset applied above.
        targetFocus.set(hit.x - terrain.position.x, hit.y, hit.z);
      }
    }
    function onEnter() { targetReveal = 1; }
    function onLeave() { targetReveal = 0; }

    host.addEventListener('pointermove', onPointerMove);
    host.addEventListener('pointerenter', onEnter);
    host.addEventListener('pointerleave', onLeave);

    // Touch has no hover. Rather than leave the effect unreachable, reveal it
    // outright and park the scan centre on the massif.
    const coarse = window.matchMedia('(pointer: coarse)').matches;
    if (coarse) { targetReveal = 1; targetFocus.set(0, 0, 0); }

    function onResize() {
      const w = host!.clientWidth;
      const h = host!.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    }
    const ro = new ResizeObserver(onResize);
    ro.observe(host);

    // ── Loop ─────────────────────────────────────────────────────
    const clock = new THREE.Clock();
    let raf = 0;
    function tick() {
      raf = requestAnimationFrame(tick);

      reveal += (targetReveal - reveal) * DAMPING;
      focus.lerp(targetFocus, 0.09);

      uniforms.uReveal.value = reveal;
      uniforms.uFocus.value.copy(focus);
      uniforms.uTime.value = clock.getElapsedTime();

      // The surface retreats as the cloud arrives, but never fully: a trace
      // of it keeps the silhouette legible against the page.
      meshMat.opacity = 1 - reveal * 0.88;

      // A slow orbit, so the terrain reads as an object rather than a texture.
      const a = clock.getElapsedTime() * 0.045;
      camera.position.x = Math.sin(a) * 7.5;
      camera.position.z = 44 - Math.cos(a) * 3.5;
      camera.lookAt(4, 3.2, 0);

      renderer.render(scene, camera);
    }
    tick();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      host.removeEventListener('pointermove', onPointerMove);
      host.removeEventListener('pointerenter', onEnter);
      host.removeEventListener('pointerleave', onLeave);
      meshGeo.dispose();
      pointGeo.dispose();
      meshMat.dispose();
      pointMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={hostRef} className={className} aria-hidden="true" />;
}
