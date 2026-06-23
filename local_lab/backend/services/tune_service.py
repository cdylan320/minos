"""Miner config tuning pipeline — round-history analysis and recommendations."""

from __future__ import annotations

import re
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from local_lab.backend.services.config_service import read_config, write_config
from local_lab.backend.services.leaderboard_service import (
    _get_hotkey_coldkey_map,
    _load_cached_finalized_leaderboards,
    _short_hotkey,
    fetch_round_leaderboard,
    fetch_rounds,
    get_my_hotkey,
    sync_all_finalized,
)
from utils.config_loader import extract_tool_options

REGION_RE = re.compile(r"^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$")


def _short_coldkey(ck: str) -> str:
    return _short_hotkey(ck)


def _log(
    logs: List[Dict[str, Any]],
    phase: str,
    level: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    logs.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "level": level,
        "message": message,
        "data": data or {},
    })


def _parse_region(region: str) -> Dict[str, Any]:
    m = REGION_RE.match(region or "")
    if not m:
        return {"chrom": "unknown", "start": None, "end": None, "width_bp": None}
    start, end = int(m.group(2)), int(m.group(3))
    return {"chrom": m.group(1), "start": start, "end": end, "width_bp": end - start}


def _format_round_short(round_id: str) -> str:
    try:
        dt = datetime.fromisoformat(round_id.replace("Z", "+00:00"))
        return dt.strftime("%m/%d %H:%M")
    except ValueError:
        return (round_id or "")[:16]


def _avg(values: List[float]) -> Optional[float]:
    return round(statistics.mean(values), 4) if values else None


def _median(values: List[float]) -> Optional[float]:
    return round(statistics.median(values), 4) if values else None


def _score_gap_label(gap: float) -> str:
    if gap >= 0.08:
        return "critical"
    if gap >= 0.04:
        return "moderate"
    if gap >= 0.02:
        return "minor"
    return "ok"


