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


def parse_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    cleaned = date_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _analyze_my_performance(
    hotkey: Optional[str],
    leaderboards: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
    template: str,
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
                "submitted_at": e.get("submitted_at") or rnd.get("round_id"),
            })

    if not rows:
        _log(logs, "my_miner", "warn", f"Hotkey {_short_hotkey(hotkey)} not found in cached round history")
        return {"hotkey": hotkey, "short_hotkey": _short_hotkey(hotkey), "rounds_found": 0, "history": []}

    # Load config history for this template
    from local_lab.backend.services.config_service import read_config_history
    cfg_history = [c for c in read_config_history() if c.get("template") == template]

    # Map each config change to the first round submitted/run after it
    round_updates: Dict[str, List[Dict[str, Any]]] = {}
    chronological_rounds = sorted(rows, key=lambda x: parse_date(x.get("submitted_at") or x.get("round_id")))

    for c in cfg_history:
        t_c = parse_date(c.get("timestamp"))
        target_round = None
        for r in chronological_rounds:
            t_r = parse_date(r.get("submitted_at") or r.get("round_id"))
            if t_r > t_c:
                target_round = r
                break
        if target_round:
            rid = target_round["round_id"]
            round_updates.setdefault(rid, []).append(c)

    for r in rows:
        rid = r["round_id"]
        r["updates"] = round_updates.get(rid, [])

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


