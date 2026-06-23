"""Miner tool config read/write."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_DIR = PROJECT_ROOT / "configs"
VALID_TEMPLATES = ("gatk", "deepvariant", "bcftools")


def list_templates() -> List[Dict[str, str]]:
    items = []
    for name in VALID_TEMPLATES:
        path = CONFIG_DIR / f"{name}.conf"
        items.append({
            "id": name,
            "label": name.upper(),
            "path": str(path.relative_to(PROJECT_ROOT)),
            "exists": path.exists(),
        })
    return items


def read_config(template: str) -> Dict[str, Any]:
    template = template.lower().strip()
    if template not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template: {template}")

    path = CONFIG_DIR / f"{template}.conf"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    return {
        "template": template,
        "path": str(path.relative_to(PROJECT_ROOT)),
        "content": path.read_text(encoding="utf-8"),
        "parsed_count": _parsed_param_count(template),
    }


def write_config(template: str, content: str) -> Dict[str, Any]:
    template = template.lower().strip()
    if template not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template: {template}")

    path = CONFIG_DIR / f"{template}.conf"
    path.write_text(content, encoding="utf-8")

    # Validate by parsing
    from utils.config_loader import extract_tool_options

    options = extract_tool_options(template)
    return {
        "template": template,
        "saved": True,
        "parsed_count": len(options),
        "options_preview": dict(list(options.items())[:8]),
    }


def _parsed_param_count(template: str) -> int:
    try:
        from utils.config_loader import extract_tool_options
        return len(extract_tool_options(template))
    except Exception:
        return 0
