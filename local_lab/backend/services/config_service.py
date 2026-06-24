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


def write_config(template: str, content: str, source: str = "manual_edit") -> Dict[str, Any]:
    template = template.lower().strip()
    if template not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template: {template}")

    path = CONFIG_DIR / f"{template}.conf"
    old_content = ""
    if path.exists():
        old_content = path.read_text(encoding="utf-8")

    path.write_text(content, encoding="utf-8")

    # Log the change
    try:
        log_config_change(template, old_content, content, source=source)
    except Exception:
        pass

    # Validate by parsing
    from utils.config_loader import extract_tool_options

    options = extract_tool_options(template)
    return {
        "template": template,
        "saved": True,
        "parsed_count": len(options),
        "options_preview": dict(list(options.items())[:8]),
    }


def log_config_change(template: str, old_content: str, new_content: str, source: str = "manual_edit") -> None:
    import json
    import uuid
    from datetime import datetime, timezone

    path = _get_history_path()
    history = read_config_history()

    # Parse parameter dicts to find differences
    from utils.config_loader import _parse_value

    def get_params(content_str: str):
        params = {}
        for line in content_str.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            params[k.strip()] = _parse_value(v.strip())
        return params

    old_params = get_params(old_content)
    new_params = get_params(new_content)

    changed_params = []
    changes = []
    all_keys = set(old_params.keys()) | set(new_params.keys())
    for k in all_keys:
        old_val = old_params.get(k)
        new_val = new_params.get(k)
        if old_val != new_val:
            changed_params.append(k)
            changes.append({
                "param": k,
                "old_value": old_val,
                "new_value": new_val
            })

    # Only record if something actually changed!
    if not changed_params:
        return

    record = {
        "id": f"cfg_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "template": template,
        "old_content": old_content,
        "new_content": new_content,
        "changed_params": sorted(changed_params),
        "changes": sorted(changes, key=lambda x: x["param"]),
        "source": source,
    }
    history.append(record)
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def read_config_history() -> List[Dict[str, Any]]:
    import json
    path = _get_history_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _get_history_path() -> Path:
    cache_dir = PROJECT_ROOT / "local_lab" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "config_history.json"


def _parsed_param_count(template: str) -> int:
    try:
        from utils.config_loader import extract_tool_options
        return len(extract_tool_options(template))
    except Exception:
        return 0
