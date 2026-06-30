"""OpenRouter LLM advisory layer for the tune pipeline (rank + augment rule-based recs)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Strong reasoning default; override via OPENROUTER_MODEL in .env
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Rollback / rollback+upgrade recommendations are never removed by the LLM.
PROTECTED_SOURCES = frozenset({"rollback", "rollback_upgrade"})


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.miner")


def get_llm_tune_status() -> Dict[str, Any]:
    _load_env()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    enabled = os.getenv("TUNE_LLM_ENABLED", "true").lower() not in ("0", "false", "no")
    return {
        "configured": bool(key),
        "enabled": enabled and bool(key),
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip() or DEFAULT_OPENROUTER_MODEL,
        "provider": "openrouter",
    }


def _get_param_specs(template: str) -> Dict[str, Any]:
    from templates.tool_params import (
        BCFTOOLS_QUALITY_PARAMS,
        DEEPVARIANT_QUALITY_PARAMS,
        GATK_QUALITY_PARAMS,
    )
    return {
        "gatk": GATK_QUALITY_PARAMS,
        "deepvariant": DEEPVARIANT_QUALITY_PARAMS,
        "bcftools": BCFTOOLS_QUALITY_PARAMS,
    }.get(template, {})


def _clamp_value(template: str, param: str, value: Any) -> Any:
    from local_lab.backend.services.tune_service import _clamp_param
    return _clamp_param(template, param, value)


def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _build_llm_context(
    template: str,
    current_params: Dict[str, Any],
    diagnosis: Dict[str, Any],
    rule_recommendations: List[Dict[str, Any]],
    top_summary: Dict[str, Any],
    my_perf: Optional[Dict[str, Any]],
    last_update_analysis: Optional[Dict[str, Any]],
    region_analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    latest = (my_perf or {}).get("latest_round") or {}
    history = (my_perf or {}).get("history") or []
    recent_regions = (region_analysis or {}).get("recent_rounds") or []

    return {
        "template": template,
        "current_config": current_params,
        "diagnosis": {
            "interpretation": diagnosis.get("interpretation"),
            "gaps": diagnosis.get("gaps"),
            "primary_weakness": diagnosis.get("primary_weakness"),
            "latest_round": diagnosis.get("latest_round"),
            "average": diagnosis.get("average"),
        },
        "top_miner_medians": {
            "combined": top_summary.get("median_combined"),
            "snp": top_summary.get("median_snp"),
            "indel": top_summary.get("median_indel"),
        },
        "my_latest_scores": {
            "combined": latest.get("combined_final"),
            "snp": latest.get("snp_final"),
            "indel": latest.get("indel_final"),
            "rank": latest.get("rank"),
            "region": latest.get("region"),
        },
        "my_recent_rounds": [
            {
                "round": r.get("round_id"),
                "region": r.get("region"),
                "combined": r.get("combined_final"),
                "snp": r.get("snp_final"),
                "indel": r.get("indel_final"),
                "rank": r.get("rank"),
            }
            for r in history[:8]
        ],
        "recent_regions": recent_regions[:6],
        "last_update_analysis": {
            "score_before": last_update_analysis.get("score_before") if last_update_analysis else None,
            "score_after": last_update_analysis.get("score_after") if last_update_analysis else None,
            "difference": last_update_analysis.get("difference") if last_update_analysis else None,
            "needs_rollback": last_update_analysis.get("needs_rollback") if last_update_analysis else None,
            "message": last_update_analysis.get("message") if last_update_analysis else None,
        } if last_update_analysis else None,
        "rule_candidates": [
            {
                "param": r["param"],
                "current_value": r["current_value"],
                "proposed_value": r["proposed_value"],
                "source": r.get("source"),
                "reason": r.get("reason"),
                "priority": r.get("priority"),
            }
            for r in rule_recommendations
        ],
        "allowed_params": list(_get_param_specs(template).keys()),
    }


def _call_openrouter(model: str, api_key: str, system: str, user: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://theminos.ai",
        "X-Title": "Minos Local Lab Tune Pipeline",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.15,
        "max_tokens": 2500,
    }
    with httpx.Client(timeout=90.0) as client:
        resp = client.post(OPENROUTER_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""


def _merge_llm_ranking(
    template: str,
    rule_recommendations: List[Dict[str, Any]],
    llm_payload: Dict[str, Any],
    current_params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    ranked = llm_payload.get("ranked_recommendations") or []
    if not isinstance(ranked, list):
        ranked = []

    by_param: Dict[str, Dict[str, Any]] = {r["param"]: dict(r) for r in rule_recommendations}
    protected = [r for r in rule_recommendations if r.get("source") in PROTECTED_SOURCES]
    mutable = [r for r in rule_recommendations if r.get("source") not in PROTECTED_SOURCES]

    llm_by_param: Dict[str, Dict[str, Any]] = {}
    for item in ranked:
        if not isinstance(item, dict):
            continue
        param = item.get("param")
        if param:
            llm_by_param[str(param)] = item

    merged: List[Dict[str, Any]] = []

    # 1) Protected rollback recs — always first, always selected
    for rec in sorted(protected, key=lambda x: x.get("priority", 0)):
        out = dict(rec)
        out["selected"] = True
        out["llm_rank"] = out.get("llm_rank", 0)
        out["llm_confidence"] = "high"
        merged.append(out)

    # 2) Re-rank mutable rule recs per LLM order
    seen_params = {r["param"] for r in protected}
    order: List[str] = []
    for item in ranked:
        p = item.get("param")
        if p and p not in seen_params and p in by_param:
            order.append(p)
            seen_params.add(p)
    for rec in mutable:
        if rec["param"] not in seen_params:
            order.append(rec["param"])
            seen_params.add(rec["param"])

    rank_idx = len(merged) + 1
    for param in order:
        if param not in by_param:
            continue
        base = dict(by_param[param])
        llm_item = llm_by_param.get(param, {})
        if llm_item.get("reason"):
            base["reason"] = str(llm_item["reason"])
        base["selected"] = bool(llm_item.get("selected", True))
        base["llm_rank"] = int(llm_item.get("priority") or rank_idx)
        base["llm_confidence"] = str(llm_item.get("confidence") or "medium")
        if base.get("source") not in PROTECTED_SOURCES and llm_item:
            base["source"] = "llm_ranked"
        merged.append(base)
        rank_idx += 1

    # 3) Optional new LLM-only suggestions (validated + clamped)
    specs = _get_param_specs(template)
    for item in ranked:
        param = item.get("param")
        if not param or param in by_param or param not in specs:
            continue
        proposed = _clamp_value(template, param, item.get("proposed_value"))
        cur = current_params.get(param)
        from local_lab.backend.services.tune_service import _param_values_equal
        if _param_values_equal(cur, proposed):
            continue
        merged.append({
            "id": f"llm_{param}_{proposed}",
            "param": param,
            "current_value": cur,
            "proposed_value": proposed,
            "reason": str(item.get("reason") or "Suggested by LLM advisory layer."),
            "priority": int(item.get("priority") or rank_idx),
            "source": "llm_advisory",
            "selected": bool(item.get("selected", False)),
            "llm_rank": int(item.get("priority") or rank_idx),
            "llm_confidence": str(item.get("confidence") or "medium"),
        })
        rank_idx += 1

    merged.sort(key=lambda r: (0 if r.get("source") == "rollback" else 1, r.get("llm_rank", r.get("priority", 99))))
    return merged


def enhance_recommendations_with_llm(
    template: str,
    current_params: Dict[str, Any],
    diagnosis: Dict[str, Any],
    rule_recommendations: List[Dict[str, Any]],
    top_summary: Dict[str, Any],
    my_perf: Optional[Dict[str, Any]],
    last_update_analysis: Optional[Dict[str, Any]],
    region_analysis: Optional[Dict[str, Any]],
    logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    from local_lab.backend.services.tune_service import _log

    status = get_llm_tune_status()
    advisory: Dict[str, Any] = {
        "enabled": status["enabled"],
        "configured": status["configured"],
        "model": status["model"],
        "used": False,
        "summary": None,
        "strategy": None,
        "notes": None,
        "error": None,
    }

    if not status["configured"]:
        _log(logs, "llm_advisory", "info", "OPENROUTER_API_KEY not set — using rule-based recommendations only")
        advisory["notes"] = "Add OPENROUTER_API_KEY to .env to enable LLM ranking."
        return {"recommendations": rule_recommendations, "llm_advisory": advisory}

    if not status["enabled"]:
        _log(logs, "llm_advisory", "info", "TUNE_LLM_ENABLED=false — skipping LLM layer")
        return {"recommendations": rule_recommendations, "llm_advisory": advisory}

    if not rule_recommendations:
        _log(logs, "llm_advisory", "info", "No rule candidates — LLM layer skipped (nothing to rank)")
        advisory["notes"] = "Rule engine produced no candidates; LLM ranking skipped."
        return {"recommendations": rule_recommendations, "llm_advisory": advisory}

    _load_env()
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = status["model"]
    context = _build_llm_context(
        template, current_params, diagnosis, rule_recommendations,
        top_summary, my_perf, last_update_analysis, region_analysis,
    )

    system_prompt = """You are an expert computational genomics advisor for the Minos Bittensor subnet (variant calling competition on GIAB-style WGS BAMs).