def _load_rounds_data(rounds_limit: int, force_sync: bool, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    _log(logs, "load", "info", f"Fetching up to {rounds_limit} finalized rounds from platform cache")
    rounds_data = fetch_rounds(limit=100, force=force_sync)
    finalized_ids = [
        r["round_id"] for r in rounds_data.get("rounds", []) if r.get("is_finalized")
    ][:rounds_limit]

    if force_sync:
        sync_all_finalized(force=True, max_rounds=rounds_limit)
    else:
        missing = [
            rid for rid in finalized_ids
            if not any(
                lb.get("round", {}).get("round_id") == rid
                for lb in _load_cached_finalized_leaderboards()
            )
        ]
        for rid in missing[:20]:
            try:
                fetch_round_leaderboard(rid, force=False)
            except Exception as exc:
                _log(logs, "load", "warn", f"Could not fetch round {rid}: {exc}")

    leaderboards = _load_cached_finalized_leaderboards()
    by_id = {lb.get("round", {}).get("round_id"): lb for lb in leaderboards}
    selected = [by_id[rid] for rid in finalized_ids if rid in by_id]
    _log(logs, "load", "success", f"Loaded {len(selected)} finalized rounds for analysis")
    return selected


def _analyze_regions(leaderboards: List[Dict[str, Any]], logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    chrom_counts: Dict[str, int] = {}
    widths: List[int] = []
    recent: List[Dict[str, Any]] = []

    for lb in leaderboards[:15]:
        rnd = lb.get("round", {})
        region = rnd.get("region", "")
        parsed = _parse_region(region)
        chrom_counts[parsed["chrom"]] = chrom_counts.get(parsed["chrom"], 0) + 1
        if parsed["width_bp"]:
            widths.append(parsed["width_bp"])
        recent.append({
            "round_id": rnd.get("round_id"),
            "region": region,
            "chrom": parsed["chrom"],
            "width_mb": round(parsed["width_bp"] / 1_000_000, 2) if parsed["width_bp"] else None,
            "status": rnd.get("status"),
        })

    top_chrom = sorted(chrom_counts.items(), key=lambda x: (-x[1], x[0]))
    _log(
        logs, "regions", "info",
        f"Recent chromosomes: {', '.join(f'{c}({n})' for c, n in top_chrom[:5])}",
        {"chrom_counts": dict(top_chrom)},
    )
    return {
        "recent_rounds": recent,
        "chromosome_frequency": [{"chrom": c, "count": n} for c, n in top_chrom],
        "typical_window_mb": round(statistics.median(widths) / 1_000_000, 2) if widths else 5.0,
    }


def _scored_entries(lb: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        e for e in lb.get("entries", [])
        if e.get("status") == "scored" and e.get("combined_final") is not None
    ]


def _analyze_top_miners(
    leaderboards: List[Dict[str, Any]],
    hotkey_to_coldkey: Dict[str, str],
    logs: List[Dict[str, Any]],
    top_n: int = 3,
) -> Dict[str, Any]:
    profiles: List[Dict[str, Any]] = []
    recent_winners: List[Dict[str, Any]] = []
    tool_wins: Dict[str, int] = {}

    for lb in leaderboards:
        rnd = lb.get("round", {})
        scored = sorted(_scored_entries(lb), key=lambda e: e.get("rank") or 9999)
        if scored and scored[0].get("rank") == 1:
            w = scored[0]
            hk = w.get("hotkey", "")
            ck = hotkey_to_coldkey.get(hk)
            recent_winners.append({
                "round_id": rnd.get("round_id"),
                "round_label": _format_round_short(rnd.get("round_id", "")),
                "region": rnd.get("region"),
                "hotkey": hk,
                "short_hotkey": _short_hotkey(hk),
                "coldkey": ck,
                "short_coldkey": _short_coldkey(ck) if ck else None,
                "uid": w.get("uid"),
                "combined_final": w.get("combined_final"),
                "snp_final": w.get("snp_final"),
                "indel_final": w.get("indel_final"),
                "tool_name": w.get("tool_name"),
            })
        for e in scored[:top_n]:
            hk = e.get("hotkey", "")
            ck = hotkey_to_coldkey.get(hk)
            profiles.append({
                "round_id": rnd.get("round_id"),
                "region": rnd.get("region"),
                "rank": e.get("rank"),
                "hotkey": hk,
                "short_hotkey": _short_hotkey(hk),
                "coldkey": ck,
                "short_coldkey": _short_coldkey(ck) if ck else None,
                "uid": e.get("uid"),
                "combined_final": e.get("combined_final"),
                "snp_final": e.get("snp_final"),
                "indel_final": e.get("indel_final"),
                "tool_name": e.get("tool_name"),
            })
            if e.get("rank") == 1:
                tool = e.get("tool_name") or "unknown"
                tool_wins[tool] = tool_wins.get(tool, 0) + 1

    snp_vals = [p["snp_final"] for p in profiles if p.get("snp_final") is not None]
    indel_vals = [p["indel_final"] for p in profiles if p.get("indel_final") is not None]
    combined_vals = [p["combined_final"] for p in profiles if p.get("combined_final") is not None]

    summary = {
        "sample_count": len(profiles),
        "avg_combined": _avg(combined_vals),
        "median_combined": _median(combined_vals),
        "avg_snp": _avg(snp_vals),
        "median_snp": _median(snp_vals),
        "avg_indel": _avg(indel_vals),
        "median_indel": _median(indel_vals),
        "tool_win_counts": tool_wins,
    }
    _log(
        logs, "top_miners", "info",
        (
            f"Top-{top_n} podium SNP median {_median(snp_vals)}, "
            f"INDEL median {_median(indel_vals)}, combined median {_median(combined_vals)}"
        ),
        summary,
    )
    recent_winners.sort(key=lambda x: x.get("round_id", ""), reverse=True)
    return {
        "profiles": profiles[:30],
        "summary": summary,
        "tool_win_counts": tool_wins,
        "recent_winners": recent_winners[:15],
    }


def _analyze_my_performance(
    hotkey: Optional[str],
    leaderboards: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not hotkey:
        _log(logs, "my_miner", "warn", "No local hotkey configured in .env — skipping personal diagnosis")
        return None

    rows: List[Dict[str, Any]] = []
    for lb in leaderboards:
        rnd = lb.get("round", {})
        for e in lb.get("entries", []):
            if e.get("hotkey") != hotkey:
                continue
            rows.append({
                "round_id": rnd.get("round_id"),
                "region": rnd.get("region"),
                "rank": e.get("rank"),
                "combined_final": e.get("combined_final"),
                "snp_final": e.get("snp_final"),
                "indel_final": e.get("indel_final"),
                "tool_name": e.get("tool_name"),
                "status": e.get("status"),
            })

    if not rows:
        _log(logs, "my_miner", "warn", f"Hotkey {_short_hotkey(hotkey)} not found in cached round history")
        return {"hotkey": hotkey, "short_hotkey": _short_hotkey(hotkey), "rounds_found": 0, "history": []}

    scored = [r for r in rows if r.get("combined_final") is not None]
    history = sorted(rows, key=lambda x: x.get("round_id", ""), reverse=True)
    latest_scored = next((r for r in history if r.get("combined_final") is not None), None)
    latest_round = None
    if latest_scored:
        latest_round = {
            **latest_scored,
            "round_label": _format_round_short(latest_scored.get("round_id", "")),
        }
        _log(
            logs, "my_miner", "info",
            (
                f"Latest scored round {latest_round['round_label']}: "
                f"combined={latest_round.get('combined_final')}, "
                f"snp={latest_round.get('snp_final')}, indel={latest_round.get('indel_final')}"
            ),
            latest_round,
        )
    _log(logs, "my_miner", "success", f"Found {len(rows)} rounds ({len(scored)} scored) for your hotkey")

    return {
        "hotkey": hotkey,
        "short_hotkey": _short_hotkey(hotkey),
        "rounds_found": len(rows),
        "scored_rounds": len(scored),
        "latest_round": latest_round,
        "avg_combined": _avg([r["combined_final"] for r in scored]),
        "avg_snp": _avg([r["snp_final"] for r in scored if r.get("snp_final") is not None]),
        "avg_indel": _avg([r["indel_final"] for r in scored if r.get("indel_final") is not None]),
        "best_combined": max((r["combined_final"] for r in scored), default=None),
        "worst_combined": min((r["combined_final"] for r in scored), default=None),
        "history": history[:20],
    }


def _compute_gaps(my_snp: float, my_indel: float, my_combined: float,
                  ref_snp: float, ref_indel: float, ref_combined: float) -> Dict[str, Any]:
    snp_gap = round(ref_snp - my_snp, 4)
    indel_gap = round(ref_indel - my_indel, 4)
    combined_gap = round(ref_combined - my_combined, 4)
    weaknesses: List[str] = []
    if snp_gap >= 0.02:
        weaknesses.append("snp")
    if indel_gap >= 0.02:
        weaknesses.append("indel")
    if combined_gap >= 0.05 and not weaknesses:
        weaknesses.append("overall")
    return {
        "my_combined": my_combined,
        "my_snp": my_snp,
        "my_indel": my_indel,
        "ref_combined": ref_combined,
        "ref_snp": ref_snp,
        "ref_indel": ref_indel,
        "gaps": {
            "combined": {"value": combined_gap, "severity": _score_gap_label(combined_gap)},
            "snp": {"value": snp_gap, "severity": _score_gap_label(snp_gap)},
            "indel": {"value": indel_gap, "severity": _score_gap_label(indel_gap)},
        },
        "weaknesses": weaknesses,
        "primary_weakness": weaknesses[0] if weaknesses else "none",
        "interpretation": _interpret_weakness(weaknesses, snp_gap, indel_gap),
    }


def _diagnose(
    my_perf: Optional[Dict[str, Any]],
    top_summary: Dict[str, Any],
    recent_winners: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not my_perf or not my_perf.get("scored_rounds"):
        return {
            "available": False,
            "message": "Configure WALLET_NAME/WALLET_HOTKEY in .env and participate in scored rounds for personal diagnosis.",
        }

    avg_block = _compute_gaps(
        my_perf.get("avg_snp") or 0.0,
        my_perf.get("avg_indel") or 0.0,
        my_perf.get("avg_combined") or 0.0,
        top_summary.get("median_snp") or 0.95,
        top_summary.get("median_indel") or 0.95,
        top_summary.get("median_combined") or 0.87,
    )

    latest_block = None
    latest = my_perf.get("latest_round")
    if latest:
        winner = next(
            (w for w in recent_winners if w.get("round_id") == latest.get("round_id")),
            None,
        )
        ref_snp = winner.get("snp_final") if winner else top_summary.get("median_snp") or 0.95
        ref_indel = winner.get("indel_final") if winner else top_summary.get("median_indel") or 0.95
        ref_combined = winner.get("combined_final") if winner else top_summary.get("median_combined") or 0.87
        latest_block = {
            "round_id": latest.get("round_id"),
            "round_label": latest.get("round_label"),
            "region": latest.get("region"),
            "winner_hotkey": winner.get("short_hotkey") if winner else None,
            **_compute_gaps(
                latest.get("snp_final") or 0.0,
                latest.get("indel_final") or 0.0,
                latest.get("combined_final") or 0.0,
                ref_snp or 0.0,
                ref_indel or 0.0,
                ref_combined or 0.0,
            ),
        }

    primary = latest_block if latest_block else avg_block
    diagnosis = {
        "available": True,
        "score_note": (
            "Scores shown are one final value per round from the public leaderboard API "
            "(snp_final, indel_final, combined_final). The official dashboard may list multiple "
            "validator eval rows (EVAL_ID) per round, but they share the same aggregated finals — "
            "not separate per-validator SNP/INDEL in our API."
        ),
        "latest_round": latest_block,
        "average": avg_block,
        "interpretation": primary["interpretation"],
        "gaps": primary["gaps"],
        "primary_weakness": primary["primary_weakness"],
        "weaknesses": primary["weaknesses"],
    }
    _log(logs, "diagnosis", "decision", diagnosis["interpretation"], diagnosis)
    return diagnosis


def _interpret_weakness(weaknesses: List[str], snp_gap: float, indel_gap: float) -> str:
    if not weaknesses or weaknesses == ["none"]:
        return "Your SNP/INDEL balance is close to top performers — focus on fine-tuning one parameter at a time."
    if "indel" in weaknesses and snp_gap < 0.02:
        return (
            f"INDEL score lags top miners by {indel_gap:.3f} while SNP is fine — "
            "likely indel filtering (PCR model, confidence threshold, or assembly graph)."
        )
    if "snp" in weaknesses and indel_gap < 0.02:
        return (
            f"SNP score lags top miners by {snp_gap:.3f} while INDEL is fine — "
            "likely over-filtering bases/reads or confidence threshold too high."
        )
    return (
        f"Both SNP (gap {snp_gap:.3f}) and INDEL (gap {indel_gap:.3f}) trail top miners — "
        "start with PCR-free GATK settings, then adjust confidence threshold."
    )


def _clamp_param(tool: str, param: str, value: Any) -> Any:
    from templates.tool_params import (
        BCFTOOLS_QUALITY_PARAMS,
        DEEPVARIANT_QUALITY_PARAMS,
        GATK_QUALITY_PARAMS,
    )
    defs = {
        "gatk": GATK_QUALITY_PARAMS,
        "deepvariant": DEEPVARIANT_QUALITY_PARAMS,
        "bcftools": BCFTOOLS_QUALITY_PARAMS,
    }.get(tool, {})
    spec = defs.get(param)
    if not spec:
        return value
    if spec["type"] == "enum":
        return value if value in spec["allowed_values"] else spec["default"]
    if spec["type"] in ("int", "float"):
        lo, hi = spec["min"], spec["max"]
        v = float(value) if spec["type"] == "float" else int(round(float(value)))
        return max(lo, min(hi, v))
    return value


def _build_recommendations(
    template: str,
    current: Dict[str, Any],
    diagnosis: Dict[str, Any],
    top_summary: Dict[str, Any],
    logs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []

    def add(param: str, new_value: Any, reason: str, priority: int, source: str) -> None:
        cur = current.get(param)
        clamped = _clamp_param(template, param, new_value)
        if cur == clamped:
            return
        recs.append({
            "id": f"{param}_{clamped}",
            "param": param,
            "current_value": cur,
            "proposed_value": clamped,
            "reason": reason,
            "priority": priority,
            "source": source,
            "selected": True,
        })

    if template == "gatk":
        if current.get("pcr_indel_model") != "NONE":
            add(
                "pcr_indel_model", "NONE",
                "GIAB/Minos BAMs are PCR-free — CONSERVATIVE PCR model suppresses real indels.",
                1, "tuning_guide",
            )

        weakness = diagnosis.get("primary_weakness", "none")
        if diagnosis.get("latest_round"):
            weakness = diagnosis["latest_round"].get("primary_weakness", weakness)
        conf = float(current.get("standard_min_confidence_threshold_for_calling", 30))
        base_q = int(current.get("min_base_quality_score", 10))
        map_q = int(current.get("min_mapping_quality_score", 20))

        if weakness in ("snp", "overall") and diagnosis.get("available"):
            if conf > 25:
                add(
                    "standard_min_confidence_threshold_for_calling", conf - 5,
                    f"SNP gap vs top miners — lower calling threshold to recover recall (was {conf}).",
                    2, "score_diagnosis",
                )
            if base_q > 8:
                add(
                    "min_base_quality_score", max(8, base_q - 2),
                    "SNP recall may improve with slightly lower base quality filter.",
                    3, "score_diagnosis",
                )

        if weakness in ("indel", "overall") and diagnosis.get("available"):
            if conf > 28:
                add(
                    "standard_min_confidence_threshold_for_calling", conf - 3,
                    f"INDEL gap vs top miners — moderate confidence reduction (was {conf}).",
                    2, "score_diagnosis",
                )
            indel_het = float(current.get("indel_heterozygosity", 0.000125))
            if indel_het < 0.0002:
                add(
                    "indel_heterozygosity", min(0.0002, indel_het * 1.5),
                    "Slightly higher indel prior can help indel sensitivity on GIAB windows.",
                    4, "heuristic",
                )

        if weakness == "none" and (top_summary.get("median_snp") or 0) > 0.98:
            if map_q < 25:
                add(
                    "min_mapping_quality_score", min(25, map_q + 5),
                    "Top miners show very high SNP — slightly stricter mapping quality may reduce FPs without hurting recall.",
                    5, "top_miner_profile",
                )

    elif template == "deepvariant":
        if current.get("model_type") != "WGS":
            add("model_type", "WGS", "Minos BAMs are whole-genome — WES mode hurts scores.", 1, "tuning_guide")
        mq = int(current.get("min_mapping_quality", 5))
        weakness = diagnosis.get("primary_weakness", "none")
        if weakness in ("snp", "overall") and mq > 3:
            add("min_mapping_quality", max(3, mq - 2), "Lower mapping quality filter to improve SNP recall.", 2, "score_diagnosis")
        elif weakness == "none" and mq < 10:
            add("min_mapping_quality", min(10, mq + 2), "Top performers run clean calls — modest MQ increase may trim FPs.", 3, "top_miner_profile")

    elif template == "bcftools":
        mq = int(current.get("min_MQ", 0))
        bq = int(current.get("min_BQ", 13))
        weakness = diagnosis.get("primary_weakness", "none")
        if weakness in ("snp", "overall") and mq > 5:
            add("min_MQ", max(0, mq - 5), "Reduce mapping quality filter for better SNP recall.", 2, "score_diagnosis")
        if weakness in ("indel", "overall") and bq > 10:
            add("min_BQ", max(10, bq - 3), "Lower base quality filter to help indel recall.", 3, "score_diagnosis")

    recs.sort(key=lambda r: r["priority"])
    _log(logs, "recommendations", "success", f"Generated {len(recs)} parameter recommendation(s)", {"count": len(recs)})
    for r in recs:
        _log(
            logs, "recommendations", "decision",
            f"{r['param']}: {r['current_value']} → {r['proposed_value']} — {r['reason']}",
            r,
        )
    return recs


def _apply_recommendations_to_content(
    content: str,
    recommendations: List[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    selected = [r for r in recommendations if r.get("selected", True)]
    lines = content.splitlines()
    changed_keys: List[str] = []
    key_to_idx: Dict[str, int] = {}

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        key_to_idx[key] = i

    for rec in selected:
        param = rec["param"]
        val = rec["proposed_value"]
        new_line = f"{param}={val}"
        if param in key_to_idx:
            lines[key_to_idx[param]] = new_line
        else:
            lines.append(new_line)
        changed_keys.append(param)

    return "\n".join(lines) + ("\n" if content.endswith("\n") else ""), changed_keys


def run_tune_pipeline(
    template: str = "gatk",
    rounds_limit: int = 30,
    my_hotkey: Optional[str] = None,
    force_sync: bool = False,
) -> Dict[str, Any]:
    logs: List[Dict[str, Any]] = []
    template = template.lower().strip()
    rounds_limit = max(5, min(rounds_limit, 100))
    hotkey = my_hotkey or get_my_hotkey()

    _log(logs, "init", "info", f"Starting tune pipeline for template={template}, rounds={rounds_limit}")

    config_flow = {
        "real_time_on_chain": False,
        "summary": (
            "Saving config in Local Lab writes configs/{tool}.conf to disk. "
            "The live miner re-reads this file on the next open round — not instantly on-chain."
        ),
        "steps": [
            "Edit config in Local Lab (or any editor) → file saved to configs/{tool}.conf",
            "Running miner polls every ~30s; on next open round it reads the updated file",
            "Miner runs variant calling, then POSTs tool_config to platform API (not Bittensor chain)",
            "Validators fetch submissions during scoring window and re-run your config",
            "One submission per round — edits during an in-flight call do not affect that round",
        ],
        "restart_required_for": ["MINER_TEMPLATE change", ".env / wallet / PLATFORM_URL changes"],
        "no_restart_for": ["Quality parameter changes in .conf files"],
    }
    _log(logs, "config_flow", "info", config_flow["summary"])

    limitations = {
        "other_miner_configs": (
            "Other miners' submitted tool_config is NOT exposed on the public leaderboard API. "
            "Only validators can fetch configs via POST /v2/get-submissions. "
            "This pipeline uses score breakdowns (snp_final, indel_final) and tuning heuristics instead."
        ),
        "haplotype_detail": (
            "Per-component hap.py metrics (precision, recall, FP rate, Ti/Tv) are validator-only. "
            "Public API provides snp_final, indel_final, combined_final per scored miner."
        ),
        "region_specific_configs": (
            "Cannot clone exact winner configs per chromosome. Recommendations are heuristic "
            "based on your score gaps vs top-miner medians and docs/tuning_guide.md."
        ),
    }
    _log(logs, "limitations", "warn", limitations["other_miner_configs"])

    try:
        current_content = read_config(template)["content"]
        current_params = extract_tool_options(template)
    except Exception as exc:
        _log(logs, "config", "error", f"Failed to read current config: {exc}")
        raise

    leaderboards = _load_rounds_data(rounds_limit, force_sync, logs)
    hotkey_to_coldkey = _get_hotkey_coldkey_map(force=force_sync)
    region_analysis = _analyze_regions(leaderboards, logs)
    top_analysis = _analyze_top_miners(leaderboards, hotkey_to_coldkey, logs)
    my_perf = _analyze_my_performance(hotkey, leaderboards, logs)
    diagnosis = _diagnose(my_perf, top_analysis["summary"], top_analysis["recent_winners"], logs)
    recommendations = _build_recommendations(
        template, current_params, diagnosis, top_analysis["summary"], logs,
    )

    proposed_content, applied_keys = _apply_recommendations_to_content(current_content, recommendations)
    diff_lines = []
    for rec in recommendations:
        if rec.get("selected", True):
            diff_lines.append(f"- {rec['param']}: {rec['current_value']} → {rec['proposed_value']}")

    _log(
        logs, "complete", "success",
        f"Pipeline complete — {len(recommendations)} recommendation(s), {len(applied_keys)} param(s) in proposed config",
    )

    return {
        "template": template,
        "rounds_analyzed": len(leaderboards),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "my_hotkey": hotkey,
        "config_flow": config_flow,
        "limitations": limitations,
        "current_config": {
            "content": current_content,
            "params": current_params,
        },
        "region_analysis": region_analysis,
        "top_miner_analysis": top_analysis,
        "my_performance": my_perf,
        "diagnosis": diagnosis,
        "recommendations": recommendations,
        "proposed_config": {
            "content": proposed_content,
            "changed_params": applied_keys,
            "diff_summary": diff_lines,
        },
        "logs": logs,
    }


def apply_tune_recommendations(
    template: str,
    recommendations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    content = read_config(template)["content"]
    new_content, changed = _apply_recommendations_to_content(content, recommendations)
    write_config(template, new_content)
    return {
        "template": template,
        "changed_params": changed,
        "content": new_content,
        "message": f"Applied {len(changed)} parameter(s) to configs/{template}.conf",
    }
