import { useCallback, useEffect, useMemo, useState } from 'react';

export type Async<T> =
  | { status: 'loading'; previous: T | undefined }
  | { status: 'error'; error: unknown; previous: T | undefined }
  | { status: 'ready'; data: T };

interface Settled<T> { load: (signal: AbortSignal) => Promise<T>; nonce: number; result: Async<T> }

// Runs `load` whenever its identity changes (memoize it with useCallback and
// list what it reads) or `reload` is called. Loading is derived rather than
// stored: a result belongs to the load and nonce that produced it, so a
// stale result is never shown as current. `update` edits the loaded value in
// place, for writes that return the saved row.
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>): {
  state: Async<T>; reload: () => void; update: (change: (data: T) => T) => void;
} {
  const [nonce, setNonce] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      data => { if (!controller.signal.aborted) setSettled({ load, nonce, result: { status: 'ready', data } }); },
      error => { if (!controller.signal.aborted) setSettled(prev => ({ load, nonce, result: { status: 'error', error, previous: lastData(prev) } })); },
    );
    return () => controller.abort();
  }, [load, nonce]);

  const reload = useCallback(() => setNonce(n => n + 1), []);
  const update = useCallback((change: (data: T) => T) => setSettled(prev =>
    prev && prev.result.status === 'ready' ? { ...prev, result: { status: 'ready', data: change(prev.result.data) } } : prev), []);

  const current = !!settled && settled.load === load && settled.nonce === nonce;
  const state = useMemo((): Async<T> => current && settled ? settled.result : { status: 'loading', previous: lastData(settled) }, [current, settled]);
  return { state, reload, update };
}

function lastData<T>(settled: Settled<T> | null): T | undefined {
  if (!settled) return undefined;
  return settled.result.status === 'ready' ? settled.result.data : settled.result.previous;
}

// The loaded value, or the last one while a reload is in flight.
export function dataOf<T>(state: Async<T>): T | undefined {
  return state.status === 'ready' ? state.data : state.previous;
}
