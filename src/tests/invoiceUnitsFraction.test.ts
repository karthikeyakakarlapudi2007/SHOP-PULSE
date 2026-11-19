/**
 * Phase 4 (finalisation): invoice review units and fractional quantities.
 * Rules come only from the canonical unit registry: the fixture is the backend GET /api/v1/units response,
 * and backend/tests/test_unit_registry.py fails if it ever differs from the live registry.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { UnitRegistry } from '../api/units';
import { createUnitIndex } from '../utils/unitRegistry';
import {
  applyLineEdit,
  fractionalQuantityNotice,
  fractionalUnitList,
  quantityProblem,
  unitBlockNotice,
  unitProblem,
  unitProblemText,
} from '../utils/invoiceReliability';

const registry: UnitRegistry = JSON.parse(readFileSync(resolve(__dirname, 'fixtures/unit_registry.json'), 'utf8'));
const rules = createUnitIndex(registry);
const src = readFileSync(resolve(__dirname, '../pages/InvoiceScanner.tsx'), 'utf8');
const helpers = readFileSync(resolve(__dirname, '../utils/invoiceReliability.ts'), 'utf8');

describe('missing or unregistered invoice units', () => {
  it('a missing unit needs review and is never assumed to be pcs', () => {
    for (const u of ['', '   ', null, undefined]) expect(unitProblem(u, rules)).toBe('missing');
    expect(unitProblemText('', 'missing')).toMatch(/Unit missing/);
  });

  it('an unregistered unit needs review; registered spellings are kept as valid', () => {
    expect(unitProblem('unit', rules)).toBe('unregistered');
    expect(unitProblem('500g pack', rules)).toBe('unregistered');
    expect(unitProblemText('unit', 'unregistered')).toBe("'unit' is not a registered unit: select one");
    for (const u of ['kg', 'KGS', 'ml', 'LTR', 'pcs', 'PKT', 'dozen', 'box', 'bar']) expect(unitProblem(u, rules), u).toBeNull();
  });

  it('blocks confirmation while a selected line has no valid unit, naming the line', () => {
    const n = unitBlockNotice(
      [
        { product_name: 'Toor Dal', quantity: 2.5, unit: '' },
        { product_name: 'Soap', quantity: 4, unit: 'unit' },
        { product_name: 'Salt', quantity: 20, unit: 'pcs' },
      ],
      rules,
    );
    expect(n).toContain('Nothing has been added to stock');
    expect(n).toContain('Toor Dal (unit missing)');
    expect(n).toContain("Soap ('unit' is not a registered unit)");
    expect(n).not.toContain('Salt');
  });

  it('clears once a registered unit is selected', () => {
    expect(unitBlockNotice([{ product_name: 'Toor Dal', quantity: 2.5, unit: 'kg' }], rules)).toBeNull();
  });

  it('blocks rather than guesses when the registry could not be loaded', () => {
    expect(unitBlockNotice([{ product_name: 'Salt', quantity: 1, unit: 'pcs' }], null)).toMatch(/could not be loaded/);
  });

  it('correcting the unit keeps the extracted quantity, rate and amount', () => {
    const line = { quantity: 2.5, unit: '', purchase_price: 44, amount: 110, is_free_item: false, extracted_quantity: 2.5 };
    const fixed = applyLineEdit(line, 'unit', 'kg');
    expect(fixed).toEqual({ ...line, unit: 'kg' });
  });
});

describe('fractional quantities follow the unit registry', () => {
  it('kg, g, L and ml accept up to 3 decimals', () => {
    for (const [q, u] of [[2.5, 'kg'], [750, 'ml'], [0.75, 'L'], [0.125, 'kg'], [2.75, 'KGS'], [12.5, 'g']] as const) {
      expect(quantityProblem({ quantity: q, unit: u }, rules), `${q} ${u}`).toBeNull();
    }
    expect(quantityProblem({ quantity: 5.5, paid_quantity: 5, free_quantity: 0.5, unit: 'kg' }, rules)).toBeNull();
    expect(quantityProblem({ quantity: 1.2345, unit: 'kg' }, rules)).toBe('too_many_decimals');
  });

  it('pcs, dozen, packages, quintal and tonne stay whole numbers (never rounded)', () => {
    for (const u of ['pcs', 'nos', 'dozen', 'packet', 'box', 'bottle', 'bag', 'qtl', 'ton']) {
      expect(quantityProblem({ quantity: 2.5, unit: u }, rules), u).toBe('whole_only');
      expect(quantityProblem({ quantity: 3, unit: u }, rules), u).toBeNull();
    }
    expect(quantityProblem({ quantity: 11, paid_quantity: 10.5, free_quantity: 0.5, unit: 'pcs' }, rules)).toBe('whole_only');
  });

  it('the unit problem is reported first; a fraction with no unit is not judged yet', () => {
    expect(quantityProblem({ quantity: 2.5, unit: '' }, rules)).toBeNull();
    expect(quantityProblem({ quantity: 2.5, unit: 'kg' }, null)).toBeNull();
  });

  it('the fractional unit list and the block message come from the registry', () => {
    expect(fractionalUnitList(rules)).toBe('kg, g, L, ml');
    const n = fractionalQuantityNotice(
      [
        { product_name: 'Gift Box', quantity: 2.5, unit: 'packet' },
        { product_name: 'Sugar', quantity: 2.5, unit: 'kg' },
      ],
      rules,
    );
    expect(n).toContain('allowed only for kg, g, L, ml');
    expect(n).toContain('Gift Box (2.5 packet): packet is counted in whole numbers');
    expect(n).toContain('Nothing has been added to stock');
    expect(n).not.toContain('Sugar');
    expect(fractionalQuantityNotice([{ product_name: 'Sugar', quantity: 2.5, unit: 'kg' }], rules)).toBeNull();
  });
});

describe('review screen uses the canonical registry (source)', () => {
  it('loads units from the registry hook and offers them in a select', () => {
    expect(src).toMatch(/useUnitRegistry\(\)/);
    expect(src).toMatch(/data-testid="unit-select"/);
    expect(src).toMatch(/unitIndex\?\.units \?\? \[\]\)\.map/);
    expect(src).toMatch(/data-testid="unit-warning"/);
    expect(src).toMatch(/data-testid="unit-block"/);
  });

  it('no silent default unit for extracted lines and none in the confirm payload', () => {
    expect(src).not.toMatch(/item\.unit \|\| 'unit'/);
    expect(src).not.toMatch(/i\.unit\?\.trim\(\) \|\| 'pcs'/);
    expect(src).toMatch(/unit: i\.unit\.trim\(\)/);
  });

  it('the quantity step follows the unit (fractions only where allowed)', () => {
    expect(src).toMatch(/step=\{fractionAllowed \? '0\.001' : '1'\}/);
  });

  it('keeps no unit list of its own', () => {
    for (const text of [src, helpers]) {
      expect(text).not.toMatch(/\[\s*'kg',\s*'g'/);
      expect(text).not.toMatch(/\['pcs',/);
    }
  });
});
