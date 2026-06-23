# Minos Local Lab

Local **backend + frontend** for testing and building your Minos SN107 miner before going live on [theminos.ai](https://theminos.ai/).

## What it does

| Tab | Purpose |
|-----|---------|
| **Overview** | Environment health (Docker, reference data, platform API) |
| **Tool Config** | Edit `configs/gatk.conf` (or deepvariant / bcftools) in the browser |
| **Demo Run** | Runs `python -m neurons.miner --demo` with live log streaming |
| **Results** | Shows variant counts and preview from latest `output.vcf.gz` |
| **Leaderboard** | Round history, rankings, win counts, miner analytics (from platform API) |

Demo mode uses the platform sandbox (`/v2/demo/*`) — **no wallet, no TAO, no registration**.

## Prerequisites

Same as the main miner:

```bash
bash install.sh          # venv, Docker images, reference data
bash scripts/verify.sh --miner
```

Also need **Node.js 18+** and **npm** for the UI.

## Quick start

```bash
bash local_lab/start-lab.sh
```

Open **http://127.0.0.1:5173**

## Architecture

```text
Browser (React UI)
      ↓ /api/*
FastAPI backend (port 8765)
      ├─ neurons.status     → health checks
      ├─ utils.config_loader → config parse/validate
      └─ subprocess         → neurons.miner --demo
```

## Production-style (single port)

Build the frontend and let FastAPI serve it:

```bash
cd local_lab/frontend && npm install && npm run build
cd ../..
PYTHONPATH=. .venv/bin/python -m uvicorn local_lab.backend.main:app --host 0.0.0.0 --port 8765
```

Open **http://127.0.0.1:8765**

## CLI alternative

No UI needed:

```bash
bash scripts/demo.sh --template gatk
```

## Go live after local tests pass

1. Copy `.env.miner.example` → `.env`
2. Set `WALLET_NAME`, `WALLET_HOTKEY`, `MINER_TEMPLATE`
3. Register: `btcli subnets register --netuid 107 ...`
4. Run: `bash start-miner.sh`

Official dashboard: https://theminos.ai/dashboard/leaderboard

## Leaderboard & analytics

The **Leaderboard** tab pulls live data from the public Minos platform API:

- `GET /scoring/rounds` — round history (latest finalized, live, scoring)
- `GET /scoring/rounds/{round_id}/leaderboard` — full ranking per round

Features:

- **Latest finalized / Live round / Round history** — same modes as the official dashboard
- **Analytics** — #1 win counts per hotkey across cached rounds, win rate, podium count, avg score
- **Miner lookup** — full rank history for any hotkey; highlights your `.env` wallet hotkey
- **Sync** — prefetch finalized round data into `local_lab/.cache/leaderboard/`

API routes (local lab backend):

| Route | Purpose |
|-------|---------|
| `GET /api/leaderboard/rounds` | Round history list |
| `GET /api/leaderboard?mode=latest\|live` | Leaderboard for a round |
| `GET /api/leaderboard/analytics?sync=true` | Win counts & performance stats |
| `GET /api/leaderboard/miner/{hotkey}` | Per-miner history |
| `POST /api/leaderboard/sync` | Refresh cache from platform |
