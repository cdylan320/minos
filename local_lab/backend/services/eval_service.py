"""Local eval — validator-parity scoring for config tuning."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import math
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.miner")

from base import BASE_DIR, GENOMICS_CONFIG
from templates import load_template
from utils.config_loader import extract_tool_options
from utils.file_utils import download_file_with_fallback
from utils.path_utils import safe_round_dir_name
from utils.scoring import AdvancedScorer, HappyScorer

logger = logging.getLogger(__name__)

LAB_DIR = PROJECT_ROOT / "local_lab"
EVAL_CACHE = LAB_DIR / ".cache" / "eval_tasks"
EVAL_HISTORY_PATH = LAB_DIR / ".cache" / "eval_history.json"
EVAL_RUNS_DIR = LAB_DIR / ".eval_runs"
MANIFEST_PATH = LAB_DIR / "eval_tasks" / "manifest.json"
REGISTRY_PATH = EVAL_CACHE / "registry.json"
REF_S3_BASE = "https://api.theminos.ai/reference"

# RTG SDF files required for hap.py vcfeval (matches setup.py)
_SDF_FILES = [
    "done", "mainIndex",
    "nameIndex0", "namedata0", "namepointer0",
    "progress", "seqdata0", "seqpointer0",
    "sequenceIndex0", "summary.txt",
]

ALLOWED_CONFIG_KEYS = {
    "tool",
    "version",
    "gatk_options",
    "deepvariant_options",
    "freebayes_options",
    "bcftools_options",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_round_score(value, *, label: str) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        logger.warning("Skipping %s: invalid combined_final=%r", label, value)
        return None
    if not math.isfinite(score) or score <= 0.0 or score > 1.0:
        logger.warning("Skipping %s: out-of-range combined_final=%r", label, score)
        return None
    return score


def _is_zero_input_advanced_fingerprint(metrics: dict, combined_final: float) -> bool:
    return (
        (metrics.get("f1_snp") or 0.0) == 0.0
        and (metrics.get("f1_indel") or 0.0) == 0.0
        and 0.24999 <= combined_final <= 0.25001
    )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _config_fingerprint(template: str) -> str:
    path = PROJECT_ROOT / "configs" / f"{template}.conf"
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _resolve_reference(chrom: str) -> tuple[Optional[Path], Optional[Path]]:
    ref_path = BASE_DIR / "datasets" / "reference" / chrom / f"{chrom}.fa"
    ref_sdf_path = BASE_DIR / "datasets" / "reference" / chrom / f"{chrom}.sdf"
    if not ref_path.exists() and chrom == "chr20":
        legacy = BASE_DIR / "datasets" / "reference" / "chr20.fa"
        if legacy.exists():
            ref_path = legacy
            ref_sdf_path = BASE_DIR / "datasets" / "reference" / "chr20.sdf"
    if not ref_path.exists():
        return None, None
    return ref_path, ref_sdf_path if ref_sdf_path.exists() else None


def _count_vcf_variants(vcf_path: Path) -> int:
    if not vcf_path.exists():
        return 0
    count = 0
    opener = gzip.open if str(vcf_path).endswith(".gz") else open
    with opener(vcf_path, "rt") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            count += 1
    return count


def _load_manifest() -> dict:
    return _read_json(MANIFEST_PATH, {"tasks": []})


def _load_registry() -> dict:
    return _read_json(REGISTRY_PATH, {"tasks": {}})


def _save_registry(registry: dict) -> None:
    _write_json(REGISTRY_PATH, registry)


def _task_dir(task_id: str) -> Path:
    return EVAL_CACHE / task_id


def _task_ready(task: dict) -> bool:
    paths = task.get("paths") or {}
    required = ["bam", "truth_vcf", "mutations_vcf"]
    for key in required:
        p = paths.get(key)
        if not p or not Path(p).exists():
            return False
    return True


def _chrom_from_region(region: str) -> str:
    return region.split(":")[0] if region else "chr20"


def scan_scoring_cache() -> List[dict]:
    """Discover complete validator scoring directories under output/scoring/."""
    scoring_root = PROJECT_ROOT / "output" / "scoring"
    found: List[dict] = []
    if not scoring_root.exists():
        return found

    for work_dir in sorted(scoring_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not work_dir.is_dir():
            continue
        bam = work_dir / "round.bam"
        truth = work_dir / "truth.vcf.gz"
        mutations = work_dir / "mutations.vcf.gz"
        if not (bam.exists() and truth.exists() and mutations.exists()):
            continue

        meta_path = work_dir / "task_meta.json"
        meta = _read_json(meta_path, {})
        region = meta.get("region") or meta.get("region_string") or ""
        round_id = meta.get("round_id") or work_dir.name.replace("round_", "").replace("_", ":")
        task_id = f"scoring_{work_dir.name}"

        chrom = _chrom_from_region(region) if region else "chr20"
        ref_path, ref_sdf_path = _resolve_reference(chrom)

        entry = {
            "id": task_id,
            "name": f"Validator cache · {work_dir.name}",
            "description": "Imported from output/scoring — production-identical artifacts.",
            "source": "scoring_cache",
            "region": region,
            "chrom": chrom,
            "round_id": round_id,
            "ready": True,
            "paths": {
                "work_dir": str(work_dir),
                "bam": str(bam),
                "truth_vcf": str(truth),
                "mutations_vcf": str(mutations),
                "ref": str(ref_path) if ref_path else None,
                "ref_sdf": str(ref_sdf_path) if ref_sdf_path else None,
            },
            "num_mutations": _count_vcf_variants(mutations),
            "truth_variants": _count_vcf_variants(truth),
        }
        found.append(entry)

        registry = _load_registry()
        registry["tasks"][task_id] = entry
        _save_registry(registry)

    return found


def scan_miner_downloads() -> List[dict]:
    """Discover BAMs downloaded by the miner (output/**/input.bam)."""
    output_root = PROJECT_ROOT / "output"
    found: List[dict] = []
    if not output_root.exists():
        return found

    for bam in sorted(output_root.rglob("input.bam"), key=lambda p: p.stat().st_mtime, reverse=True):
        work_dir = bam.parent
        if "scoring" in work_dir.parts:
            continue

        meta = _read_json(work_dir / "task_meta.json", {})
        if not meta:
            meta = _read_json(work_dir / "output.meta.json", {})

        region = meta.get("region") or meta.get("region_string") or ""
        round_id = meta.get("round_id") or ""
        vcf = work_dir / "output.vcf.gz"
        task_id = f"miner_bam_{hashlib.sha256(str(work_dir).encode()).hexdigest()[:10]}"

        if not region and round_id.startswith("2026-01-01"):
            region = "chr20:46254744-51254744"
        if not region:
            region = "unknown"

        chrom = _chrom_from_region(region) if region != "unknown" else "chr20"
        ref_path, ref_sdf_path = _resolve_reference(chrom)

        paths: Dict[str, str] = {
            "work_dir": str(work_dir),
            "bam": str(bam),
            "ref": str(ref_path) if ref_path else "",
            "ref_sdf": str(ref_sdf_path) if ref_sdf_path else "",
        }
        if vcf.exists():
            paths["query_vcf"] = str(vcf)

        has_truth = (work_dir / "truth.vcf.gz").exists() and (work_dir / "mutations.vcf.gz").exists()
        if has_truth:
            paths["truth_vcf"] = str(work_dir / "truth.vcf.gz")
            paths["mutations_vcf"] = str(work_dir / "mutations.vcf.gz")

        bam_gb = bam.stat().st_size / (1024 ** 3)
        entry = {
            "id": task_id,
            "name": f"Miner BAM · {work_dir.name}",
            "description": (
                f"input.bam ({bam_gb:.2f} GB) from miner download. "
                + ("Truth attached — ready to score." if has_truth else "Needs truth + mutations VCF to score.")
            ),
            "source": "miner_download",
            "region": region,
            "chrom": chrom,
            "round_id": round_id or None,
            "ready": _task_ready({"paths": paths}),
            "bam_only": not has_truth,
            "paths": paths,
            "has_vcf": vcf.exists(),
        }
        found.append(entry)

        registry = _load_registry()
        registry["tasks"][task_id] = entry
        _save_registry(registry)

    return found[:10]


def scan_demo_outputs() -> List[dict]:
    """Register demo miner outputs that can pair with a prepared truth bundle."""
    output_root = PROJECT_ROOT / "output"
    found: List[dict] = []
    if not output_root.exists():
        return found

    for round_dir in sorted(output_root.rglob("output.vcf.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        vcf = round_dir
        work_dir = vcf.parent
        if "scoring" in work_dir.parts:
            continue
        bam_candidates = list(work_dir.glob("*.bam"))
        if not bam_candidates:
            continue
        bam = bam_candidates[0]
        meta = _read_json(work_dir / "output.meta.json", {})
        region = meta.get("region") or "chr20:46254744-51254744"
        task_id = f"demo_output_{hashlib.sha256(str(work_dir).encode()).hexdigest()[:10]}"
        chrom = _chrom_from_region(region)
        ref_path, ref_sdf_path = _resolve_reference(chrom)

        entry = {
            "id": task_id,
            "name": f"Demo output · {work_dir.name}",
            "description": "VCF + BAM from a demo run. Score-only once truth/mutations are prepared for this region.",
            "source": "demo_output",
            "region": region,
            "chrom": chrom,
            "ready": False,
            "score_only": True,
            "paths": {
                "work_dir": str(work_dir),
                "bam": str(bam),
                "query_vcf": str(vcf),
                "ref": str(ref_path) if ref_path else None,
                "ref_sdf": str(ref_sdf_path) if ref_sdf_path else None,
            },
            "variant_count": _count_vcf_variants(vcf),
        }
        found.append(entry)

    return found[:5]


def list_tasks(refresh: bool = True) -> dict:
    if refresh:
        scan_scoring_cache()
        scan_miner_downloads()
        scan_demo_outputs()

    manifest = _load_manifest()
    registry = _load_registry()
    by_id: Dict[str, dict] = {}

    for t in manifest.get("tasks", []):
        tid = t["id"]
        entry = dict(t)
        cached = registry.get("tasks", {}).get(tid)
        if cached:
            entry.update(cached)
        entry.setdefault("source", "builtin")
        entry["ready"] = _task_ready(entry)
        by_id[tid] = entry

    for tid, cached in registry.get("tasks", {}).items():
        if tid not in by_id:
            by_id[tid] = {**cached, "ready": _task_ready(cached)}

    tasks = sorted(by_id.values(), key=lambda x: (not x.get("ready"), x.get("name", "")))
    ready_count = sum(1 for t in tasks if t.get("ready"))

    return {
        "tasks": tasks,
        "ready_count": ready_count,
        "total_count": len(tasks),
        "manifest_path": str(MANIFEST_PATH),
        "cache_dir": str(EVAL_CACHE),
    }


def get_task(task_id: str) -> Optional[dict]:
    data = list_tasks(refresh=True)
    for t in data["tasks"]:
        if t.get("id") == task_id:
            return t
    return None


def check_prerequisites(task_id: str) -> dict:
    task = get_task(task_id)
    if not task:
        return {"ok": False, "error": f"Task not found: {task_id}"}

    region = task.get("region") or ""
    chrom = task.get("chrom") or _chrom_from_region(region)
    ref_path, ref_sdf_path = _resolve_reference(chrom)

    checks: List[dict] = []
    checks.append({
        "name": "Task artifacts",
        "status": "pass" if _task_ready(task) else "fail",
        "detail": (
            "truth.vcf.gz + mutations.vcf.gz + BAM present"
            if _task_ready(task)
            else (
                "BAM present — attach truth.vcf.gz + mutations.vcf.gz to score "
                "(platform does not send these to miners)"
                if task.get("bam_only") or (task.get("paths") or {}).get("bam")
                else "Missing BAM + truth/mutations — fetch demo task or import"
            )
        ),
    })
    checks.append({
        "name": f"Reference FASTA ({chrom})",
        "status": "pass" if ref_path and ref_path.exists() else "fail",
        "detail": str(ref_path) if ref_path else f"Missing datasets/reference/{chrom}/{chrom}.fa",
    })
    checks.append({
        "name": f"RTG SDF ({chrom})",
        "status": "pass" if ref_sdf_path and ref_sdf_path.exists() else "fail",
        "detail": "Required for hap.py vcfeval — run setup.py as validator or download SDF",
    })

    try:
        from base import is_docker_available
        docker_ok = is_docker_available()
    except Exception:
        docker_ok = False
    checks.append({
        "name": "Docker",
        "status": "pass" if docker_ok else "fail",
        "detail": "Docker required for hap.py and variant calling",
    })

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "ok": len(failed) == 0 and _task_ready(task),
        "task_id": task_id,
        "region": region,
        "chrom": chrom,
        "checks": checks,
        "ref_path": str(ref_path) if ref_path else None,
        "ref_sdf_path": str(ref_sdf_path) if ref_sdf_path else None,
    }


def prepare_builtin_task(task_id: str) -> dict:
    manifest = _load_manifest()
    spec = next((t for t in manifest.get("tasks", []) if t.get("id") == task_id), None)
    if not spec:
        raise ValueError(f"Unknown builtin task: {task_id}")

    dest = _task_dir(task_id)
    dest.mkdir(parents=True, exist_ok=True)
    log: List[str] = []

    base_url = spec.get("files_base_url", "").rstrip("/")
    file_map = spec.get("files") or {}
    paths: Dict[str, str] = {"work_dir": str(dest)}

    logical_to_path = {
        "bam": "bam",
        "bam_index": "bam_index",
        "truth_vcf": "truth_vcf",
        "truth_vcf_index": "truth_vcf_index",
        "mutations_vcf": "mutations_vcf",
        "mutations_vcf_index": "mutations_vcf_index",
    }

    for logical, filename in file_map.items():
        local = dest / filename
        url = f"{base_url}/{filename}"
        optional = logical.endswith("_index") or logical == "bam_index"
        if logical in ("bam", "truth_vcf", "mutations_vcf"):
            log.append(f"Downloading {filename}...")
        ok = download_file_with_fallback(url, local, backup_url=None, show_progress=logical == "bam")
        if logical in ("bam", "truth_vcf", "mutations_vcf"):
            if not ok or not local.exists() or local.stat().st_size == 0:
                raise RuntimeError(
                    f"Failed to download {filename} from {url}. "
                    "The eval bundle may not be published yet — import from validator cache "
                    "or fetch a scoring-round task with a validator wallet."
                )
        elif optional and not ok:
            continue
        if local.exists():
            key = logical_to_path.get(logical, logical)
            paths[key] = str(local)

    chrom = spec.get("chrom") or _chrom_from_region(spec.get("region", ""))
    ref_path, ref_sdf_path = _resolve_reference(chrom)
    if ref_path:
        paths["ref"] = str(ref_path)
    if ref_sdf_path:
        paths["ref_sdf"] = str(ref_sdf_path)

    entry = {
        **spec,
        "ready": _task_ready({"paths": paths}),
        "paths": paths,
        "prepared_at": _now_iso(),
    }
    registry = _load_registry()
    registry["tasks"][task_id] = entry
    _save_registry(registry)

    return {"task": entry, "log": log}


def ensure_chrom_sdf(chrom: str = "chr20") -> dict:
    """Download RTG SDF directory for a chromosome (required for hap.py)."""
    sdf_dir = BASE_DIR / "datasets" / "reference" / chrom / f"{chrom}.sdf"
    missing = []
    for fname in _SDF_FILES:
        local = sdf_dir / fname
        if not local.exists() or local.stat().st_size == 0:
            missing.append(fname)

    if not missing:
        return {"ok": True, "chrom": chrom, "message": "SDF already present", "downloaded": []}

    sdf_dir.mkdir(parents=True, exist_ok=True)
    downloaded: List[str] = []
    failed: List[str] = []

    for fname in missing:
        local = sdf_dir / fname
        url = f"{REF_S3_BASE}/{chrom}/{chrom}.sdf/{fname}"
        ok = download_file_with_fallback(url, local, backup_url=None, show_progress=(fname == "seqdata0"))
        if ok and local.exists() and local.stat().st_size > 0:
            downloaded.append(fname)
        else:
            failed.append(fname)

    if failed:
        raise RuntimeError(
            f"Failed to download SDF files for {chrom}: {', '.join(failed)}. "
            "Run: python setup.py (validator role) to install reference data."
        )

    return {"ok": True, "chrom": chrom, "downloaded": downloaded}


def _download_demo_bam(round_data: dict, round_id: str, dest: Path, log: List[str]) -> Path:
    """Download demo BAM to dest, or reuse miner-cached input.bam."""
    miner_dir = BASE_DIR / "output" / safe_round_dir_name(round_id)
    miner_bam = miner_dir / "input.bam"
    if miner_bam.exists() and miner_bam.stat().st_size > 0:
        log.append(f"Reusing miner BAM: {miner_bam}")
        return miner_bam

    _prefer_hippius = os.getenv("STORAGE_PRIMARY_BACKEND", "hippius").lower() != "aws_s3"
    if _prefer_hippius:
        bam_url = round_data.get("bam_presigned_url_backup") or round_data.get("bam_presigned_url")
        bam_url_backup = round_data.get("bam_presigned_url")
    else:
        bam_url = round_data.get("bam_presigned_url")
        bam_url_backup = round_data.get("bam_presigned_url_backup")

    if not bam_url and not bam_url_backup:
        raise RuntimeError("Platform demo round has no BAM URL")

    dest.mkdir(parents=True, exist_ok=True)
    bam_path = dest / "round.bam"
    log.append("Downloading demo BAM from platform (no wallet required)...")
    ok = download_file_with_fallback(
        bam_url, bam_path, backup_url=bam_url_backup,
        expected_sha256=round_data.get("bam_sha256"), show_progress=True,
    )
    if not ok or not bam_path.exists():
        raise RuntimeError("Failed to download demo BAM")

    bam_index_url = round_data.get("bam_index_presigned_url") or round_data.get("bam_index_presigned_url_backup")
    if bam_index_url:
        download_file_with_fallback(bam_index_url, dest / "round.bam.bai", show_progress=False)

    return bam_path


def _try_download_eval_bundle(base_url: str, dest: Path, log: List[str]) -> Dict[str, str]:
    """Try reference API eval bundle (truth + mutations). Returns paths found."""
    paths: Dict[str, str] = {}
    for logical, filename in [("truth_vcf", "truth.vcf.gz"), ("mutations_vcf", "mutations.vcf.gz")]:
        local = dest / filename
        url = f"{base_url.rstrip('/')}/{filename}"
        log.append(f"Trying {url}...")
        ok = download_file_with_fallback(url, local, backup_url=None, show_progress=False)
        if ok and local.exists() and local.stat().st_size > 1000:
            paths[logical] = str(local)
            log.append(f"Got {filename}")
        else:
            log.append(f"Not available: {filename}")
    return paths


async def fetch_demo_task_from_platform() -> dict:
    """Fetch demo sandbox task from platform — BAM without wallet; truth if published."""
    from bittensor_wallet import Keypair
    from utils.platform_client import MinerPlatformClient, PlatformConfig

    log: List[str] = []
    kp = Keypair.create_from_uri("//local-lab-eval")
    platform_url = os.getenv("PLATFORM_URL", "https://api.theminos.ai").rstrip("/")
    client = MinerPlatformClient(kp, PlatformConfig(platform_url), demo=True)

    round_data = await client.get_round_status()
    if not round_data.get("has_active_round"):
        raise RuntimeError("No active demo round on platform")

    round_id = round_data.get("round_id") or "2026-01-01T00:00:00+00:00"
    region = round_data.get("region") or "chr20:46254744-51254744"
    chrom = round_data.get("chromosome") or _chrom_from_region(region)
    num_mutations = round_data.get("num_mutations")

    task_id = "demo_sandbox"
    dest = _task_dir(task_id)
    dest.mkdir(parents=True, exist_ok=True)

    bam_path = _download_demo_bam(round_data, round_id, dest, log)

    manifest = _load_manifest()
    spec = next((t for t in manifest.get("tasks", []) if t.get("id") == task_id), {})
    base_url = spec.get("files_base_url", f"{REF_S3_BASE}/eval/demo_sandbox")
    truth_paths = _try_download_eval_bundle(base_url, dest, log)

    ref_path, ref_sdf_path = _resolve_reference(chrom)
    if not truth_paths.get("truth_vcf") and bam_path.exists() and ref_path:
        log.append("Official eval bundle unavailable — generating local truth from BAM + GIAB...")
        try:
            from local_lab.backend.services.truth_generator import generate_local_truth
            gen = generate_local_truth(
                bam_path=Path(bam_path),
                ref_path=ref_path,
                region=region,
                work_dir=dest,
                giab_cache_dir=LAB_DIR / ".cache" / "giab",
            )
            log.extend(gen.get("log", []))
            truth_paths["truth_vcf"] = gen["truth_vcf"]
            truth_paths["mutations_vcf"] = gen["mutations_vcf"]
            meta_extra = {
                "truth_source": "local_generator",
                "synthetic_mutations": gen.get("synthetic_mutations"),
                "giab_variants": gen.get("giab_variants"),
            }
        except Exception as exc:
            log.append(f"Local truth generation failed: {exc}")
            meta_extra = {}
    else:
        meta_extra = {}

    # Also write metadata for miner output dirs
    meta = {
        "round_id": round_id,
        "region": region,
        "num_mutations": num_mutations,
        "fetched_at": _now_iso(),
        "source": "platform_demo",
        **meta_extra,
    }
    _write_json(dest / "task_meta.json", meta)
    miner_dir = BASE_DIR / "output" / safe_round_dir_name(round_id)
    if miner_dir.exists():
        _write_json(miner_dir / "task_meta.json", meta)

    ref_path, ref_sdf_path = _resolve_reference(chrom)
    try:
        sdf_result = ensure_chrom_sdf(chrom)
        log.append(f"SDF: {sdf_result.get('message', 'ok')}")
        ref_path, ref_sdf_path = _resolve_reference(chrom)
    except RuntimeError as exc:
        log.append(f"SDF download issue: {exc}")

    paths: Dict[str, str] = {
        "work_dir": str(dest if str(bam_path).startswith(str(dest)) else bam_path.parent),
        "bam": str(bam_path),
        "ref": str(ref_path) if ref_path else "",
        "ref_sdf": str(ref_sdf_path) if ref_sdf_path else "",
        **truth_paths,
    }

    ready = _task_ready({"paths": paths})
    missing = []
    if not truth_paths.get("truth_vcf"):
        missing.append("truth.vcf.gz")
    if not truth_paths.get("mutations_vcf"):
        missing.append("mutations.vcf.gz")

    entry = {
        "id": task_id,
        "name": "Platform Demo Sandbox",
        "description": spec.get("description", "Demo sandbox eval task"),
        "source": "platform_demo",
        "region": region,
        "chrom": chrom,
        "round_id": round_id,
        "num_mutations": num_mutations,
        "ready": ready,
        "bam_only": not ready,
        "missing_artifacts": missing,
        "paths": paths,
        "prepared_at": _now_iso(),
    }
    registry = _load_registry()
    registry["tasks"][task_id] = entry
    _save_registry(registry)

    return {
        "task": entry,
        "log": log,
        "ready": ready,
        "message": (
            "Demo task ready — BAM + truth + mutations (official bundle)."
            if ready and meta_extra.get("truth_source") != "local_generator"
            else "Demo task ready — BAM + locally generated truth/mutations (GIAB + oracle)."
            if ready and meta_extra.get("truth_source") == "local_generator"
            else f"BAM ready ({bam_path.stat().st_size / (1024**3):.2f} GB). "
            f"Still missing: {', '.join(missing)}. "
            "Click Generate local truth or re-fetch demo task."
            if not ready else
            "Demo task ready."
        ),
    }


def generate_truth_for_task(task_id: str, force: bool = False) -> dict:
    """Generate truth + mutations locally for any BAM-only task."""
    from local_lab.backend.services.truth_generator import generate_local_truth

    task = get_task(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    paths = task.get("paths") or {}
    bam = paths.get("bam")
    region = task.get("region") or ""
    chrom = task.get("chrom") or _chrom_from_region(region)

    if not bam or not Path(bam).exists():
        raise RuntimeError("Task has no BAM — fetch demo task or scan miner downloads first")
    if not region or region == "unknown":
        raise RuntimeError("Task has no region — cannot generate truth")

    ref_path, ref_sdf_path = _resolve_reference(chrom)
    if not ref_path:
        raise RuntimeError(f"Reference FASTA missing for {chrom}")

    ensure_chrom_sdf(chrom)
    ref_path, ref_sdf_path = _resolve_reference(chrom)

    work_dir = Path(paths.get("work_dir") or _task_dir(task_id))
    giab_cache = LAB_DIR / ".cache" / "giab"

    gen = generate_local_truth(
        bam_path=Path(bam),
        ref_path=ref_path,
        region=region,
        work_dir=work_dir,
        giab_cache_dir=giab_cache,
        force=force,
    )

    paths = dict(paths)
    paths["truth_vcf"] = gen["truth_vcf"]
    paths["mutations_vcf"] = gen["mutations_vcf"]
    paths["ref"] = str(ref_path)
    if ref_sdf_path:
        paths["ref_sdf"] = str(ref_sdf_path)

    entry = {
        **task,
        "ready": _task_ready({"paths": paths}),
        "bam_only": False,
        "missing_artifacts": [],
        "truth_source": "local_generator",
        "synthetic_mutations": gen.get("synthetic_mutations"),
        "giab_variants": gen.get("giab_variants"),
        "paths": paths,
        "generated_at": _now_iso(),
    }
    registry = _load_registry()
    registry["tasks"][task_id] = entry
    _save_registry(registry)

    return {
        "task": entry,
        "log": gen.get("log", []),
        "cached": gen.get("cached", False),
        "message": (
            f"Generated {gen.get('synthetic_mutations', '?')} synthetic mutations + "
            f"{gen.get('giab_variants', '?')} GIAB variants → ready to score."
        ),
    }


def attach_ground_truth(task_id: str, truth_vcf: str, mutations_vcf: str) -> dict:
    """Attach truth/mutations VCF paths to a BAM-only task."""
    task = get_task(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    truth = Path(truth_vcf).resolve()
    mutations = Path(mutations_vcf).resolve()
    if not truth.exists():
        raise ValueError(f"Truth VCF not found: {truth}")
    if not mutations.exists():
        raise ValueError(f"Mutations VCF not found: {mutations}")

    paths = dict(task.get("paths") or {})
    paths["truth_vcf"] = str(truth)
    paths["mutations_vcf"] = str(mutations)

    entry = {
        **task,
        "paths": paths,
        "ready": _task_ready({"paths": paths}),
        "bam_only": False,
        "missing_artifacts": [],
    }
    registry = _load_registry()
    registry["tasks"][task_id] = entry
    _save_registry(registry)
    return {"task": entry}


async def fetch_platform_task(round_id: str) -> dict:
    """Download scoring artifacts for a round (validator wallet required)."""
    from bittensor_wallet import Wallet
    from utils.platform_client import PlatformClientError, PlatformConfig, ValidatorPlatformClient

    wallet_name = os.getenv("WALLET_NAME")
    wallet_hotkey = os.getenv("WALLET_HOTKEY")
    if not wallet_name or not wallet_hotkey:
        raise RuntimeError(
            "Set WALLET_NAME and WALLET_HOTKEY in .env to fetch platform scoring tasks. "
            "Your hotkey must be authorized as a validator during the scoring window."
        )

    wallet = Wallet(name=wallet_name, hotkey=wallet_hotkey)
    platform_url = os.getenv("PLATFORM_URL", "https://api.theminos.ai").rstrip("/")
    client = ValidatorPlatformClient(wallet.hotkey, PlatformConfig(platform_url))

    try:
        round_data = await client.get_round_submissions(round_id)
    except PlatformClientError as exc:
        raise RuntimeError(f"Platform fetch failed: {exc}") from exc

    region = round_data.get("region")
    if not region:
        raise RuntimeError("Platform response missing region")

    chrom = _chrom_from_region(region)
    ref_path, ref_sdf_path = _resolve_reference(chrom)
    if not ref_path:
        raise RuntimeError(f"Reference not found for {chrom}. Run setup.py first.")

    task_id = f"platform_{safe_round_dir_name(round_id)}"
    work_dir = _task_dir(task_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    _prefer_hippius = os.getenv("STORAGE_PRIMARY_BACKEND", "hippius").lower() != "aws_s3"

    def _ordered(s3_key: str, hip_key: str):
        s3 = round_data.get(s3_key)
        hip = round_data.get(hip_key)
        return (hip, s3) if _prefer_hippius else (s3, hip)

    bam_url, bam_url_backup = _ordered("bam_presigned_url", "bam_presigned_url_backup")
    bam_index_url, bam_index_url_backup = _ordered("bam_index_presigned_url", "bam_index_presigned_url_backup")
    truth_url, truth_url_backup = _ordered("truth_vcf_presigned_url", "truth_vcf_presigned_url_backup")
    truth_index_url, truth_index_url_backup = _ordered(
        "truth_vcf_index_presigned_url", "truth_vcf_index_presigned_url_backup"
    )
    mut_url, mut_url_backup = _ordered("mutations_vcf_presigned_url", "mutations_vcf_presigned_url_backup")
    mut_index_url, mut_index_url_backup = _ordered(
        "mutations_vcf_index_presigned_url", "mutations_vcf_index_presigned_url_backup"
    )

    bam_path = work_dir / "round.bam"
    if not download_file_with_fallback(
        bam_url, bam_path, backup_url=bam_url_backup,
        expected_sha256=round_data.get("bam_sha256"), show_progress=True,
    ):
        raise RuntimeError("Failed to download BAM")

    bam_index = work_dir / "round.bam.bai"
    if bam_index_url or bam_index_url_backup:
        download_file_with_fallback(bam_index_url, bam_index, backup_url=bam_index_url_backup)

    truth_path = work_dir / "truth.vcf.gz"
    if not download_file_with_fallback(
        truth_url, truth_path, backup_url=truth_url_backup,
        expected_sha256=round_data.get("truth_vcf_sha256"),
    ):
        raise RuntimeError("Failed to download truth VCF")

    mut_path = work_dir / "mutations.vcf.gz"
    if not (mut_url or mut_url_backup):
        raise RuntimeError("Platform did not provide mutations VCF URL")
    if not download_file_with_fallback(
        mut_url, mut_path, backup_url=mut_url_backup,
        expected_sha256=round_data.get("mutations_vcf_sha256"),
    ):
        raise RuntimeError("Failed to download mutations VCF")

    meta = {
        "round_id": round_id,
        "region": region,
        "fetched_at": _now_iso(),
        "num_mutations": round_data.get("num_mutations"),
    }
    _write_json(work_dir / "task_meta.json", meta)

    paths = {
        "work_dir": str(work_dir),
        "bam": str(bam_path),
        "truth_vcf": str(truth_path),
        "mutations_vcf": str(mut_path),
        "ref": str(ref_path),
        "ref_sdf": str(ref_sdf_path) if ref_sdf_path else None,
    }

    entry = {
        "id": task_id,
        "name": f"Platform round · {round_id[:19]}",
        "description": "Downloaded from platform get-submissions (validator-parity artifacts).",
        "source": "platform",
        "region": region,
        "chrom": chrom,
        "round_id": round_id,
        "num_mutations": round_data.get("num_mutations"),
        "ready": True,
        "paths": paths,
        "prepared_at": _now_iso(),
    }
    registry = _load_registry()
    registry["tasks"][task_id] = entry
    _save_registry(registry)
    return {"task": entry}


def import_task_directory(source_dir: str, name: Optional[str] = None) -> dict:
    src = Path(source_dir).resolve()
    if not src.is_dir():
        raise ValueError(f"Not a directory: {source_dir}")

    bam = src / "round.bam"
    if not bam.exists():
        bams = list(src.glob("*.bam"))
        bam = bams[0] if bams else None
    truth = src / "truth.vcf.gz"
    mutations = src / "mutations.vcf.gz"
    if not bam or not truth.exists() or not mutations.exists():
        raise ValueError(
            "Directory must contain round.bam (or *.bam), truth.vcf.gz, and mutations.vcf.gz"
        )

    meta = _read_json(src / "task_meta.json", {})
    region = meta.get("region") or meta.get("region_string") or ""
    if not region:
        raise ValueError("Missing region — add task_meta.json with {\"region\": \"chr20:...\"}")

    task_id = f"import_{hashlib.sha256(str(src).encode()).hexdigest()[:10]}"
    chrom = _chrom_from_region(region)
    ref_path, ref_sdf_path = _resolve_reference(chrom)

    paths = {
        "work_dir": str(src),
        "bam": str(bam),
        "truth_vcf": str(truth),
        "mutations_vcf": str(mutations),
        "ref": str(ref_path) if ref_path else None,
        "ref_sdf": str(ref_sdf_path) if ref_sdf_path else None,
    }

    entry = {
        "id": task_id,
        "name": name or f"Imported · {src.name}",
        "description": f"Imported from {src}",
        "source": "import",
        "region": region,
        "chrom": chrom,
        "ready": True,
        "paths": paths,
        "imported_at": _now_iso(),
    }
    registry = _load_registry()
    registry["tasks"][task_id] = entry
    _save_registry(registry)
    return {"task": entry}


def _build_tool_config(template: str) -> dict:
    options = extract_tool_options(template)
    key_map = {
        "gatk": "gatk_options",
        "deepvariant": "deepvariant_options",
        "bcftools": "bcftools_options",
    }
    opt_key = key_map.get(template, f"{template}_options")
    sanitized = {k: v for k, v in options.items() if k in ALLOWED_CONFIG_KEYS or k.endswith("_options")}
    if opt_key not in sanitized:
        sanitized[opt_key] = options
    return {
        **sanitized,
        "tool": template,
        "timeout": GENOMICS_CONFIG.get("variant_calling_timeout", 1800),
        "threads": int(os.getenv("SCORING_THREADS", "4")),
        "memory_gb": int(os.getenv("SCORING_MEMORY_GB", "16")),
        "ref_build": "GRCh38",
    }


def _run_variant_call_sync(
    template: str,
    bam_path: Path,
    ref_path: Path,
    output_vcf: Path,
    region: str,
) -> dict:
    tpl = load_template(template)
    config = _build_tool_config(template)
    return tpl.variant_call(
        bam_path=bam_path,
        reference_path=ref_path,
        output_vcf_path=output_vcf,
        region=region,
        config=config,
    )


def score_query_vcf(task: dict, query_vcf: Path) -> dict:
    """Score a query VCF with validator-parity hap.py + AdvancedScorer."""
    paths = task.get("paths") or {}
    truth = Path(paths["truth_vcf"])
    mutations = Path(paths["mutations_vcf"])
    region = task.get("region") or ""
    ref_path = Path(paths["ref"]) if paths.get("ref") else None
    ref_sdf = Path(paths["ref_sdf"]) if paths.get("ref_sdf") else None

    if not ref_path or not ref_path.exists():
        chrom = task.get("chrom") or _chrom_from_region(region)
        ref_path, ref_sdf = _resolve_reference(chrom)
    if not ref_path or not ref_path.exists():
        raise RuntimeError("Reference FASTA missing")
    if not ref_sdf or not ref_sdf.exists():
        raise RuntimeError("Reference SDF missing — required for hap.py vcfeval")

    scorer = HappyScorer()
    metrics = scorer.score_vcf(
        truth_vcf=str(truth),
        query_vcf=str(query_vcf),
        reference_fasta=str(ref_path),
        confident_bed=None,
        region=region,
        reference_sdf=str(ref_sdf),
        mutations_vcf=str(mutations),
    )
    if metrics is None:
        raise RuntimeError("hap.py scoring failed — check Docker and logs")

    advanced_score = AdvancedScorer.compute_advanced_score(metrics)
    combined_final = _valid_round_score(
        advanced_score / 100.0,
        label="local eval",
    )
    if combined_final is None:
        raise RuntimeError("Invalid combined score from AdvancedScorer")
    if _is_zero_input_advanced_fingerprint(metrics, combined_final):
        raise RuntimeError("Zero-input score fingerprint — scoring likely failed")

    snp_final = float(metrics.get("f1_snp") or 0.0)
    indel_final = float(metrics.get("f1_indel") or 0.0)

    components = _score_components(metrics, advanced_score)

    return {
        "metrics": metrics,
        "advanced_score": advanced_score,
        "combined_final": combined_final,
        "snp_final": snp_final,
        "indel_final": indel_final,
        "components": components,
        "query_vcf": str(query_vcf),
        "truth_vcf": str(truth),
        "mutations_vcf": str(mutations),
        "region": region,
    }


def _score_components(metrics: dict, advanced_score: float) -> dict:
    f1_snp = metrics.get("f1_snp", 0) or 0
    f1_indel = metrics.get("f1_indel", 0) or 0
    recall_snp = metrics.get("recall_snp", 0) or 0
    recall_indel = metrics.get("recall_indel", 0) or 0
    precision_snp = metrics.get("precision_snp", 0) or 0
    precision_indel = metrics.get("precision_indel", 0) or 0

    return {
        "core_f1": {
            "weight": 0.60,
            "snp_f1": f1_snp,
            "indel_f1": f1_indel,
            "weighted_f1": metrics.get("weighted_f1"),
        },
        "completeness": {
            "weight": 0.15,
            "recall_snp": recall_snp,
            "recall_indel": recall_indel,
            "frac_na_snp": metrics.get("frac_na_snp"),
            "frac_na_indel": metrics.get("frac_na_indel"),
        },
        "fp_rate": {
            "weight": 0.15,
            "fp_snp": metrics.get("fp_snp"),
            "fp_indel": metrics.get("fp_indel"),
            "query_total_snp": metrics.get("query_total_snp"),
            "query_total_indel": metrics.get("query_total_indel"),
        },
        "quality": {
            "weight": 0.10,
            "titv_query_snp": metrics.get("titv_query_snp"),
            "titv_truth_snp": metrics.get("titv_truth_snp"),
            "hethom_query_snp": metrics.get("hethom_query_snp"),
            "hethom_truth_snp": metrics.get("hethom_truth_snp"),
        },
        "overcall_penalty": metrics.get("overcall_penalty", 0),
        "advanced_score": advanced_score,
    }


def append_eval_history(record: dict) -> dict:
    history = _read_json(EVAL_HISTORY_PATH, {"entries": []})
    history.setdefault("entries", []).insert(0, record)
    history["entries"] = history["entries"][:100]
    _write_json(EVAL_HISTORY_PATH, history)
    return record


def get_eval_history(limit: int = 30) -> dict:
    history = _read_json(EVAL_HISTORY_PATH, {"entries": []})
    entries = history.get("entries", [])[:limit]
    return {"entries": entries, "count": len(entries)}


class EvalRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EvalRunRecord:
    id: str
    task_id: str
    template: str
    mode: str
    status: EvalRunStatus
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    log_path: Optional[str] = None
    message: str = ""
    result: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "template": self.template,
            "mode": self.mode,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_path": self.log_path,
            "message": self.message,
            "result": self.result,
        }


class EvalRunManager:
    def __init__(self) -> None:
        EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._runs: Dict[str, EvalRunRecord] = {}
        self._lock = threading.Lock()

    def list_runs(self, limit: int = 20) -> List[dict]:
        items = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in items[:limit]]

    def get_run(self, run_id: str) -> Optional[EvalRunRecord]:
        return self._runs.get(run_id)

    def get_latest_result(self) -> Optional[dict]:
        for rec in sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True):
            if rec.status == EvalRunStatus.COMPLETED and rec.result:
                return rec.result
        history = get_eval_history(limit=1)
        if history.get("entries"):
            return history["entries"][0]
        return None

    def start_eval(
        self,
        task_id: str,
        template: str,
        mode: str = "full",
        query_vcf: Optional[str] = None,
    ) -> EvalRunRecord:
        with self._lock:
            active = [r for r in self._runs.values() if r.status == EvalRunStatus.RUNNING]
            if active:
                raise RuntimeError(f"Eval run {active[0].id} already in progress")

        task = get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        prereq = check_prerequisites(task_id)
        if mode == "full" and not _task_ready(task):
            raise RuntimeError("Task not ready — prepare or import truth/mutations/BAM first")
        if mode == "score_only" and not _task_ready(task):
            raise RuntimeError("Score-only requires prepared truth + mutations VCF")

        run_id = uuid.uuid4().hex[:12]
        log_path = EVAL_RUNS_DIR / f"{run_id}.log"
        record = EvalRunRecord(
            id=run_id,
            task_id=task_id,
            template=template,
            mode=mode,
            status=EvalRunStatus.PENDING,
            created_at=_now_iso(),
            log_path=str(log_path),
        )
        self._runs[run_id] = record
        log_path.write_text("", encoding="utf-8")

        thread = threading.Thread(
            target=self._execute_eval,
            args=(run_id, task, template, mode, query_vcf),
            daemon=True,
        )
        thread.start()
        return record

    def _log(self, log_path: Path, msg: str) -> None:
        line = f"[{_now_iso()}] {msg}\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _execute_eval(
        self,
        run_id: str,
        task: dict,
        template: str,
        mode: str,
        query_vcf: Optional[str],
    ) -> None:
        record = self._runs[run_id]
        log_path = Path(record.log_path)
        record.status = EvalRunStatus.RUNNING
        record.started_at = _now_iso()

        try:
            paths = task.get("paths") or {}
            work_dir = Path(paths.get("work_dir") or _task_dir(task["id"]))
            work_dir.mkdir(parents=True, exist_ok=True)
            region = task.get("region") or ""
            chrom = task.get("chrom") or _chrom_from_region(region)
            ref_path, ref_sdf_path = _resolve_reference(chrom)
            if not ref_path:
                raise RuntimeError(f"Reference missing for {chrom}")

            if mode == "full":
                self._log(log_path, f"Running {template} variant calling on eval BAM...")
                bam = Path(paths["bam"])
                out_vcf = work_dir / f"eval_{template}_{run_id}.vcf.gz"
                result = _run_variant_call_sync(template, bam, ref_path, out_vcf, region)
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "Variant calling failed")
                self._log(log_path, f"Variant calling done: {result.get('variant_count', 0)} variants")
                query_path = out_vcf
            else:
                if query_vcf:
                    query_path = Path(query_vcf)
                elif paths.get("query_vcf"):
                    query_path = Path(paths["query_vcf"])
                else:
                    from local_lab.backend.services.vcf_service import find_latest_vcf
                    latest = find_latest_vcf(PROJECT_ROOT / "output")
                    if not latest:
                        raise RuntimeError("No query VCF — run demo first or specify query_vcf")
                    query_path = latest
                self._log(log_path, f"Score-only mode using {query_path}")

            self._log(log_path, "Running hap.py (validator-parity scoring)...")
            score = score_query_vcf(task, query_path)
            self._log(
                log_path,
                f"Score: combined={score['combined_final']:.4f} "
                f"SNP F1={score['snp_final']:.4f} INDEL F1={score['indel_final']:.4f} "
                f"advanced={score['advanced_score']:.2f}/100",
            )

            history_entry = {
                "id": run_id,
                "timestamp": _now_iso(),
                "task_id": task["id"],
                "task_name": task.get("name"),
                "template": template,
                "mode": mode,
                "config_fingerprint": _config_fingerprint(template),
                **{k: score[k] for k in ("combined_final", "snp_final", "indel_final", "advanced_score", "components")},
                "metrics_summary": {
                    k: score["metrics"].get(k)
                    for k in (
                        "precision_snp", "recall_snp", "f1_snp",
                        "precision_indel", "recall_indel", "f1_indel",
                        "fp_snp", "fp_indel", "truth_total_snp", "truth_total_indel",
                    )
                },
            }
            append_eval_history(history_entry)

            record.result = score
            record.status = EvalRunStatus.COMPLETED
            record.message = "Eval completed"
            record.finished_at = _now_iso()

        except Exception as exc:
            logger.exception("Eval run %s failed", run_id)
            self._log(log_path, f"ERROR: {exc}")
            record.status = EvalRunStatus.FAILED
            record.message = str(exc)
            record.finished_at = _now_iso()

    async def stream_logs(self, run_id: str) -> AsyncIterator[str]:
        record = self._runs.get(run_id)
        if not record or not record.log_path:
            yield "data: [error] run not found\n\n"
            return

        log_path = Path(record.log_path)
        sent = 0
        idle = 0
        while True:
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) > sent:
                    for line in lines[sent:]:
                        yield f"data: {line.replace(chr(10), ' ')}\n\n"
                    sent = len(lines)
                    idle = 0

            current = self._runs.get(run_id)
            if not current:
                break
            if current.status in (EvalRunStatus.COMPLETED, EvalRunStatus.FAILED):
                yield "event: done\ndata: finished\n\n"
                break

            idle += 1
            if idle > 7200:
                yield "event: done\ndata: timeout\n\n"
                break
            await asyncio.sleep(1)


eval_manager = EvalRunManager()
