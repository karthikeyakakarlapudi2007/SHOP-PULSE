"""Read-only canonical unit registry (Phase 4, workstream 1). No database access, no mutation."""

from fastapi import APIRouter, Depends

from api import deps
from db.models.user import User
from schemas.units import UnitRegistryResponse
from services.unit_registry import registry_payload

router = APIRouter()


@router.get("", response_model=UnitRegistryResponse)
@router.get("/", response_model=UnitRegistryResponse, include_in_schema=False)
def get_unit_registry(current_user: User = Depends(deps.get_current_user)) -> dict:
    """Every registered unit with its family, base unit, conversion factor, fraction rule and aliases."""
    return registry_payload()
