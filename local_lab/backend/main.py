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
from local_lab.backend.services.leaderboard_service import (
    compute_analytics,
    get_leaderboard,
    get_miner_history,
    get_network_status,
    list_rounds,
    sync_all_finalized,
)
from local_lab.backend.services.llm_tune_service import get_llm_tune_status
from local_lab.backend.services.tune_service import apply_tune_recommendations, run_llm_judge, run_tune_pipeline
from local_lab.backend.services.vcf_service import find_latest_vcf, summarize_vcf
from local_lab.backend.services.eval_service import (
    attach_ground_truth,
    check_prerequisites,
    ensure_chrom_sdf,
    eval_manager,
    fetch_demo_task_from_platform,
    fetch_platform_task,
    generate_truth_for_task,
    get_eval_history,
    get_task,
    import_task_directory,
    list_tasks,
    prepare_builtin_task,
    scan_miner_downloads,
    scan_scoring_cache,
)

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


class TuneApplyRequest(BaseModel):
    template: str = Field(default="gatk", pattern="^(gatk|deepvariant|bcftools)$")
    recommendations: list[dict] = Field(default_factory=list)


class LlmJudgeRequest(BaseModel):
    template: str = Field(default="gatk", pattern="^(gatk|deepvariant|bcftools)$")
    current_config: dict = Field(default_factory=dict)
    diagnosis: dict = Field(default_factory=dict)
    rule_recommendations: list[dict] = Field(default_factory=list)
    top_miner_summary: dict = Field(default_factory=dict)
    my_performance: dict | None = None
    last_update_analysis: dict | None = None
    region_analysis: dict | None = None
    logs: list[dict] = Field(default_factory=list)


class EvalRunRequest(BaseModel):
    task_id: str = Field(..., min_length=1)
    template: str = Field(default="gatk", pattern="^(gatk|deepvariant|bcftools)$")
    mode: str = Field(default="full", pattern="^(full|score_only)$")
    query_vcf: str | None = None


class EvalPrepareRequest(BaseModel):
    task_id: str = Field(..., min_length=1)


class EvalPlatformFetchRequest(BaseModel):
    round_id: str = Field(..., min_length=8)


class EvalImportRequest(BaseModel):
    source_dir: str = Field(..., min_length=1)
    name: str | None = None


class EvalAttachTruthRequest(BaseModel):
    task_id: str = Field(..., min_length=1)
    truth_vcf: str = Field(..., min_length=1)
    mutations_vcf: str = Field(..., min_length=1)


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


# --- Leaderboard / analytics (public platform API) ---

