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
    <div className="pointer-events-auto flex items-center gap-1.5 rounded-xl border border-[var(--line)] bg-[var(--ink-850)]/80 p-1.5 backdrop-blur-md">
      {VIEWS.map(([mode, key, label]) => {
        const active = state.view === mode;
        return (
          <button
            key={mode}
            type="button"
            aria-pressed={active}
            onClick={() => setView(mode)}
            title={`${label} view (${key})`}
            className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 t-label font-medium transition-colors duration-150"
            style={{
              background: active ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
              color: active ? 'var(--accent)' : 'var(--text-lo)',
            }}
          >
            {label}
            <kbd
              className="tabular text-[11px] transition-opacity duration-150"
              style={{ opacity: active ? 0.75 : 0.4 }}
            >
              {key}
            </kbd>
          </button>
        );
      })}

      <span className="mx-1 h-5 w-px bg-[var(--line)]" />

      <Toggle active={state.elevation} onClick={toggleElevation} hint="E"
        title="Shade by height instead of semantic class (FR-26)">Elevation</Toggle>
      <Toggle active={state.grid} onClick={toggleGrid} hint="G"
        title="Draw the cell boundaries themselves (FR-27)">Grid</Toggle>
      <Toggle active={state.wipe} onClick={toggleWipe} hint="W"
        title="Uniform 5 cm against the adaptive grid, one scan (FR-29)">Wipe</Toggle>
    </div>
  );
}

function Toggle({
  active,
  onClick,
  hint,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  hint: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      title={`${title} (${hint})`}
      className="flex items-center gap-2 rounded-lg px-3.5 py-2 t-label font-medium transition-colors duration-150 hover:text-[var(--text-hi)]"
      style={{
        background: active ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text-lo)',
      }}
    >
      {children}
      <kbd className="tabular text-[11px]" style={{ opacity: active ? 0.75 : 0.4 }}>
        {hint}
      </kbd>
    </button>
  );
}
