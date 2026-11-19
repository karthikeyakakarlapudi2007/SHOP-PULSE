"""Quantity type for API schemas (Phase 4, fractional inventory).

Stock and line quantities may be fractional for kg, g, L and ml (2.5 kg). In JSON a whole quantity stays
an integer (5, not 5.0) so existing clients see the same values as before; a fractional one is a number
with up to 3 decimals.
"""

from typing import Annotated, Optional, Union

from pydantic import PlainSerializer


def _serialize_quantity(value: Optional[float]) -> Optional[Union[int, float]]:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else round(number, 3)


Quantity = Annotated[float, PlainSerializer(_serialize_quantity, return_type=Optional[Union[int, float]])]