@app.get("/api/leaderboard/rounds")
def api_leaderboard_rounds(limit: int = 100):
    try:
        return list_rounds(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/leaderboard")
def api_leaderboard(round_id: str | None = None, mode: str = "latest"):
    try:
        return get_leaderboard(round_id=round_id, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/leaderboard/sync")
def api_leaderboard_sync(force: bool = False, max_rounds: int = 50):
    try:
        return sync_all_finalized(force=force, max_rounds=max_rounds)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/leaderboard/analytics")
def api_leaderboard_analytics(sync: bool = False):
    try:
        return compute_analytics(force_sync=sync)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/leaderboard/miner/{hotkey}")
def api_leaderboard_miner(hotkey: str):
    try:
        return get_miner_history(hotkey)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/leaderboard/my-hotkey")
def api_leaderboard_my_hotkey():
    from local_lab.backend.services.leaderboard_service import get_my_coldkey, get_my_hotkey
    hk = get_my_hotkey()
    return {"hotkey": hk, "coldkey": get_my_coldkey(), "configured": hk is not None}


@app.get("/api/tune/llm-status")
def api_tune_llm_status():
    return get_llm_tune_status()


@app.get("/api/tune/analyze")
def api_tune_analyze(
    template: str = "gatk",
    rounds: int = 30,
    sync: bool = False,
    use_llm: bool = False,
):
    try:
        return run_tune_pipeline(
            template=template,
            rounds_limit=rounds,
            force_sync=sync,
            use_llm=use_llm,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/tune/llm-judge")
def api_tune_llm_judge(body: LlmJudgeRequest):
    try:
        params = body.current_config.get("params") if isinstance(body.current_config, dict) else {}
        if not params and isinstance(body.current_config, dict):
            params = body.current_config
        return run_llm_judge(
            template=body.template,
            current_params=params,
            diagnosis=body.diagnosis,
            rule_recommendations=body.rule_recommendations,
            top_summary=body.top_miner_summary,
            my_perf=body.my_performance,
            last_update_analysis=body.last_update_analysis,
            region_analysis=body.region_analysis,
            prior_logs=body.logs,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/tune/apply")
def api_tune_apply(body: TuneApplyRequest):
    try:
        return apply_tune_recommendations(body.template, body.recommendations)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/leaderboard/status")
def api_leaderboard_status():
    try:
        return get_network_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --- Local eval (validator-parity scoring) ---

@app.get("/api/eval/tasks")
def api_eval_tasks(refresh: bool = True):
    try:
        return list_tasks(refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/eval/tasks/scan-cache")
def api_eval_scan_cache():
    try:
        scoring = scan_scoring_cache()
        miner = scan_miner_downloads()
        return {
            "imported": len(scoring) + len(miner),
            "scoring_cache": len(scoring),
            "miner_downloads": len(miner),
            "tasks": list_tasks(refresh=False),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/eval/tasks/fetch-demo")
async def api_eval_fetch_demo():
    try:
        return await fetch_demo_task_from_platform()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/eval/prerequisites/download-sdf")
def api_eval_download_sdf(chrom: str = "chr20"):
    try:
        return ensure_chrom_sdf(chrom)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/eval/tasks/generate-truth")
def api_eval_generate_truth(task_id: str, force: bool = False):
    try:
        return generate_truth_for_task(task_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/eval/tasks/attach-truth")
def api_eval_attach_truth(body: EvalAttachTruthRequest):
    try:
        return attach_ground_truth(body.task_id, body.truth_vcf, body.mutations_vcf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/eval/tasks/prepare")
def api_eval_prepare(body: EvalPrepareRequest):
    try:
        return prepare_builtin_task(body.task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/eval/tasks/fetch-platform")
async def api_eval_fetch_platform(body: EvalPlatformFetchRequest):
    try:
        return await fetch_platform_task(body.round_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/eval/tasks/import")
def api_eval_import(body: EvalImportRequest):
    try:
        return import_task_directory(body.source_dir, name=body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/eval/prerequisites")
def api_eval_prerequisites(task_id: str):
    try:
        return check_prerequisites(task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/eval/tasks/{task_id}")
def api_eval_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/eval/run")
def api_eval_run(body: EvalRunRequest):
    try:
        record = eval_manager.start_eval(
            task_id=body.task_id,
            template=body.template,
            mode=body.mode,
            query_vcf=body.query_vcf,
        )
        return record.to_dict()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/eval/runs")
def api_eval_runs():
    return {"runs": eval_manager.list_runs()}


@app.get("/api/eval/runs/{run_id}")
def api_eval_run(run_id: str):
    record = eval_manager.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    return record.to_dict()


@app.get("/api/eval/runs/{run_id}/logs")
async def api_eval_run_logs(run_id: str):
    record = eval_manager.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    return StreamingResponse(
        eval_manager.stream_logs(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/eval/latest")
def api_eval_latest():
    result = eval_manager.get_latest_result()
    if not result:
        return {"found": False, "message": "No eval results yet — run local eval first"}
    return {"found": True, **result}


@app.get("/api/eval/history")
def api_eval_history(limit: int = 30):
    return get_eval_history(limit=limit)


# Serve built frontend when available
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
