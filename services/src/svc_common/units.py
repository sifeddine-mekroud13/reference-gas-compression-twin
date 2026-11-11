"""OPC UA EUInformation from UNECE Rec. 20 common codes (IEC 62541-8, section 5.6.3).

UnitId is the common code's ASCII characters packed into an Int32, big-endian, so "CEL"
becomes 0x0043454C.
"""

from __future__ import annotations

UNECE_NAMESPACE = "http://www.opcfoundation.org/UA/units/un/cefact"


def unit_id(code: str) -> int:
    value = 0
    for ch in code.upper():
        value = (value << 8) | ord(ch)
    return value
