"""Response schema of GET /api/v1/units (read-only view of services/unit_registry.py)."""

from typing import List, Literal

from pydantic import BaseModel, Field

UnitKind = Literal["measure", "count", "package"]


class UnitFamilyResponse(BaseModel):
    id: str = Field(..., description="Family id: mass, volume, count, or the package type (packet, box, ...)")
    label: str
    kind: UnitKind
    base_unit: str = Field(..., description="Unit every member converts to (g, ml, pcs; a package is its own base)")
    auto_convertible: bool = Field(..., description="Members convert to each other without product configuration")
    units: List[str]


class UnitResponse(BaseModel):
    id: str = Field(..., description="Canonical unit id (kg, g, L, ml, pcs, dozen, packet, box, bottle, ...)")
    label: str
    family: str
    kind: UnitKind
    base_unit: str
    factor_to_base: int = Field(..., description="Base units in one of this unit (1 kg = 1000 g; 1 dozen = 12 pcs)")
    allows_fraction: bool = Field(..., description="Fractional quantities allowed (kg, g, L, ml); otherwise whole numbers")
    convertible: bool = Field(..., description="Converts automatically within its family; package units never do")
    compatible_units: List[str] = Field(..., description="Units this one converts to without product configuration")
    aliases: List[str] = Field(..., description="Accepted spellings, in normalised form (lower case, no punctuation)")


class UnitRegistryResponse(BaseModel):
    version: int
    max_fraction_digits: int
    families: List[UnitFamilyResponse]
    units: List[UnitResponse]
