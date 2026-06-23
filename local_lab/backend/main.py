"""Minos Local Lab — FastAPI backend for miner testing."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from local_lab.backend.services.config_service import (
    list_templates,
    read_config,
    write_config,
)
from local_lab.backend.services.health_service import (
    get_health_report,
    get_platform_round_status,
)
from local_lab.backend.services.run_service import run_manager
from local_lab.backend.services.vcf_service import find_latest_vcf, summarize_vcf

app = FastAPI(
    title="Minos Local Lab",
    description="Local miner testing dashboard for Minos SN107",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConfigSaveRequest(BaseModel):
    content: str = Field(..., min_length=1)


class DemoStartRequest(BaseModel):
    template: str = Field(default="gatk", pattern="^(gatk|deepvariant|bcftools)$")


@app.get("/api/meta")
def api_meta():
    return {
        "name": "Minos Local Lab",
        "version": "0.1.0",
        "project_root": str(PROJECT_ROOT),
        "official_dashboard": "https://theminos.ai/",
        "platform_api": "https://api.theminos.ai",
    }


@app.get("/api/health")
def api_health(template: str = "gatk"):
    try:
        return get_health_report(template)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/platform")
def api_platform():
    return get_platform_round_status()


@app.get("/api/templates")
def api_templates():
    return {"templates": list_templates()}


@app.get("/api/config/{template}")
def api_get_config(template: str):
    try:
        return read_config(template)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/config/{template}")
def api_put_config(template: str, body: ConfigSaveRequest):
    try:
        return write_config(template, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
def api_list_runs():
    return {"runs": run_manager.list_runs()}


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: str):
    record = run_manager.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    return record.to_dict()


@app.post("/api/runs/demo")
async def api_start_demo(body: DemoStartRequest):
    try:
        record = await run_manager.start_demo(body.template)
        return record.to_dict()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/stop")
async def api_stop_run(run_id: str):
    try:
        record = await run_manager.stop_run(run_id)
        return record.to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/runs/{run_id}/logs")
async def api_run_logs(run_id: str):
    record = run_manager.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")

    return StreamingResponse(
        run_manager.stream_logs(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/results/latest")
def api_latest_results():
    output_dir = PROJECT_ROOT / "output"
    vcf = find_latest_vcf(output_dir)
    if not vcf:
        return {"found": False, "message": "No output.vcf.gz yet — run a demo first"}
    try:
        summary = summarize_vcf(vcf)
        return {"found": True, **summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Serve built frontend when available
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
