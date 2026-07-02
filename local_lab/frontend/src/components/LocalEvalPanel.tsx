import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  streamEvalLogs,
  type EvalHistoryEntry,
  type EvalPrerequisites,
  type EvalRunRecord,
  type EvalScoreResult,
  type EvalTask,
} from "../api/client";
import { Button, StatCard } from "./UI";

type Props = {
  template: string;
};

const SOURCE_LABEL: Record<string, string> = {
  builtin: "Built-in",
  scoring_cache: "Validator cache",
  platform: "Platform",
  platform_demo: "Platform demo",
  import: "Imported",
  demo_output: "Demo output",
  miner_download: "Miner BAM",
};

function scoreClass(v: number) {
  if (v >= 0.85) return "eval-score--excellent";
  if (v >= 0.7) return "eval-score--good";
  if (v >= 0.5) return "eval-score--fair";
  return "eval-score--poor";
}

function fmt4(v?: number) {
  return v != null && Number.isFinite(v) ? v.toFixed(4) : "—";
}

export function LocalEvalPanel({ template }: Props) {
  const [tasks, setTasks] = useState<EvalTask[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [prereq, setPrereq] = useState<EvalPrerequisites | null>(null);
  const [mode, setMode] = useState<"full" | "score_only">("score_only");
  const [history, setHistory] = useState<EvalHistoryEntry[]>([]);
  const [latest, setLatest] = useState<EvalScoreResult | null>(null);
  const [activeRun, setActiveRun] = useState<EvalRunRecord | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [platformRoundId, setPlatformRoundId] = useState("");
  const [importPath, setImportPath] = useState("");
  const [truthPath, setTruthPath] = useState("");
  const [mutationsPath, setMutationsPath] = useState("");
  const logRef = useRef<HTMLPreElement>(null);

  const selected = useMemo(
    () => tasks.find((t) => t.id === selectedId) ?? null,
    [tasks, selectedId],
  );

  const refreshTasks = useCallback(async () => {
    const data = await api.evalTasks(true);
    setTasks(data.tasks);
    if (!selectedId && data.tasks.length) {
      const ready = data.tasks.find((t) => t.ready) ?? data.tasks[0];
      setSelectedId(ready.id);
    }
  }, [selectedId]);

  const refreshHistory = useCallback(async () => {
    const [h, lat] = await Promise.all([api.evalHistory(20), api.evalLatest()]);
    setHistory(h.entries);
    if (lat.found && lat.combined_final != null) {
      setLatest(lat as EvalScoreResult);
    }
  }, []);

  useEffect(() => {
    refreshTasks().catch((e) => setMsg(String(e)));
    refreshHistory().catch(() => undefined);
  }, [refreshTasks, refreshHistory]);

  useEffect(() => {
    if (!selectedId) return;
    api.evalPrerequisites(selectedId).then(setPrereq).catch(() => setPrereq(null));
  }, [selectedId, tasks]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [logs]);

  const scoreDelta = useMemo(() => {
    if (history.length < 2 || !history[0]?.combined_final) return null;
    return history[0].combined_final - history[1].combined_final;
  }, [history]);

  const runEval = async () => {
    if (!selectedId) return;
    setLoading(true);
    setLogs([]);
    setMsg("");
    try {
      const run = await api.evalRun({ task_id: selectedId, template, mode });
      setActiveRun(run);
      streamEvalLogs(
        run.id,
        (line) => setLogs((prev) => [...prev, line]),
        async () => {
          setLoading(false);
          const runs = await api.evalRuns();
          const current = runs.runs.find((r) => r.id === run.id);
          if (current?.result) setLatest(current.result);
          if (current) setActiveRun(current);
          await refreshHistory();
          await refreshTasks();
        },
      );
    } catch (e) {
      setLoading(false);
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const handleScanCache = async () => {
    setLoading(true);
    setMsg("");
    try {
      const res = await api.evalScanCache();
      setTasks(res.tasks.tasks);
      const parts = [];
      if (res.miner_downloads) parts.push(`${res.miner_downloads} miner BAM(s)`);
      if (res.scoring_cache) parts.push(`${res.scoring_cache} validator cache`);
      setMsg(parts.length ? `Found: ${parts.join(", ")}` : "No cached tasks found — try Fetch demo task");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleFetchDemo = async () => {
    setLoading(true);
    setMsg("");
    setLogs([]);
    try {
      const res = await api.evalFetchDemo();
      setTasks((await api.evalTasks(true)).tasks);
      setSelectedId(res.task.id);
      setLogs(res.log);
      setMsg(res.message);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateTruth = async () => {
    if (!selectedId) return;
    setLoading(true);
    setMsg("");
    setLogs([]);
    try {
      const res = await api.evalGenerateTruth(selectedId);
      setLogs(res.log);
      setMsg(res.message);
      setTasks((await api.evalTasks(true)).tasks);
      if (selectedId) setPrereq(await api.evalPrerequisites(selectedId));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadSdf = async () => {
    setLoading(true);
    setMsg("");
    try {
      const res = await api.evalDownloadSdf("chr20");
      setMsg(res.message ?? `Downloaded chr20 SDF (${res.downloaded.length} files)`);
      if (selectedId) {
        setPrereq(await api.evalPrerequisites(selectedId));
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleAttachTruth = async () => {
    if (!selectedId || !truthPath.trim() || !mutationsPath.trim()) return;
    setLoading(true);
    setMsg("");
    try {
      const res = await api.evalAttachTruth(selectedId, truthPath.trim(), mutationsPath.trim());
      setSelectedId(res.task.id);
      await refreshTasks();
      setMsg("Ground truth attached — task should be ready to score");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleFetchPlatform = async () => {
    if (!platformRoundId.trim()) return;
    setLoading(true);
    setMsg("");
    try {
      const res = await api.evalFetchPlatform(platformRoundId.trim());
      setSelectedId(res.task.id);
      await refreshTasks();
      setMsg("Platform task downloaded");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    if (!importPath.trim()) return;
    setLoading(true);
    setMsg("");
    try {
      const res = await api.evalImport(importPath.trim());
      setSelectedId(res.task.id);
      await refreshTasks();
      setMsg("Task imported");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const metrics = latest?.metrics;
  const components = latest?.components as Record<string, Record<string, number>> | undefined;

  return (
    <div className="eval-layout">
      <div className="card eval-intro">
        <div className="eval-intro__text">
          <h2 className="card__title">Local Eval</h2>
          <p className="card__subtitle">
            Score your config with the <strong>same hap.py + AdvancedScorer pipeline</strong> as validators.
            No on-chain validator needed — click <strong>Fetch demo task</strong> to auto-generate truth from
            <strong> GIAB (open-source) + oracle BAM call</strong> (same idea as platform: baseline + synthetic distance).
          </p>
        </div>
        <div className="eval-intro__actions">
          <Button variant="primary" onClick={handleFetchDemo} disabled={loading}>
            Fetch demo task (no wallet)
          </Button>
          <Button variant="secondary" onClick={handleScanCache} disabled={loading}>
            Scan miner downloads
          </Button>
          <Button variant="secondary" onClick={() => refreshTasks()} disabled={loading}>
            Refresh
          </Button>
        </div>
      </div>

      {msg && <div className="toast toast--info" role="status">{msg}</div>}

      <div className="page-grid--eval">
        <div className="eval-main">
          {latest && (
            <div className="card eval-hero">
              <div className="eval-hero__scores">
                <div className={`eval-hero__primary ${scoreClass(latest.combined_final ?? 0)}`}>
                  <span className="eval-hero__label">Combined</span>
                  <span className="eval-hero__value">{fmt4(latest.combined_final)}</span>
                  {scoreDelta != null && (
                    <span className={`eval-hero__delta ${scoreDelta >= 0 ? "eval-hero__delta--up" : "eval-hero__delta--down"}`}>
                      {scoreDelta >= 0 ? "+" : ""}{scoreDelta.toFixed(4)} vs prior
                    </span>
                  )}
                </div>
                <StatCard label="SNP F1" value={fmt4(latest.snp_final)} />
                <StatCard label="INDEL F1" value={fmt4(latest.indel_final)} />
                <StatCard label="Advanced" value={`${latest.advanced_score?.toFixed(1) ?? "—"}/100`} />
              </div>
              {latest.region && (
                <p className="eval-hero__region">Region: <code>{latest.region}</code></p>
              )}
            </div>
          )}

          <div className="card">
            <div className="card__header">
              <h3 className="card__title">Eval tasks</h3>
              <span className="eval-badge">
                {tasks.filter((t) => t.ready).length}/{tasks.length} ready
              </span>
            </div>
            <div className="eval-task-grid">
              {tasks.length === 0 && (
                <div className="empty-state">
                  <p>No eval tasks yet.</p>
                  <p className="text-muted">Scan validator cache, import a scoring directory, or fetch from platform.</p>
                </div>
              )}
              {tasks.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`eval-task-card ${selectedId === t.id ? "eval-task-card--selected" : ""} ${t.ready ? "eval-task-card--ready" : ""}`}
                  onClick={() => setSelectedId(t.id)}
                >
                  <div className="eval-task-card__head">
                    <span className="eval-task-card__name">{t.name}</span>
                    <span className={`eval-task-card__status ${t.ready ? "eval-task-card__status--ready" : t.bam_only ? "eval-task-card__status--bam" : ""}`}>
                      {t.ready ? "Ready" : t.bam_only ? "BAM only" : "Needs data"}
                    </span>
                  </div>
                  <p className="eval-task-card__desc">{t.description}</p>
                  <div className="eval-task-card__meta">
                    <span className="eval-source-pill">{SOURCE_LABEL[t.source] ?? t.source}</span>
                    {t.region && <code className="eval-task-card__region">{t.region}</code>}
                    {t.num_mutations != null && <span>{t.num_mutations} mutations</span>}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card__header">
              <h3 className="card__title">Run eval</h3>
            </div>
            <div className="eval-run-controls">
              <div className="eval-mode-toggle">
                <button
                  type="button"
                  className={`eval-mode-btn ${mode === "score_only" ? "eval-mode-btn--active" : ""}`}
                  onClick={() => setMode("score_only")}
                >
                  Score only
                  <span className="eval-mode-btn__hint">Use latest demo VCF</span>
                </button>
                <button
                  type="button"
                  className={`eval-mode-btn ${mode === "full" ? "eval-mode-btn--active" : ""}`}
                  onClick={() => setMode("full")}
                >
                  Full pipeline
                  <span className="eval-mode-btn__hint">Call variants + score</span>
                </button>
              </div>
              <Button variant="primary" disabled={loading || !selectedId || !prereq?.ok} onClick={runEval}>
                {loading ? "Running eval…" : "Run local eval"}
              </Button>
            </div>
            {!prereq?.ok && selected && (
              <div className="eval-prereq-warn">
                {selected.bam_only ? (
                  <>
                    BAM ready — click <button type="button" className="link-btn" onClick={handleGenerateTruth}>Generate local truth</button>
                    {" "}or re-fetch demo task (auto-generates truth).
                  </>
                ) : (
                  "Complete prerequisites below before running."
                )}
              </div>
            )}
          </div>

          {(loading || logs.length > 0) && (
            <div className="card eval-log-card">
              <div className="card__header">
                <h3 className="card__title">Eval log</h3>
                {activeRun && <span className="eval-run-status">{activeRun.status}</span>}
              </div>
              <pre ref={logRef} className="log-viewer">{logs.join("\n") || "Waiting for output…"}</pre>
            </div>
          )}

          {metrics && (
            <div className="card">
              <div className="card__header">
                <h3 className="card__title">Metric breakdown</h3>
              </div>
              <table className="data-table eval-metrics-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Precision</th>
                    <th>Recall</th>
                    <th>F1</th>
                    <th>FP</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><span className="type-pill type-pill--snp">SNP</span></td>
                    <td>{fmt4(metrics.precision_snp)}</td>
                    <td>{fmt4(metrics.recall_snp)}</td>
                    <td className="lb-score">{fmt4(metrics.f1_snp)}</td>
                    <td>{metrics.fp_snp ?? "—"}</td>
                  </tr>
                  <tr>
                    <td><span className="type-pill type-pill--indel">INDEL</span></td>
                    <td>{fmt4(metrics.precision_indel)}</td>
                    <td>{fmt4(metrics.recall_indel)}</td>
                    <td className="lb-score">{fmt4(metrics.f1_indel)}</td>
                    <td>{metrics.fp_indel ?? "—"}</td>
                  </tr>
                </tbody>
              </table>
              {components && (
                <div className="eval-components">
                  <h4>AdvancedScorer components</h4>
                  <div className="eval-component-bars">
                    {[
                      { key: "core_f1", label: "Core F1", weight: 0.6 },
                      { key: "completeness", label: "Completeness", weight: 0.15 },
                      { key: "fp_rate", label: "FP rate", weight: 0.15 },
                      { key: "quality", label: "Quality", weight: 0.1 },
                    ].map(({ key, label, weight }) => (
                      <div key={key} className="eval-component-row">
                        <span className="eval-component-label">{label} ({Math.round(weight * 100)}%)</span>
                        <div className="eval-component-bar">
                          <div
                            className="eval-component-fill"
                            style={{ width: `${Math.min(100, (latest?.advanced_score ?? 0) * weight / 0.6)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  {(Number(components.overcall_penalty) || 0) > 0 && (
                    <p className="eval-overcall">Overcall penalty: −{Number(components.overcall_penalty).toFixed(1)} pts</p>
                  )}
                </div>
              )}
            </div>
          )}

          {history.length > 0 && (
            <div className="card">
              <div className="card__header">
                <h3 className="card__title">Score history</h3>
                <span className="text-muted">Track config improvements over time</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Task</th>
                    <th>Mode</th>
                    <th>Combined</th>
                    <th>SNP</th>
                    <th>INDEL</th>
                    <th>Config</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id}>
                      <td>{new Date(h.timestamp).toLocaleString()}</td>
                      <td>{h.task_name ?? h.task_id}</td>
                      <td>{h.mode}</td>
                      <td className={`lb-score ${scoreClass(h.combined_final)}`}>{fmt4(h.combined_final)}</td>
                      <td>{fmt4(h.snp_final)}</td>
                      <td>{fmt4(h.indel_final)}</td>
                      <td><code>{h.config_fingerprint?.slice(0, 8) ?? "—"}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <aside className="eval-sidebar">
          <div className="card">
            <h3 className="card__title">Prerequisites</h3>
            {prereq ? (
              <ul className="eval-check-list">
                {prereq.checks.map((c) => (
                  <li key={c.name} className={`eval-check eval-check--${c.status}`}>
                    <span className="eval-check__name">{c.name}</span>
                    <span className="eval-check__detail">{c.detail}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted">Select a task</p>
            )}
          </div>

          <div className="card">
            <h3 className="card__title">Get eval data</h3>
            <div className="eval-import-block eval-import-block--highlight">
              <p className="field-hint">
                <strong>One click:</strong> Fetch demo task downloads BAM + auto-generates truth/mutations
                (GIAB benchmark + oracle call on BAM). Takes ~5–15 min first time (GIAB download cached).
              </p>
              <div className="btn-group" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
                <Button variant="secondary" disabled={loading || !selectedId} onClick={handleGenerateTruth}>
                  Generate local truth
                </Button>
                <Button variant="secondary" disabled={loading} onClick={handleDownloadSdf}>
                  Download chr20 SDF
                </Button>
              </div>
            </div>
            {selected?.bam_only && (
              <div className="eval-import-block">
                <label className="field-label">Or attach official truth manually</label>
                <input className="field-input" placeholder="/path/to/truth.vcf.gz" value={truthPath} onChange={(e) => setTruthPath(e.target.value)} />
                <input className="field-input" placeholder="/path/to/mutations.vcf.gz" value={mutationsPath} onChange={(e) => setMutationsPath(e.target.value)} />
                <Button variant="secondary" disabled={loading} onClick={handleAttachTruth}>
                  Attach truth files
                </Button>
                <p className="field-hint">
                  Truth/mutations are not sent to miners — get them from a validator scoring dir
                  (<code>output/scoring/round_*/</code>) or import a full task directory below.
                </p>
              </div>
            )}
            <div className="eval-import-block">
              <label className="field-label">Platform round (validator wallet)</label>
              <input
                className="field-input"
                placeholder="2026-06-29T22:40:00+00:00"
                value={platformRoundId}
                onChange={(e) => setPlatformRoundId(e.target.value)}
              />
              <Button variant="secondary" disabled={loading} onClick={handleFetchPlatform}>
                Fetch round task
              </Button>
              <p className="field-hint">Requires WALLET_NAME/HOTKEY authorized as validator during scoring window.</p>
            </div>
            <div className="eval-import-block">
              <label className="field-label">Import scoring directory</label>
              <input
                className="field-input"
                placeholder="/path/to/output/scoring/round_..."
                value={importPath}
                onChange={(e) => setImportPath(e.target.value)}
              />
              <Button variant="secondary" disabled={loading} onClick={handleImport}>
                Import
              </Button>
              <p className="field-hint">Must contain round.bam, truth.vcf.gz, mutations.vcf.gz, and task_meta.json with region.</p>
            </div>
          </div>

          <div className="card eval-help">
            <h3 className="card__title">How it works</h3>
            <ol className="eval-help-list">
              <li><strong>Fetch demo task</strong> — BAM from platform + auto truth generation (no wallet).</li>
              <li><strong>Generate local truth</strong> — GIAB open-source baseline + oracle BAM call → synthetic mutations.</li>
              <li><strong>Scan miner downloads</strong> — uses your <code>input.bam</code>, then generate truth.</li>
              <li><strong>Download chr20 SDF</strong> — required for hap.py (one-time).</li>
              <li>Run eval — scores use same hap.py + AdvancedScorer as mainnet.</li>
            </ol>
            <p className="field-hint">
              Local scores are for <strong>relative config tuning</strong> (A vs B on same task).
              Mainnet scores differ unless Minos publishes the official truth bundle.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
