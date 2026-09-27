"""Offline checks for a future resolver-produced XLSX environment candidate.

The current 27-package authority remains in check_current_protected_environment.
No candidate validated here is promoted or installed by this module.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts import check_current_protected_environment as current


SPEC = Path(__file__).resolve().parents[1] / "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR_DIRECT_SPEC.txt"


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def validate_direct_spec() -> dict[str, str]:
    """Bind all existing pins exactly to the reviewed current authority."""
    authority = current.resolve_historical_v10c_authority()
    if authority["status"] != "PASS" or authority["package_count"] != 27:
        raise ValueError("CURRENT_27_PACKAGE_AUTHORITY_INVALID")
    base = authority["package_map"]
    direct: dict[str, str] = {}
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            raise ValueError("DIRECT_SPEC_LINE_INVALID")
        name, separator, version = line.partition("==")
        normalized = _name(name)
        if normalized != name or normalized in direct:
            raise ValueError("DIRECT_SPEC_IDENTITY_INVALID")
        if separator and not version:
            raise ValueError("DIRECT_SPEC_PIN_INVALID")
        direct[name] = version if separator else ""
    if set(direct) != set(base) | {"openpyxl"}:
        raise ValueError("DIRECT_SPEC_SET_INVALID")
    if any(direct[name] != version for name, version in base.items()):
        raise ValueError("CURRENT_PIN_DRIFT")
    if direct["openpyxl"]:
        raise ValueError("UNRESOLVED_VERSION_GUESSED")
    return base
