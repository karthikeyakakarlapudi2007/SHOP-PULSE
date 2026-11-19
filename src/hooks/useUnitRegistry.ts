/**
 * Loads the canonical unit registry once per session (GET /api/v1/units) and shares it.
 * If the request fails the hook reports 'error' and returns no index: callers keep working without
 * suggestions and never substitute a unit. A later mount retries.
 */
import { useEffect, useState } from 'react';
import { unitsApi } from '../api/units';
import { createUnitIndex, type UnitIndex } from '../utils/unitRegistry';

type Status = 'loading' | 'ready' | 'error';

let cached: UnitIndex | null = null;
let pending: Promise<UnitIndex> | null = null;

/** Shared loader (exported for tests). Rejects when the API is unavailable; nothing is substituted. */
export function loadUnitIndex(): Promise<UnitIndex> {
  if (cached) return Promise.resolve(cached);
  if (!pending) {
    pending = unitsApi
      .getRegistry()
      .then((registry) => {
        cached = createUnitIndex(registry);
        return cached;
      })
      .finally(() => {
        pending = null;
      });
  }
  return pending;
}

export function useUnitRegistry(): { index: UnitIndex | null; status: Status } {
  const [index, setIndex] = useState<UnitIndex | null>(cached);
  const [status, setStatus] = useState<Status>(cached ? 'ready' : 'loading');

  useEffect(() => {
    if (cached) return;
    let active = true;
    loadUnitIndex()
      .then((loaded) => {
        if (active) {
          setIndex(loaded);
          setStatus('ready');
        }
      })
      .catch(() => {
        if (active) setStatus('error');
      });
    return () => {
      active = false;
    };
  }, []);

  return { index, status };
}

/** Test helper: forget the cached registry. */
export function resetUnitRegistryCache(): void {
  cached = null;
  pending = null;
}
