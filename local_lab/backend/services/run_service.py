"""Demo miner run orchestration."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_DIR = PROJECT_ROOT / "local_lab"
RUNS_DIR = LAB_DIR / ".runs"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class RunRecord:
    id: str
    template: str
    status: RunStatus
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    log_path: Optional[str] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    message: str = ""
    demo_complete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "template": self.template,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_path": self.log_path,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "message": self.message,
            "demo_complete": self.demo_complete,
        }


class RunManager:
    def __init__(self) -> None:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._runs: Dict[str, RunRecord] = {}
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._watch_tasks: Dict[str, asyncio.Task] = {}

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        items = sorted(
            self._runs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return [r.to_dict() for r in items[:limit]]

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        return self._runs.get(run_id)

    async def start_demo(self, template: str = "gatk") -> RunRecord:
        active = [
            r for r in self._runs.values()
            if r.status == RunStatus.RUNNING
        ]
        if active:
            raise RuntimeError(
                f"Run {active[0].id} is already in progress. Stop it first."
            )

        template = template.lower().strip()
        if template not in ("gatk", "deepvariant", "bcftools"):
            raise ValueError(f"Invalid template: {template}")

        run_id = uuid.uuid4().hex[:12]
        log_path = RUNS_DIR / f"{run_id}.log"
        now = datetime.now(timezone.utc).isoformat()

        record = RunRecord(
            id=run_id,
            template=template,
            status=RunStatus.PENDING,
            created_at=now,
            log_path=str(log_path),
        )
        self._runs[run_id] = record

        python_bin = PROJECT_ROOT / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        env = os.environ.copy()
        env["MINER_TEMPLATE"] = template
        env["MINER_DEMO"] = "true"
        env.setdefault("PLATFORM_URL", "https://api.theminos.ai")

        cmd = [
            str(python_bin),
            "-m",
            "neurons.miner",
            "--demo",
        ]

        log_path.write_text("", encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        record.status = RunStatus.RUNNING
        record.started_at = datetime.now(timezone.utc).isoformat()
        record.pid = proc.pid
        self._processes[run_id] = proc
        self._watch_tasks[run_id] = asyncio.create_task(
            self._watch_process(run_id, proc, log_path)
        )
        return record

    async def stop_run(self, run_id: str) -> RunRecord:
        record = self._runs.get(run_id)
        if not record:
            raise KeyError(run_id)

        proc = self._processes.get(run_id)
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            record.status = RunStatus.STOPPED
            record.message = "Stopped by user"
            record.finished_at = datetime.now(timezone.utc).isoformat()

        return record

    async def _watch_process(
        self,
        run_id: str,
        proc: asyncio.subprocess.Process,
        log_path: Path,
    ) -> None:
        record = self._runs[run_id]
        assert proc.stdout is not None

        with log_path.open("a", encoding="utf-8") as log_file:
            while True:
                chunk = await proc.stdout.readline()
                if not chunk:
                    break
                line = chunk.decode("utf-8", errors="replace")
                log_file.write(line)
                log_file.flush()
                if "DEMO COMPLETE" in line:
                    record.demo_complete = True
                if "Total rounds participated: 1" in line:
                    record.demo_complete = True

        exit_code = await proc.wait()
        record.exit_code = exit_code
        record.finished_at = datetime.now(timezone.utc).isoformat()

        if record.status == RunStatus.STOPPED:
            return

        if exit_code == 0 or record.demo_complete:
            record.status = RunStatus.COMPLETED
            record.message = "Demo round finished"
        else:
            record.status = RunStatus.FAILED
            record.message = f"Process exited with code {exit_code}"

        self._processes.pop(run_id, None)

    async def stream_logs(
        self,
        run_id: str,
        from_line: int = 0,
    ) -> AsyncIterator[str]:
        record = self._runs.get(run_id)
        if not record or not record.log_path:
            yield "data: [error] run not found\n\n"
            return

        log_path = Path(record.log_path)
        sent = 0
        idle_ticks = 0
        max_idle = 600  # ~10 min at 1s interval

        while True:
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) > sent:
                    for line in lines[sent:]:
                        escaped = line.replace("\n", " ")
                        yield f"data: {escaped}\n\n"
                    sent = len(lines)
                    idle_ticks = 0

            current = self._runs.get(run_id)
            if not current:
                break

            if current.status in (
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.STOPPED,
            ):
                yield "event: done\ndata: finished\n\n"
                break

            idle_ticks += 1
            if idle_ticks > max_idle:
                yield "event: done\ndata: timeout\n\n"
                break

            await asyncio.sleep(1)


run_manager = RunManager()