Minos scores miners using hap.py F1 metrics: snp_final, indel_final, combined_final (public leaderboard API).
You receive rule-based tuning candidates plus the miner's score history. Your job:
1) Rank and prioritize rule candidates (do NOT invent rollback reversals — rollback items are mandatory if present).
2) Optionally add at most 2 NEW parameter suggestions from allowed_params only.
3) Deselect low-value or conflicting changes (except rollback source=rollback — always keep selected=true).
4) Explain tradeoffs briefly.

Respond with JSON only:
{
  "summary": "2-4 sentences on miner situation and recommended strategy",
  "strategy": "rollback|rollback_upgrade|aggressive_recall|precision|balanced",
  "ranked_recommendations": [
    {
      "param": "parameter_name",
      "proposed_value": <value>,
      "priority": 1,
      "selected": true,
      "confidence": "high|medium|low",
      "reason": "why this helps SNP/INDEL/combined on Minos scoring"
    }
  ],
  "notes": "optional caveats"
}

Rules:
- Use only params listed in allowed_params.
- proposed_value must be valid for GATK/DeepVariant/bcftools (bool as true/false, enums exact).
- If needs_rollback is true, keep rollback and rollback_upgrade items selected=true.
- If aggressive recall already failed, use rollback_upgrade strategy: revert bad values then suggest moderate improvements (NOT repeating the failed aggressive values).
- Prefer fewer high-confidence changes over many low-confidence ones."""

    user_prompt = (
        "Analyze this Minos miner tuning context and return ranked JSON recommendations:\n\n"
        + json.dumps(context, indent=2, default=str)
    )

    try:
        _log(logs, "llm_advisory", "info", f"Calling OpenRouter model={model} to rank {len(rule_recommendations)} rule candidate(s)")
        raw = _call_openrouter(model, api_key, system_prompt, user_prompt)
        parsed = _parse_json_response(raw)
        if not parsed:
            raise ValueError("LLM response was not valid JSON")

        merged = _merge_llm_ranking(template, rule_recommendations, parsed, current_params)
        advisory.update({
            "used": True,
            "summary": parsed.get("summary"),
            "strategy": parsed.get("strategy"),
            "notes": parsed.get("notes"),
        })
        _log(
            logs, "llm_advisory", "success",
            f"LLM ranked {len(merged)} recommendation(s) — strategy={parsed.get('strategy')}",
            {"model": model, "summary": parsed.get("summary")},
        )
        return {"recommendations": merged, "llm_advisory": advisory}
    except Exception as exc:
        _log(logs, "llm_advisory", "warn", f"LLM advisory failed ({exc}) — falling back to rule-based list")
        advisory["error"] = str(exc)
        advisory["notes"] = "LLM call failed; showing rule-based recommendations only."
        return {"recommendations": rule_recommendations, "llm_advisory": advisory}
