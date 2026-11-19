/**
 * Phase 4, workstream 1: frontend use of the canonical unit registry.
 * The fixture is the backend registry response; backend/tests/test_unit_registry.py fails if it ever
 * differs from the live registry, so these tests always run against the real unit data.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { UnitRegistry } from '../api/units';
import { cleanUnitText, createUnitIndex } from '../utils/unitRegistry';

const registry: UnitRegistry = JSON.parse(readFileSync(resolve(__dirname, 'fixtures/unit_registry.json'), 'utf8'));

vi.mock('../api/units', () => ({ unitsApi: { getRegistry: vi.fn() } }));

describe('unit index built from the registry response', () => {
  const idx = createUnitIndex(registry);

  it('normalises the approved spellings like the backend', () => {
    const cases: Array<[string, string]> = [
      ['KG', 'kg'], ['KGS', 'kg'], ['kilograms', 'kg'], ['GM', 'g'], ['grams', 'g'], ['LTR', 'L'], ['litre', 'L'],
      ['liters', 'L'], ['ML', 'ml'], ['millilitre', 'ml'], ['PC', 'pcs'], ['pieces', 'pcs'], ['DOZ', 'dozen'],
      ['PKT', 'packet'], ['packets', 'packet'], ['BOX', 'box'], ['boxes', 'box'], ['BTL', 'bottle'], ['bottles', 'bottle'],
      [' Kgs. ', 'kg'], ['L', 'L'],
      // the voice parser's internal unit names resolve too (no separate mapping needed)
      ['piece', 'pcs'], ['packet', 'packet'], ['bottle', 'bottle'], ['dozen', 'dozen'],
    ];
    for (const [raw, id] of cases) expect(idx.normalize(raw), raw).toBe(id);
    for (const unit of registry.units) for (const alias of unit.aliases) expect(idx.normalize(alias)).toBe(unit.id);
  });

  it('reports unknown units as unknown and never substitutes pcs', () => {
    for (const raw of ['xyz', 'units', 'bundle', '', null, undefined, '-']) {
      expect(idx.normalize(raw as string)).toBeNull();
      expect(idx.get(raw as string)).toBeNull();
      expect(idx.allowsFraction(raw as string)).toBeNull();
    }
  });

  it('compatibility and fraction rules come from the registry', () => {
    expect(idx.areCompatible('kg', 'g')).toBe(true);
    expect(idx.areCompatible('dozen', 'pcs')).toBe(true);
    expect(idx.areCompatible('kg', 'L')).toBe(false);
    expect(idx.areCompatible('packet', 'kg')).toBe(false);
    expect(idx.areCompatible('box', 'pcs')).toBe(false);
    expect(idx.areCompatible('xyz', 'xyz')).toBe(false);
    expect(['kg', 'g', 'L', 'ml'].map((u) => idx.allowsFraction(u))).toEqual([true, true, true, true]);
    expect(['pcs', 'dozen', 'packet', 'box', 'bottle'].map((u) => idx.allowsFraction(u))).toEqual([false, false, false, false, false]);
  });

  it('cleans text like the backend (punctuation and spaces removed, lower case)', () => {
    expect(cleanUnitText(' K.G. ')).toBe('kg');
    expect(cleanUnitText(null)).toBe('');
  });
});

describe('registry loading', () => {
  beforeEach(async () => {
    const { resetUnitRegistryCache } = await import('../hooks/useUnitRegistry');
    resetUnitRegistryCache();
  });

  it('loads once and shares the index', async () => {
    const { unitsApi } = await import('../api/units');
    const { loadUnitIndex } = await import('../hooks/useUnitRegistry');
    vi.mocked(unitsApi.getRegistry).mockReset().mockResolvedValue(registry);
    const [a, b] = await Promise.all([loadUnitIndex(), loadUnitIndex()]);
    expect(a).toBe(b);
    expect(a.normalize('kgs')).toBe('kg');
    expect(unitsApi.getRegistry).toHaveBeenCalledTimes(1);
  });

  it('API unavailable: the loader rejects (no substitute registry) and a later call retries', async () => {
    const { unitsApi } = await import('../api/units');
    const { loadUnitIndex } = await import('../hooks/useUnitRegistry');
    vi.mocked(unitsApi.getRegistry).mockReset().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(registry);
    await expect(loadUnitIndex()).rejects.toThrow('offline');
    await expect(loadUnitIndex()).resolves.toBeTruthy();
    expect(unitsApi.getRegistry).toHaveBeenCalledTimes(2);
  });
});

describe('product form uses the registry', () => {
  it('unit suggestions come from the registry; the field stays free text', () => {
    const src = readFileSync(resolve(__dirname, '../components/ProductFormFields.tsx'), 'utf8');
    expect(src).toMatch(/useUnitRegistry\(\)/);
    expect(src).toMatch(/unitIndex\.units\.map/);
    expect(src).toMatch(/type="text"/);
  });
});
