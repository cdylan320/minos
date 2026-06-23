"""Leaderboard + round-history analytics from the Minos platform public API."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / "local_lab" / ".cache" / "leaderboard"
ROUNDS_CACHE = CACHE_DIR / "rounds.json"
ROUNDS_DIR = CACHE_DIR / "rounds"

DEFAULT_PLATFORM = "https://api.theminos.ai"
CACHE_TTL_SECONDS = 120  # live/scoring rounds refresh quickly
FINALIZED_TTL_SECONDS = 3600  # finalized rounds are stable


def _platform_url() -> str:
    return os.getenv("PLATFORM_URL", DEFAULT_PLATFORM).rstrip("/")


def _round_file_id(round_id: str) -> str:
    return round_id.replace(":", "_").replace("+", "p")


def _round_path(round_id: str) -> Path:
    return ROUNDS_DIR / f"{_round_file_id(round_id)}.json"


def _short_hotkey(hk: str) -> str:
    if len(hk) <= 16:
        return hk
    return f"{hk[:6]}...{hk[-4:]}"


def _format_round_label(round_id: str) -> str:
    try:
        dt = datetime.fromisoformat(round_id.replace("Z", "+00:00"))
        return dt.strftime("%m/%d %H:%M")
    except ValueError:
        return round_id[:16]


def _get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{_platform_url()}{path}"
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _cache_age(path: Path) -> Optional[float]:
    if not path.exists():
        return None
    return time.time() - path.stat().st_mtime


def _read_cache(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fetch_rounds(limit: int = 100, force: bool = False) -> Dict[str, Any]:
    limit = max(1, min(limit, 100))
    if not force and _cache_age(ROUNDS_CACHE) is not None and _cache_age(ROUNDS_CACHE) < CACHE_TTL_SECONDS:
        cached = _read_cache(ROUNDS_CACHE)
        if cached and cached.get("rounds"):
            return cached

    data = _get_json("/scoring/rounds", {"limit": limit})
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "platform_url": _platform_url(),
        **data,
    }
    _write_cache(ROUNDS_CACHE, payload)
    return payload


def fetch_round_leaderboard(round_id: str, force: bool = False) -> Dict[str, Any]:
    path = _round_path(round_id)
    rounds_data = fetch_rounds(force=False)
    round_meta = next(
        (r for r in rounds_data.get("rounds", []) if r.get("round_id") == round_id),
        None,
    )
    is_finalized = bool(round_meta and round_meta.get("is_finalized"))
    ttl = FINALIZED_TTL_SECONDS if is_finalized else CACHE_TTL_SECONDS

    if not force and _cache_age(path) is not None and _cache_age(path) < ttl:
        cached = _read_cache(path)
        if cached and cached.get("entries") is not None:
            return cached

    encoded = quote(round_id, safe="")
    data = _get_json(f"/scoring/rounds/{encoded}/leaderboard")
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "platform_url": _platform_url(),
        **data,
    }
    _write_cache(path, payload)
    return payload


def sync_all_finalized(force: bool = False, max_rounds: int = 50) -> Dict[str, Any]:
    """Prefetch leaderboards for finalized rounds (for analytics)."""
    rounds_data = fetch_rounds(limit=100, force=force)
    finalized = [
        r for r in rounds_data.get("rounds", [])
        if r.get("is_finalized")
    ][:max_rounds]

    synced = 0
    errors: List[str] = []
    for r in finalized:
        rid = r["round_id"]
        try:
            fetch_round_leaderboard(rid, force=force)
            synced += 1
        except Exception as exc:
            errors.append(f"{rid}: {exc}")

    return {
        "synced": synced,
        "finalized_available": len(finalized),
        "errors": errors,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def list_rounds(limit: int = 100) -> Dict[str, Any]:
    data = fetch_rounds(limit=limit)
    rounds = []
    for r in data.get("rounds", []):
        rounds.append({
            **r,
            "label": _format_round_label(r.get("round_id", "")),
        })
    latest_finalized = next((r for r in rounds if r.get("is_finalized")), None)
    live = next((r for r in rounds if r.get("is_live")), None)
    return {
        "rounds": rounds,
        "latest_finalized_round_id": latest_finalized.get("round_id") if latest_finalized else None,
        "live_round_id": live.get("round_id") if live else None,
        "fetched_at": data.get("fetched_at"),
    }


def get_leaderboard(round_id: Optional[str] = None, mode: str = "latest") -> Dict[str, Any]:
    rounds_info = list_rounds()
    rounds = rounds_info["rounds"]

    if mode == "live":
        round_id = rounds_info.get("live_round_id")
        if not round_id:
            raise ValueError("No live round available")
    elif round_id:
        # Explicit round_id from history picker — do not override with latest.
        pass
    else:
        round_id = rounds_info.get("latest_finalized_round_id")
        if not round_id:
            raise ValueError("No finalized round available")

    lb = fetch_round_leaderboard(round_id)
    entries = lb.get("entries", [])
    round_meta = lb.get("round", {})

    return {
        "round_id": round_id,
        "round": {
            **round_meta,
            "label": _format_round_label(round_id),
        },
        "entries": entries,
        "total_miners": len(entries),
        "scored_count": sum(1 for e in entries if e.get("status") == "scored"),
        "fetched_at": lb.get("fetched_at"),
    }


def _load_cached_finalized_leaderboards() -> List[Dict[str, Any]]:
    rounds_data = fetch_rounds()
    out: List[Dict[str, Any]] = []
    for r in rounds_data.get("rounds", []):
        if not r.get("is_finalized"):
            continue
        rid = r["round_id"]
        cached = _read_cache(_round_path(rid))
        if cached and cached.get("entries"):
            out.append(cached)
    return out


def compute_analytics(force_sync: bool = False) -> Dict[str, Any]:
    if force_sync:
        sync_all_finalized(force=True)

    leaderboards = _load_cached_finalized_leaderboards()
    if len(leaderboards) < 3:
        sync_all_finalized(force=force_sync)
        leaderboards = _load_cached_finalized_leaderboards()

    winner_counts: Dict[str, int] = {}
    podium_counts: Dict[str, int] = {}
    score_sums: Dict[str, float] = {}
    score_counts: Dict[str, int] = {}
    participation: Dict[str, int] = {}
    tool_counts: Dict[str, int] = {}
    uid_map: Dict[str, int] = {}
    round_winners: List[Dict[str, Any]] = []

    for lb in leaderboards:
        rid = lb.get("round", {}).get("round_id", "")
        region = lb.get("round", {}).get("region", "")
        entries = sorted(lb.get("entries", []), key=lambda e: e.get("rank", 9999))

        if entries:
            w = entries[0]
            hk = w.get("hotkey", "")
            if hk:
                winner_counts[hk] = winner_counts.get(hk, 0) + 1
                round_winners.append({
                    "round_id": rid,
                    "label": _format_round_label(rid),
                    "region": region,
                    "hotkey": hk,
                    "short_hotkey": _short_hotkey(hk),
                    "uid": w.get("uid"),
                    "score": w.get("combined_final"),
                })

        for e in entries:
            hk = e.get("hotkey", "")
            if not hk:
                continue
            rank = e.get("rank", 999)
            if rank <= 3:
                podium_counts[hk] = podium_counts.get(hk, 0) + 1
            score = e.get("combined_final")
            if score is not None:
                score_sums[hk] = score_sums.get(hk, 0.0) + float(score)
                score_counts[hk] = score_counts.get(hk, 0) + 1
            participation[hk] = participation.get(hk, 0) + 1
            tool = e.get("tool_name") or "unknown"
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            if e.get("uid") is not None:
                uid_map[hk] = e["uid"]

    rounds_analyzed = len(leaderboards)
    win_rate: Dict[str, float] = {}
    for hk, wins in winner_counts.items():
        parts = participation.get(hk, 1)
        win_rate[hk] = wins / max(parts, 1)

    avg_scores = {
        hk: score_sums[hk] / score_counts[hk]
        for hk in score_sums
        if score_counts.get(hk, 0) > 0
    }

    def _rank_table(counts: Dict[str, int], score_key: str = "wins") -> List[Dict[str, Any]]:
        rows = []
        for hk, val in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            rows.append({
                "hotkey": hk,
                "short_hotkey": _short_hotkey(hk),
                "uid": uid_map.get(hk),
                score_key: val,
                "rounds_participated": participation.get(hk, 0),
                "avg_score": round(avg_scores.get(hk, 0.0), 4) if hk in avg_scores else None,
                "win_rate": round(win_rate.get(hk, 0.0), 4) if hk in win_rate else None,
                "podium_count": podium_counts.get(hk, 0),
            })
        return rows

    return {
        "rounds_analyzed": rounds_analyzed,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "winner_leaderboard": _rank_table(winner_counts, "wins"),
        "avg_score_leaderboard": sorted(
            [
                {
                    "hotkey": hk,
                    "short_hotkey": _short_hotkey(hk),
                    "uid": uid_map.get(hk),
                    "avg_score": round(v, 4),
                    "rounds_participated": participation.get(hk, 0),
                    "wins": winner_counts.get(hk, 0),
                }
                for hk, v in avg_scores.items()
            ],
            key=lambda x: (-x["avg_score"], -x["rounds_participated"]),
        ),
        "round_winners": sorted(round_winners, key=lambda x: x.get("round_id", ""), reverse=True),
        "tool_distribution": tool_counts,
        "unique_miners": len(participation),
    }


def get_miner_history(hotkey: str) -> Dict[str, Any]:
    hotkey = hotkey.strip()
    leaderboards = _load_cached_finalized_leaderboards()
    if len(leaderboards) < 2:
        sync_all_finalized()
        leaderboards = _load_cached_finalized_leaderboards()

    history: List[Dict[str, Any]] = []
    wins = 0
    podiums = 0

    for lb in leaderboards:
        rid = lb.get("round", {}).get("round_id", "")
        region = lb.get("round", {}).get("region", "")
        for e in lb.get("entries", []):
            if e.get("hotkey") != hotkey:
                continue
            rank = e.get("rank")
            if rank == 1:
                wins += 1
            if rank is not None and rank <= 3:
                podiums += 1
            history.append({
                "round_id": rid,
                "label": _format_round_label(rid),
                "region": region,
                "rank": rank,
                "combined_final": e.get("combined_final"),
                "weight": e.get("weight"),
                "eligible": e.get("eligible"),
                "participation_count": e.get("participation_count"),
                "validator_count": e.get("validator_count"),
                "tool_name": e.get("tool_name"),
                "status": e.get("status"),
            })
            break

    history.sort(key=lambda x: x.get("round_id", ""), reverse=True)
    scores = [h["combined_final"] for h in history if h.get("combined_final") is not None]

    return {
        "hotkey": hotkey,
        "short_hotkey": _short_hotkey(hotkey),
        "rounds_found": len(history),
        "wins": wins,
        "podiums": podiums,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
        "best_score": max(scores) if scores else None,
        "worst_score": min(scores) if scores else None,
        "history": history,
    }


def get_my_hotkey() -> Optional[str]:
    """Resolve local miner hotkey from .env wallet (for highlighting in UI)."""
    import json as _json
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    wallet_name = os.getenv("WALLET_NAME", "")
    wallet_hotkey = os.getenv("WALLET_HOTKEY", "")
    if not wallet_name or not wallet_hotkey:
        return None
    path = Path.home() / ".bittensor" / "wallets" / wallet_name / "hotkeys" / wallet_hotkey
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        return data.get("ss58Address")
    except (OSError, _json.JSONDecodeError):
        return None


def get_network_status() -> Dict[str, Any]:
    data = fetch_rounds()
    rounds = data.get("rounds", [])
    by_status: Dict[str, int] = {}
    for r in rounds:
        st = r.get("status", "unknown")
        by_status[st] = by_status.get(st, 0) + 1

    live = next((r for r in rounds if r.get("is_live")), None)
    latest_final = next((r for r in rounds if r.get("is_finalized")), None)

    return {
        "platform_url": _platform_url(),
        "rounds_in_history": len(rounds),
        "status_breakdown": by_status,
        "live_round": live,
        "latest_finalized": latest_final,
        "fetched_at": data.get("fetched_at"),
    }
