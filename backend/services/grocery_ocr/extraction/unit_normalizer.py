"""
Unit normalization service for grocery invoice items.
Standardizes retail and wholesale measurement units while preserving verbatim printed units.
Strictly prohibits unverified unit conversions (e.g. BOR to PCS or PET to Liters).
"""

import re
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from services.grocery_ocr.config import GroceryOCRConfig, default_config
from services.grocery_ocr.logger import get_logger
from services.unit_registry import ocr_alias_map

logger = get_logger("extraction.unit_normalizer")

# Canonical unit mapping (alias -> OCR code, e.g. "kgs" -> "KG", "bottle" -> "PET").
# Derived from the canonical unit registry (services/unit_registry.py), which now holds every alias
# that used to be listed here; the OCR codes and their meaning are unchanged.
CANONICAL_UNITS: Dict[str, str] = ocr_alias_map()


class UnitNormalizationResult(BaseModel):
    """Result of unit normalization."""
    normalized_unit: Optional[str] = Field(None, description="Standardized canonical unit (e.g. PCS, KG, BOR, PET)")
    raw_unit: Optional[str] = Field(None, description="Original verbatim unit as printed")
    confidence: float = Field(default=100.0, ge=0.0, le=100.0, description="Confidence in unit recognition")
    is_recognized: bool = Field(default=True, description="True if unit is in canonical grocery taxonomy")


class UnitNormalizer:
    """
    Standardizes grocery measurement units without mutating or converting physical magnitudes.
    """

    def __init__(self, config: Optional[GroceryOCRConfig] = None):
        self.config = config or default_config

    def normalize(self, raw_unit: Optional[str]) -> UnitNormalizationResult:
        """
        Normalizes a raw unit string into its canonical representation.

        Args:
            raw_unit: Original string from invoice unit column or token (e.g. 'pcs', 'Bora', 'KGS', 'Pet').

        Returns:
            UnitNormalizationResult.
        """
        if not raw_unit:
            return UnitNormalizationResult(normalized_unit=None, raw_unit=None, confidence=0.0, is_recognized=False)

        raw = raw_unit.strip()
        if raw in ("-", "--", ".", "|", "/", "NA", "N/A"):
            return UnitNormalizationResult(normalized_unit=None, raw_unit=raw, confidence=100.0, is_recognized=False)

        clean = re.sub(r"[^\w]", "", raw).lower()
        if not clean:
            return UnitNormalizationResult(normalized_unit=None, raw_unit=raw, confidence=0.0, is_recognized=False)

        if clean in CANONICAL_UNITS:
            return UnitNormalizationResult(
                normalized_unit=CANONICAL_UNITS[clean],
                raw_unit=raw,
                confidence=100.0,
                is_recognized=True,
            )

        # Unrecognized custom unit (e.g. proprietary wholesale packaging)
        # Preserve verbatim in uppercase, do not invent conversion
        return UnitNormalizationResult(
            normalized_unit=clean.upper(),
            raw_unit=raw,
            confidence=60.0,
            is_recognized=False,
        )

