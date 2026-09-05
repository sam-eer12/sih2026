// decisionLayer.ts — View 4, the decision layer (FR-25, items 23-24).
//
// Three things the judge has to read from three metres away:
//   1. WHERE the vehicle intends to go        — the routes
//   2. WHAT made it change its mind           — the tracks and their predictions
//   3. HOW dangerous the situation is         — the risk verdict
//
// The reroute has to be legible at a glance, so the selected route is drawn
// thick and in the risk colour, and the rejected one is drawn thin and slate.
// Colour alone would not survive a bad projector; width carries it too.

import * as THREE from 'three';
import {
  CLASS_ID_TO_COLOUR,
  ROUTE_COLOURS,
  TRACK_PREDICTION_COLOUR,
  riskColour,
} from '../../lib/palette';
import type { Decision, FrameMessage, Track } from './types';

const ROUTE_Y = 0.35;      // m above ground — clear of the cell boxes
const MARKER_SIZE = 1.6;   // m — a track marker must be findable, not accurate
const MAX_TRACKS = 64;     // hard cap; the tracker will not exceed this

export interface DecisionLayer {
  group: THREE.Group;
  update: (msg: FrameMessage) => void;
  setVisible: (on: boolean) => void;
  dispose: () => void;
}

/** A polyline whose vertex buffer is reused across frames. */
function makeRoute(colour: number, width: number, capacity = 256) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(capacity * 3), 3).setUsage(THREE.DynamicDrawUsage)
  );
  // NOTE: linewidth is ignored by every WebGL implementation. Width is faked
  // below by drawing the selected route as a thin extruded ribbon instead.
  const material = new THREE.LineBasicMaterial({ color: colour });
  const line = new THREE.Line(geometry, material);
  line.frustumCulled = false;
  void width;
  return { line, geometry, material };
}

function writePath(geometry: THREE.BufferGeometry, path: number[][], y: number): void {
  const attr = geometry.getAttribute('position') as THREE.BufferAttribute;
  const arr = attr.array as Float32Array;
  const n = Math.min(path.length, attr.count);
  for (let i = 0; i < n; i++) {
    const o = i * 3;
    arr[o] = path[i][0];        // LiDAR x
    arr[o + 1] = y;             // Three is Y-up
    arr[o + 2] = path[i][1];    // LiDAR y
  }
  geometry.setDrawRange(0, n);
  attr.needsUpdate = true;
}

/**
 * A route ribbon — a flat strip along the path, so the selected route has real
 * width on screen. WebGL ignores LineBasicMaterial.linewidth entirely, which
 * is the usual reason a "thick" route silently renders hairline-thin.
 */