def _analyze_last_updates(
    my_perf: Optional[Dict[str, Any]],
    logs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not my_perf or not my_perf.get("history"):
        return None

    history = my_perf["history"]
    rounds_with_updates = [r for r in history if r.get("updates")]

    if not rounds_with_updates:
        _log(logs, "tune_logic", "info", "No previous Local Lab config updates found in analyzed round range")
        return None

    r_updated = rounds_with_updates[0]
    rid = r_updated["round_id"]

    history_chrono = sorted(history, key=lambda x: parse_date(x.get("submitted_at") or x.get("round_id")))
    idx = -1
    for i, r in enumerate(history_chrono):
        if r["round_id"] == rid:
            idx = i
            break

    if idx <= 0:
        _log(logs, "tune_logic", "info", f"Found config update in round {_format_round_short(rid)}, but no previous round to compare against")
        return None

    r_prev = history_chrono[idx - 1]

    score_now = r_updated.get("combined_final")
    score_prev = r_prev.get("combined_final")

    if score_now is None or score_prev is None:
        return None

    diff = score_now - score_prev
    updates_desc = []
    for u in r_updated["updates"]:
        for ch in u.get("changes", []):
            updates_desc.append(f"{ch['param']} ({ch['old_value']} -> {ch['new_value']})")

    updates_str = ", ".join(updates_desc)

    analysis_msg = ""
    if diff > 0.01:
        analysis_msg = (
            f"Your last configuration update ({updates_str}) in round {_format_round_short(rid)} "
            f"saw your score IMPROVE by {diff:+.4f} (from {score_prev:.4f} to {score_now:.4f}). This change is performing well!"
        )
        _log(logs, "tune_logic", "success", analysis_msg)
    elif diff < -0.01:
        analysis_msg = (
            f"Your last configuration update ({updates_str}) in round {_format_round_short(rid)} "
            f"saw your score DECREASE by {diff:.4f} (from {score_prev:.4f} to {score_now:.4f}). Consider reverting or adjusting further."
        )
        _log(logs, "tune_logic", "warn", analysis_msg)
    else:
        analysis_msg = (
            f"Your last configuration update ({updates_str}) in round {_format_round_short(rid)} "
            f"kept your score stable (change of {diff:+.4f}, from {score_prev:.4f} to {score_now:.4f})."
        )
        _log(logs, "tune_logic", "info", analysis_msg)

    return {
        "round_id": rid,
        "round_label": _format_round_short(rid),
        "score_before": score_prev,
        "score_after": score_now,
        "difference": diff,
        "message": analysis_msg,
        "updates": r_updated["updates"]
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

    # Fetch and evaluate quality gaps to customize recommendations dynamically
    gaps = diagnosis.get("gaps", {})
    combined_gap = float(gaps.get("combined", {}).get("value", 0.0) or 0.0)
    snp_gap = float(gaps.get("snp", {}).get("value", 0.0) or 0.0)
    indel_gap = float(gaps.get("indel", {}).get("value", 0.0) or 0.0)

    _log(
        logs, "recommendations_engine", "info",
        f"Evaluating score gaps vs top miners: Combined={combined_gap:+.4f}, SNP={snp_gap:+.4f}, INDEL={indel_gap:+.4f}"
    )

    if template == "gatk":
        # PCR indel model is always NONE for PCR-free benchmark BAMs
        if current.get("pcr_indel_model") != "NONE":
            add(
                "pcr_indel_model", "NONE",
                "GIAB and Minos BAMs are PCR-free — setting pcr_indel_model to NONE eliminates unnecessary conservative filtering and restores critical variant recall.",
                1, "tuning_guide",
            )

        # 1. Calling confidence threshold (standard_min_confidence_threshold_for_calling)
        conf = float(current.get("standard_min_confidence_threshold_for_calling", 30))
        if combined_gap > 0.15:
            if conf > 10.0:
                add(
                    "standard_min_confidence_threshold_for_calling", 10.0,
                    f"Your score has a massive gap of {combined_gap:.4f} vs top miners. Lowering calling threshold from {conf} to 10.0 drastically increases variant discovery sensitivity to catch up.",
                    2, "score_diagnosis",
                )
        elif combined_gap > 0.05:
            if conf > 15.0:
                add(
                    "standard_min_confidence_threshold_for_calling", 15.0,
                    f"With a gap of {combined_gap:.4f}, lowering the calling threshold from {conf} to 15.0 improves variant recall while maintaining competitive precision.",
                    2, "score_diagnosis",
                )
        elif combined_gap > 0.01:
            if conf > 20.0:
                add(
                    "standard_min_confidence_threshold_for_calling", 20.0,
                    f"Lowering calling threshold slightly from {conf} to 20.0 helps recover borderline SNPs to close the {combined_gap:.4f} score gap.",
                    2, "score_diagnosis",
                )

        # 2. Genotyping priors (heterozygosity and indel_heterozygosity)
        snp_het = float(current.get("heterozygosity", 0.001))
        indel_het = float(current.get("indel_heterozygosity", 0.000125))
        if combined_gap > 0.05:
            if snp_het < 0.003:
                add(
                    "heterozygosity", 0.003,
                    f"Raising SNP heterozygosity calling prior from {snp_het} to 0.003 shifts the posterior genotype model towards variants, rescuing marginal SNPs under high-depth.",
                    3, "score_diagnosis",
                )
            if indel_het < 0.0003:
                add(
                    "indel_heterozygosity", 0.0003,
                    f"Increasing INDEL heterozygosity calling prior from {indel_het} to 0.0003 instructs the genotyper to keep low-likelihood indel events, significantly boosting INDEL recall.",
                    3, "score_diagnosis",
                )
        elif combined_gap > 0.01:
            if snp_het < 0.002:
                add(
                    "heterozygosity", 0.002,
                    f"Slightly raising heterozygosity prior from {snp_het} to 0.002 helps GATK genotype borderline SNPs.",
                    3, "score_diagnosis",
                )
            if indel_het < 0.0002:
                add(
                    "indel_heterozygosity", 0.0002,
                    f"Slightly increasing indel heterozygosity prior from {indel_het} to 0.0002 improves INDEL sensitivity.",
                    3, "score_diagnosis",
                )

        # 3. Assembly Graph & Branch recovery
        recover_branches = current.get("recover_all_dangling_branches", "false")
        if str(recover_branches).lower() == "false" and combined_gap > 0.02:
            add(
                "recover_all_dangling_branches", "true",
                "Enabling recover_all_dangling_branches allows GATK to rescue assembly paths that terminate abruptly, recovering vital indels/SNPs at read boundaries.",
                4, "assembly_opt",
            )

        min_prune = int(current.get("min_pruning", 2))
        if min_prune > 1 and combined_gap > 0.04:
            add(
                "min_pruning", 1,
                "Lowering min_pruning from 2 to 1 stops the assembly graph from pruning rare candidate paths, salvaging variants in low-coverage or highly diverse loci.",
                4, "assembly_opt",
            )

        max_alt = int(current.get("max_alternate_alleles", 6))
        if max_alt < 12 and combined_gap > 0.02:
            add(
                "max_alternate_alleles", 12,
                "Increasing maximum alternate alleles to genotype from 6 to 12 prevents multi-allelic sites in complex benchmark windows from being skipped.",
                4, "assembly_opt",
            )

        # 4. Filters & Reads Optimization
        base_q = int(current.get("min_base_quality_score", 10))
        if combined_gap > 0.10:
            if base_q > 5:
                add(
                    "min_base_quality_score", 5,
                    f"With a gap of {combined_gap:.4f}, lowering base quality threshold from {base_q} to 5 rescues variant-carrying reads with borderline-quality base positions.",
                    5, "score_diagnosis",
                )
        elif combined_gap > 0.02:
            if base_q > 7:
                add(
                    "min_base_quality_score", 7,
                    "Lowering base quality threshold slightly to 7 captures variants lying on borderline read bases.",
                    5, "score_diagnosis",
                )

        map_q = int(current.get("min_mapping_quality_score", 20))
        if combined_gap > 0.10:
            if map_q > 12:
                add(
                    "min_mapping_quality_score", 12,
                    f"Decreasing minimum mapping quality from {map_q} to 12 allows variant calling in repetitive or low-mappability regions where standard filters throw away valid alignments.",
                    5, "score_diagnosis",
                )
        elif combined_gap > 0.02:
            if map_q > 15:
                add(
                    "min_mapping_quality_score", 15,
                    "Lowering minimum mapping quality to 15 helps recover variant calls in homologous and complex regions.",
                    5, "score_diagnosis",
                )

        max_reads_pos = int(current.get("max_reads_per_alignment_start", 50))
        if max_reads_pos < 150 and combined_gap > 0.02:
            add(
                "max_reads_per_alignment_start", 150,
                "Benchmark regions suffer when reads are downsampled to 50. Raising max_reads_per_alignment_start to 150 retains deep coverage alignments, boosting genotype confidence.",
                6, "depth_opt",
            )

    elif template == "deepvariant":
        if current.get("model_type") != "WGS":
            add("model_type", "WGS", "Minos BAMs are whole-genome — WES mode hurts scores.", 1, "tuning_guide")

        # Phasing & Haplotype-aware calling (HUGE scores booster)
        sort_by_hap = current.get("sort_by_haplotypes", "false")
        phase_reads = current.get("phase_reads", "false")
        if str(sort_by_hap).lower() == "false" and combined_gap > 0.01:
            add(
                "sort_by_haplotypes", "true",
                "DeepVariant uses CNN image classification. Enabling sort_by_haplotypes sorts aligned reads by their phased haplotype, creating clear visual structures that dramatically improve calling precision and recall.",
                1, "tuning_guide",
            )
        if str(phase_reads).lower() == "false" and combined_gap > 0.01:
            add(
                "phase_reads", "true",
                "Phasing reads complements haplotype-aware sorting, allowing genotype evaluation using haplotype context.",
                1, "tuning_guide",
            )

        # Candidate variant thresholds in make_examples
        vsc_snp = float(current.get("vsc_min_fraction_snps", 0.12))
        vsc_indel = float(current.get("vsc_min_fraction_indels", 0.12))
        if combined_gap > 0.04:
            if vsc_snp > 0.05:
                add(
                    "vsc_min_fraction_snps", 0.05,
                    f"Lowering make_examples SNP candidate threshold from {vsc_snp} to 0.05 ensures borderline SNPs are passed to the CNN model rather than being filtered prematurely.",
                    2, "score_diagnosis",
                )
            if vsc_indel > 0.05:
                add(
                    "vsc_min_fraction_indels", 0.05,
                    "Lowering INDEL candidate fraction to 0.05 ensures marginal indels are evaluated by the deep learning classifier.",
                    2, "score_diagnosis",
                )

        # Read quality filters
        mq = int(current.get("min_mapping_quality", 5))
        bq = int(current.get("min_base_quality", 10))
        if combined_gap > 0.05:
            if mq > 2:
                add("min_mapping_quality", 2, "Lowering candidate read mapping quality filter to 2 rescues alignments in homologous regions.", 3, "score_diagnosis")
            if bq > 5:
                add("min_base_quality", 5, "Lowering base quality threshold to 5 recovers candidate reads with minor sequencing errors.", 3, "score_diagnosis")

        # Postprocessing filters
        q_filt = float(current.get("qual_filter", 1.0))
        if q_filt > 0.0 and combined_gap > 0.02:
            add(
                "qual_filter", 0.0,
                "Setting qual_filter to 0.0 disables post-calling filters, allowing DeepVariant to output all calls to maximize recall score on the platform.",
                4, "score_diagnosis",
            )

    elif template == "bcftools":
        # BAQ Recalculation suppression
        no_baq = current.get("no_BAQ", "false")
        if str(no_baq).lower() == "false" and combined_gap > 0.01:
            add(
                "no_BAQ", "true",
                "Base Alignment Quality (BAQ) recalculation can over-suppress real variants near indels, causing severe recall gaps. Setting no_BAQ=true is standard practice for high variant discovery sensitivity.",
                1, "tuning_guide",
            )

        # Depth limits
        max_depth = int(current.get("max_depth", 250))
        if max_depth < 1000 and combined_gap > 0.02:
            add(
                "max_depth", 1000,
                "Your bcftools max_depth is 250. This can truncate variant calling at high-depth positions in WGS benchmark datasets. Raising to 1000 maintains coverage integration.",
                2, "score_diagnosis",
            )

        # Base/Mapping Quality filters
        bq = int(current.get("min_BQ", 13))
        if combined_gap > 0.04:
            if bq > 8:
                add("min_BQ", 8, f"Lowering min_BQ filter from {bq} to 8 captures reads with borderline base scores, closing the {combined_gap:.4f} gap.", 3, "score_diagnosis")
        elif combined_gap > 0.01:
            if bq > 10:
                add("min_BQ", 10, "Slightly lowering base quality filter to 10 improves variant calling sensitivity.", 3, "score_diagnosis")

        # INDEL calling priors
        gap_frac = float(current.get("gap_frac", 0.002))
        if gap_frac > 0.0005 and combined_gap > 0.02:
            add(
                "gap_frac", 0.0005,
                "Lowering the required fraction of gapped reads to 0.0005 makes bcftools far more sensitive to rare or low-allelic fraction indels, improving INDEL scores.",
                4, "score_diagnosis",
            )

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
    my_perf = _analyze_my_performance(hotkey, leaderboards, logs, template)
    last_up_analysis = _analyze_last_updates(my_perf, logs)
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
        "last_update_analysis": last_up_analysis,
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
    write_config(template, new_content, source="tune_recommendation")
    return {
        "template": template,
        "changed_params": changed,
        "content": new_content,
        "message": f"Applied {len(changed)} parameter(s) to configs/{template}.conf",
    }
