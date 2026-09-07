// ViewControls.tsx — the demo, drivable without touching the keyboard.
//
// Every control calls SceneHandle. Nothing here reaches into the viewer's
// internals, and nothing duplicates what the viewer already knows: the button
// states are read back from the handle on a timer, so using the keyboard and
// using the buttons can never disagree. That read-back is why this polls at
// all — Shubham's key bindings are still live, and a control panel that
// silently drifted out of sync with the scene would be worse than no panel.
//
// The keys are the run-book's (IMPLEMENTATION_PLAN §10), shown on each button
// so the presenter can use either.
'use client';

import { useCallback, useEffect, useState } from 'react';
import type { SceneHandle, ViewMode } from '../viewer/useThreeScene';

/** Refresh rate for reading control state back from the scene. */
const SAMPLE_HZ = 4;

const VIEWS: ReadonlyArray<readonly [ViewMode, string, string]> = [
  ['raw', '1', 'Raw'],
  ['uniform', '2', 'Uniform'],
  ['adaptive', '3', 'Adaptive'],
  ['decision', '4', 'Decision'],
] as const;

interface ControlState {
  view: ViewMode;
  elevation: boolean;
  grid: boolean;
  wipe: boolean;
}

export default function ViewControls({
  getHandle,
  onWipeChange,
}: {
  getHandle: () => SceneHandle | null;
  /** Called when the wipe button is toggled. Wires to Viewer's onWipeChange. */
  onWipeChange?: (active: boolean) => void;
}) {
  const [state, setState] = useState<ControlState | null>(null);

  const read = useCallback((): ControlState | null => {
    const h = getHandle();
    if (!h) return null;
    return {
      view: h.getView(),
      elevation: h.getColourMode() === 'elevation',
      grid: h.getGridOverlay(),
      wipe: h.getWipe(),
    };
  }, [getHandle]);

  useEffect(() => {
    const id = window.setInterval(() => setState(read()), 1000 / SAMPLE_HZ);
    return () => window.clearInterval(id);
  }, [read]);

  const setView = (view: ViewMode) => {
    getHandle()?.setView(view);
    setState(read());
  };

  const toggleElevation = () => {
    const h = getHandle();
    if (!h) return;
    h.setColourMode(h.getColourMode() === 'class' ? 'elevation' : 'class');
    setState(read());
  };

  const toggleGrid = () => {
    const h = getHandle();
    if (!h) return;
    h.setGridOverlay(!h.getGridOverlay());
    setState(read());
  };

  const toggleWipe = () => {
    const h = getHandle();
    if (!h) return;
    const next = !h.getWipe();
    // Drive through the prop so Viewer's controlled/uncontrolled path decides
    // how to update state. No synthetic keyboard events needed.
    if (onWipeChange) {
      onWipeChange(next);
    } else {
      // Fallback: viewer was mounted without controlled wipe props (e.g. in
      // Shubham's offline dev mode). Drive SceneHandle directly; the overlay
      // won't update but the GPU scissor will, which is better than nothing.
      h.setWipe(next);
    }
    setState(read());
  };

  if (!state) return null;

  return (
    <div style={BAR}>
      <div style={GROUP}>
        {VIEWS.map(([mode, key, label]) => (
          <Button
            key={mode}
            active={state.view === mode}
            hint={key}
            label={label}
            onClick={() => setView(mode)}
          />
        ))}
      </div>

      <span style={DIVIDER} />

      <div style={GROUP}>
        <Button
          active={state.elevation}
          hint="E"
          label="Elevation"
          onClick={toggleElevation}
          title="Shade by height instead of semantic class (FR-26)"
        />
        <Button
          active={state.grid}
          hint="G"
          label="Grid"
          onClick={toggleGrid}
          title="Draw the cell boundaries themselves (FR-27)"
        />
        <Button
          active={state.wipe}
          hint="W"
          label="A/B Wipe"
          onClick={toggleWipe}
          title="Uniform 5 cm against the adaptive grid, one scan (FR-29)"
        />
      </div>
    </div>
  );
}

function Button({
  active,
  hint,
  label,
  onClick,
  title,
}: {
  active: boolean;
  hint: string;
  label: string;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button type="button" onClick={onClick} title={title} style={btnStyle(active)}>
      <kbd style={kbdStyle(active)}>{hint}</kbd>
      {label}
    </button>
  );
}

function btnStyle(active: boolean): React.CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    padding: '8px 12px',
    borderRadius: 5,
    border: `1px solid ${active ? '#00C853' : 'rgba(255,255,255,0.18)'}`,
    background: active ? 'rgba(0,200,83,0.16)' : 'rgba(255,255,255,0.04)',
    color: active ? '#00C853' : '#d6d6e2',
    font: '600 13px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
    cursor: 'pointer',
  };
}

function kbdStyle(active: boolean): React.CSSProperties {
  return {
    display: 'inline-block',
    minWidth: 15,
    padding: '2px 4px',
    borderRadius: 3,
    background: active ? 'rgba(0,200,83,0.28)' : 'rgba(255,255,255,0.10)',
    font: '600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
    textAlign: 'center',
  };
}

const BAR: React.CSSProperties = {
  position: 'absolute',
  bottom: 16,
  left: 16,
  zIndex: 10,
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '10px 12px',
  borderRadius: 8,
  border: '1px solid rgba(255,255,255,0.14)',
  background: 'rgba(10, 10, 20, 0.86)',
  backdropFilter: 'blur(6px)',
};

const GROUP: React.CSSProperties = { display: 'flex', gap: 6 };

const DIVIDER: React.CSSProperties = {
  width: 1,
  alignSelf: 'stretch',
  background: 'rgba(255,255,255,0.14)',
};
