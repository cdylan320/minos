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


def _short_coldkey(ck: str) -> str:
    return _short_hotkey(ck)


_metagraph_cache: Dict[str, Any] = {"fetched_at": 0.0, "hotkey_to_coldkey": {}}
METAGRAPH_TTL_SECONDS = 300


def _get_hotkey_coldkey_map(force: bool = False) -> Dict[str, str]:
    """Map registered SN hotkeys to owner coldkeys via Bittensor metagraph."""
    age = time.time() - float(_metagraph_cache.get("fetched_at", 0.0))
    cached = _metagraph_cache.get("hotkey_to_coldkey") or {}
    if cached and not force and age < METAGRAPH_TTL_SECONDS:
        return cached

    try:
        import bittensor as bt

        network = os.getenv("SUBTENSOR_NETWORK", "finney")
        netuid = int(os.getenv("NETUID", "107"))
        if not hasattr(bt, "subtensor"):
            bt.subtensor = bt.Subtensor
        mg = bt.subtensor(network=network).metagraph(netuid)
        mapping = {
            mg.hotkeys[i]: mg.coldkeys[i]
            for i in range(len(mg.hotkeys))
            if mg.hotkeys[i] and mg.coldkeys[i]
        }
        _metagraph_cache["hotkey_to_coldkey"] = mapping
        _metagraph_cache["fetched_at"] = time.time()
        return mapping
    except Exception:
        return cached


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
    # Always keep finalized round cache complete so analytics reflect all
    # rounds returned by /scoring/rounds (API currently caps limit<=100).
    rounds_data = fetch_rounds(limit=100, force=force_sync)
    finalized_ids = [r["round_id"] for r in rounds_data.get("rounds", []) if r.get("is_finalized")]

    if force_sync:
        sync_all_finalized(force=True, max_rounds=100)
    else:
        missing = [rid for rid in finalized_ids if _read_cache(_round_path(rid)) is None]
        for rid in missing:
            try:
                fetch_round_leaderboard(rid, force=False)
            except Exception:
                # Keep analytics resilient even if one round fetch fails.
                pass

    leaderboards = _load_cached_finalized_leaderboards()

    hotkey_to_coldkey = _get_hotkey_coldkey_map(force=force_sync)

    winner_counts: Dict[str, int] = {}
    podium_counts: Dict[str, int] = {}
    score_sums: Dict[str, float] = {}
    score_counts: Dict[str, int] = {}
    participation: Dict[str, int] = {}
    tool_counts: Dict[str, int] = {}
    uid_map: Dict[str, int] = {}
    hotkeys_by_coldkey: Dict[str, set] = {}
    coldkey_winner_counts: Dict[str, int] = {}
    coldkey_podium_counts: Dict[str, int] = {}
    coldkey_score_sums: Dict[str, float] = {}
    coldkey_score_counts: Dict[str, int] = {}
    coldkey_participation: Dict[str, int] = {}
    coldkey_uids: Dict[str, set] = {}
    unmapped_hotkeys: set = set()
    round_winners: List[Dict[str, Any]] = []

    for lb in leaderboards:
        rid = lb.get("round", {}).get("round_id", "")
        region = lb.get("round", {}).get("region", "")
        entries = sorted(lb.get("entries", []), key=lambda e: (e.get("rank") is None, e.get("rank") or 9999))

        coldkeys_in_round: set = set()

        if entries:
            w = entries[0]
            hk = w.get("hotkey", "")
            if hk:
                winner_counts[hk] = winner_counts.get(hk, 0) + 1
                ck = hotkey_to_coldkey.get(hk)
                if ck:
                    coldkey_winner_counts[ck] = coldkey_winner_counts.get(ck, 0) + 1
                else:
                    unmapped_hotkeys.add(hk)
                round_winners.append({
                    "round_id": rid,
                    "label": _format_round_label(rid),
                    "region": region,
                    "hotkey": hk,
                    "short_hotkey": _short_hotkey(hk),
                    "coldkey": ck,
                    "short_coldkey": _short_coldkey(ck) if ck else None,
                    "uid": w.get("uid"),
                    "score": w.get("combined_final"),
                })

        for e in entries:
            hk = e.get("hotkey", "")
            if not hk:
                continue
            ck = hotkey_to_coldkey.get(hk)
            if ck:
                hotkeys_by_coldkey.setdefault(ck, set()).add(hk)
                coldkeys_in_round.add(ck)
                if e.get("uid") is not None:
                    coldkey_uids.setdefault(ck, set()).add(e["uid"])
            else:
                unmapped_hotkeys.add(hk)

            rank = e.get("rank")
            if isinstance(rank, int) and rank <= 3:
                podium_counts[hk] = podium_counts.get(hk, 0) + 1
                if ck:
                    coldkey_podium_counts[ck] = coldkey_podium_counts.get(ck, 0) + 1
            score = e.get("combined_final")
            if score is not None:
                score_sums[hk] = score_sums.get(hk, 0.0) + float(score)
                score_counts[hk] = score_counts.get(hk, 0) + 1
                if ck:
                    coldkey_score_sums[ck] = coldkey_score_sums.get(ck, 0.0) + float(score)
                    coldkey_score_counts[ck] = coldkey_score_counts.get(ck, 0) + 1
            participation[hk] = participation.get(hk, 0) + 1
            tool = e.get("tool_name") or "unknown"
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            if e.get("uid") is not None:
                uid_map[hk] = e["uid"]

        for ck in coldkeys_in_round:
            coldkey_participation[ck] = coldkey_participation.get(ck, 0) + 1

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

    coldkey_win_rate: Dict[str, float] = {}
    for ck, wins in coldkey_winner_counts.items():
        parts = coldkey_participation.get(ck, 1)
        coldkey_win_rate[ck] = wins / max(parts, 1)

    coldkey_avg_scores = {
        ck: coldkey_score_sums[ck] / coldkey_score_counts[ck]
        for ck in coldkey_score_sums
        if coldkey_score_counts.get(ck, 0) > 0
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

    def _hotkey_rows_for_coldkey(ck: str) -> List[Dict[str, Any]]:
        rows = []
        for hk in hotkeys_by_coldkey.get(ck, set()):
            rows.append({
                "hotkey": hk,
                "short_hotkey": _short_hotkey(hk),
                "uid": uid_map.get(hk),
                "wins": winner_counts.get(hk, 0),
                "rounds_participated": participation.get(hk, 0),
                "avg_score": round(avg_scores.get(hk, 0.0), 4) if hk in avg_scores else None,
                "win_rate": round(win_rate.get(hk, 0.0), 4) if hk in win_rate else None,
                "podium_count": podium_counts.get(hk, 0),
            })
        rows.sort(key=lambda x: (-x["wins"], -x["podium_count"], x["hotkey"]))
        return rows

    def _coldkey_rank_table(counts: Dict[str, int], score_key: str = "wins") -> List[Dict[str, Any]]:
        rows = []
        for ck, val in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            rows.append({
                "coldkey": ck,
                "short_coldkey": _short_coldkey(ck),
                "hotkey_count": len(hotkeys_by_coldkey.get(ck, set())),
                "uids": sorted(coldkey_uids.get(ck, set())),
                "hotkeys": _hotkey_rows_for_coldkey(ck),
                score_key: val,
                "rounds_participated": coldkey_participation.get(ck, 0),
                "avg_score": round(coldkey_avg_scores.get(ck, 0.0), 4) if ck in coldkey_avg_scores else None,
                "win_rate": round(coldkey_win_rate.get(ck, 0.0), 4) if ck in coldkey_win_rate else None,
                "podium_count": coldkey_podium_counts.get(ck, 0),
            })
        return rows

    return {
        "rounds_analyzed": rounds_analyzed,
        "rounds_available": len(finalized_ids),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "coldkey_mapping_available": bool(hotkey_to_coldkey),
        "unmapped_hotkey_count": len(unmapped_hotkeys),
        "winner_leaderboard": _rank_table(winner_counts, "wins"),
        "coldkey_winner_leaderboard": _coldkey_rank_table(coldkey_winner_counts, "wins"),
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
        "unique_coldkeys": len(hotkeys_by_coldkey),
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


def _wallet_dir() -> Optional[Path]:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    wallet_name = os.getenv("WALLET_NAME", "")
    if not wallet_name:
        return None
    path = Path.home() / ".bittensor" / "wallets" / wallet_name
    return path if path.exists() else None


def get_my_hotkey() -> Optional[str]:
    """Resolve local miner hotkey from .env wallet (for highlighting in UI)."""
    import json as _json
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    wallet_hotkey = os.getenv("WALLET_HOTKEY", "")
    wallet_dir = _wallet_dir()
    if not wallet_dir or not wallet_hotkey:
        return None
    path = wallet_dir / "hotkeys" / wallet_hotkey
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        return data.get("ss58Address")
    except (OSError, _json.JSONDecodeError):
        return None


def get_my_coldkey() -> Optional[str]:
    """Resolve local wallet coldkey from coldkeypub.txt."""
    import json as _json

    wallet_dir = _wallet_dir()
    if not wallet_dir:
        return None
    path = wallet_dir / "coldkeypub.txt"
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
