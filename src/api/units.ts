/**
 * Canonical unit registry (Phase 4, workstream 1): read-only GET /api/v1/units.
 * The backend registry (backend/services/unit_registry.py) is the single source of truth; the frontend
 * keeps no unit list of its own.
 */
import { apiClient } from './client';

export type UnitKind = 'measure' | 'count' | 'package';

export interface UnitFamily {
  id: string;
  label: string;
  kind: UnitKind;
  base_unit: string;
  auto_convertible: boolean;
  units: string[];
}

export interface UnitDefinition {
  id: string;
  label: string;
  family: string;
  kind: UnitKind;
  base_unit: string;
  factor_to_base: number;
  allows_fraction: boolean;
  convertible: boolean;
  compatible_units: string[];
  /** Accepted spellings in normalised form (lower case, letters / digits / underscore only). */
  aliases: string[];
}

export interface UnitRegistry {
  version: number;
  max_fraction_digits: number;
  families: UnitFamily[];
  units: UnitDefinition[];
}

export const unitsApi = {
  getRegistry: () => apiClient.get<UnitRegistry>('/api/v1/units'),
};
