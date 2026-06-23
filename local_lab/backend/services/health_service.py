"""System health checks — wraps neurons.status."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.miner")


def get_health_report(template: Optional[str] = None) -> Dict[str, Any]:
    from neurons.status import run_checks

    tpl = (template or os.getenv("MINER_TEMPLATE", "gatk")).lower().strip()
    report = run_checks("miner", tpl)
    return report.to_dict()


def get_platform_round_status() -> Dict[str, Any]:
    """Best-effort live round snapshot for the dashboard."""
    import asyncio

    platform_url = os.getenv("PLATFORM_URL", "https://api.theminos.ai").rstrip("/")
    out: Dict[str, Any] = {"platform_url": platform_url, "reachable": False}

    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            health = client.get(f"{platform_url}/health")
            out["reachable"] = health.status_code == 200
            out["health_status"] = health.status_code
    except Exception as exc:
        out["error"] = str(exc)
        return out

    # Demo round status does not require wallet when platform allows unauthenticated
    # health; round-status needs auth so we only expose health + instructions here.
    out["demo_hint"] = (
        "Start a demo run from this lab — it uses `python -m neurons.miner --demo` "
        "with an ephemeral keypair against /v2/demo/* endpoints."
    )
    return out