function makeRibbon(colour: number, halfWidth: number, capacity = 256) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(capacity * 2 * 3), 3).setUsage(THREE.DynamicDrawUsage)
  );
  const index: number[] = [];
  for (let i = 0; i < capacity - 1; i++) {
    const a = i * 2;
    index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }
  geometry.setIndex(index);

  const material = new THREE.MeshBasicMaterial({
    color: colour,
    transparent: true,
    opacity: 0.9,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false;
  return { mesh, geometry, material, halfWidth };
}

function writeRibbon(
  geometry: THREE.BufferGeometry,
  path: number[][],
  y: number,
  halfWidth: number
): void {
  const attr = geometry.getAttribute('position') as THREE.BufferAttribute;
  const arr = attr.array as Float32Array;
  const n = Math.min(path.length, attr.count / 2);

  for (let i = 0; i < n; i++) {
    // Perpendicular from the local heading, so corners stay square-ish.
    const prev = path[Math.max(0, i - 1)];
    const next = path[Math.min(n - 1, i + 1)];
    let dx = next[0] - prev[0];
    let dy = next[1] - prev[1];
    const len = Math.hypot(dx, dy) || 1;
    dx /= len;
    dy /= len;
    const px = -dy * halfWidth;
    const py = dx * halfWidth;

    const o = i * 6;
    arr[o] = path[i][0] + px;
    arr[o + 1] = y;
    arr[o + 2] = path[i][1] + py;
    arr[o + 3] = path[i][0] - px;
    arr[o + 4] = y;
    arr[o + 5] = path[i][1] - py;
  }

  geometry.setIndex(geometry.getIndex());
  geometry.setDrawRange(0, Math.max(0, (n - 1) * 6));
  attr.needsUpdate = true;
}

export function createDecisionLayer(): DecisionLayer {
  const group = new THREE.Group();
  group.visible = false;

  // Routes: the rejected one as a hairline, the selected one as a ribbon.
  const primary = makeRoute(ROUTE_COLOURS.PRIMARY, 1);
  const alternative = makeRoute(ROUTE_COLOURS.ALTERNATIVE, 1);
  const selected = makeRibbon(ROUTE_COLOURS.PRIMARY, 0.45);
  group.add(primary.line, alternative.line, selected.mesh);

  // Track markers: one instanced mesh, coloured per class.
  const markerGeo = new THREE.BoxGeometry(MARKER_SIZE, MARKER_SIZE * 1.4, MARKER_SIZE);
  const markerMat = new THREE.MeshLambertMaterial({ transparent: true, opacity: 0.85 });
  const markers = new THREE.InstancedMesh(markerGeo, markerMat, MAX_TRACKS);
  markers.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  markers.frustumCulled = false;
  markers.count = 0;
  group.add(markers);

  // Predicted trajectories: one shared line-segment buffer for all tracks.
  const predGeo = new THREE.BufferGeometry();
  predGeo.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(MAX_TRACKS * 32 * 3), 3).setUsage(
      THREE.DynamicDrawUsage
    )
  );
  const predMat = new THREE.LineBasicMaterial({
    color: TRACK_PREDICTION_COLOUR,
    transparent: true,
    opacity: 0.95,
  });
  const predictions = new THREE.LineSegments(predGeo, predMat);
  predictions.frustumCulled = false;
  group.add(predictions);

  const _dummy = new THREE.Object3D();
  const _colour = new THREE.Color();

  function updateTracks(tracks: Track[]): void {
    const n = Math.min(tracks.length, MAX_TRACKS);

    for (let i = 0; i < n; i++) {
      const t = tracks[i];
      _dummy.position.set(t.x, MARKER_SIZE * 0.7, t.y);
      // Face the direction of travel, so a glance reads heading as well as position.
      _dummy.rotation.set(0, -Math.atan2(t.vy, t.vx), 0);
      _dummy.scale.set(1, 1, 1);
      _dummy.updateMatrix();
      markers.setMatrixAt(i, _dummy.matrix);
      _colour.setHex(CLASS_ID_TO_COLOUR[t.class_id] ?? 0x808080, THREE.SRGBColorSpace);
      markers.setColorAt(i, _colour);
    }
    markers.count = n;
    markers.instanceMatrix.needsUpdate = true;
    if (markers.instanceColor) markers.instanceColor.needsUpdate = true;

    // Predictions as disjoint segments: [p0,p1][p1,p2]... per track.
    const attr = predGeo.getAttribute('position') as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    let v = 0;
    const maxVerts = attr.count;

    for (let i = 0; i < n; i++) {
      const t = tracks[i];
      const path = t.predicted ?? [];
      let prevX = t.x;
      let prevY = t.y;
      for (let j = 0; j < path.length && v + 2 <= maxVerts; j++) {
        arr[v * 3] = prevX;
        arr[v * 3 + 1] = ROUTE_Y;
        arr[v * 3 + 2] = prevY;
        v++;
        arr[v * 3] = path[j][0];
        arr[v * 3 + 1] = ROUTE_Y;
        arr[v * 3 + 2] = path[j][1];
        v++;
        prevX = path[j][0];
        prevY = path[j][1];
      }
    }
    predGeo.setDrawRange(0, v);
    attr.needsUpdate = true;
  }

  function updateDecision(d: Decision): void {
    const chosen = d.selected === 'alternative' ? d.alternative : d.route;
    const rejected = d.selected === 'alternative' ? d.route : d.alternative;

    writePath(primary.geometry, rejected ?? [], ROUTE_Y);
    primary.material.color.setHex(ROUTE_COLOURS.UNSELECTED, THREE.SRGBColorSpace);

    // The alternative line is redundant once the ribbon shows the choice;
    // keep it empty rather than drawing the chosen path twice at two widths.
    writePath(alternative.geometry, [], ROUTE_Y);

    writeRibbon(selected.geometry, chosen ?? [], ROUTE_Y, selected.halfWidth);
    // Risk colours the route the vehicle is actually taking — that is the
    // thing at risk. Colouring the rejected one would say nothing.
    selected.material.color.setHex(riskColour(d.risk), THREE.SRGBColorSpace);
  }

  return {
    group,
    update: (msg) => {
      if (msg.tracks) updateTracks(msg.tracks);
      if (msg.decision) updateDecision(msg.decision);
    },
    setVisible: (on) => {
      group.visible = on;
    },
    dispose: () => {
      primary.geometry.dispose();
      primary.material.dispose();
      alternative.geometry.dispose();
      alternative.material.dispose();
      selected.geometry.dispose();
      selected.material.dispose();
      markerGeo.dispose();
      markerMat.dispose();
      markers.dispose();
      predGeo.dispose();
      predMat.dispose();
    },
  };
}
