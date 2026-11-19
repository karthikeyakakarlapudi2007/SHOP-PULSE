/**
 * Lookup helpers over the canonical unit registry returned by GET /api/v1/units (Phase 4, workstream 1).
 *
 * Every answer comes from the registry data passed in; there is no built-in unit list and no fallback:
 * an unknown unit is reported as unknown (null), never replaced by "pcs". Quantity conversion stays in the
 * backend (exact Decimal arithmetic) and is not done here.
 */
import type { UnitDefinition, UnitRegistry } from '../api/units';

/** Same normalisation as the backend (clean_unit_text): drop punctuation / spaces, lower case. */
export function cleanUnitText(raw: string | null | undefined): string {
  return (raw ?? '').replace(/[^A-Za-z0-9_]/g, '').toLowerCase();
}

export interface UnitIndex {
  /** Canonical unit id for a spelling ("KGS" -> "kg"), or null when it is not a registered unit. */
  normalize(raw: string | null | undefined): string | null;
  get(raw: string | null | undefined): UnitDefinition | null;
  areCompatible(a: string, b: string): boolean;
  allowsFraction(raw: string): boolean | null;
  units: UnitDefinition[];
}

export function createUnitIndex(registry: UnitRegistry): UnitIndex {
  const byId = new Map<string, UnitDefinition>();
  const byAlias = new Map<string, UnitDefinition>();
  for (const unit of registry.units) {
    byId.set(unit.id, unit);
    for (const alias of [cleanUnitText(unit.id), ...unit.aliases]) byAlias.set(alias, unit);
  }
  const get = (raw: string | null | undefined): UnitDefinition | null => {
    const key = cleanUnitText(raw);
    return key ? byAlias.get(key) ?? null : null;
  };
  return {
    normalize: (raw) => get(raw)?.id ?? null,
    get,
    areCompatible: (a, b) => {
      const ua = get(a);
      const ub = get(b);
      return Boolean(ua && ub && ua.family === ub.family);
    },
    allowsFraction: (raw) => get(raw)?.allows_fraction ?? null,
    units: registry.units,
  };
}
