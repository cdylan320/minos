import { useCallback, useEffect, useRef, useState } from "react";
import { api, type TunePipelineResult, type TuneRecommendation } from "../api/client";
import { Button } from "./UI";

type Props = {
  template: string;
  onConfigApplied?: () => void;
  onRunDemo?: () => void;
};

const LEVEL_CLASS: Record<string, string> = {
  info: "tune-log--info",
  warn: "tune-log--warn",
  success: "tune-log--success",
  decision: "tune-log--decision",
  error: "tune-log--error",
};

function severityClass(sev: string) {
  if (sev === "critical") return "tune-gap--critical";
  if (sev === "moderate") return "tune-gap--moderate";
  if (sev === "minor") return "tune-gap--minor";
  return "tune-gap--ok";
}

function formatRoundId(roundId: string) {
  const dt = new Date(roundId);
  if (Number.isNaN(dt.getTime())) return roundId.slice(5, 16);
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  const hh = String(dt.getHours()).padStart(2, "0");
  const mi = String(dt.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${mi}`;
}

export function TunePanel({ template, onConfigApplied, onRunDemo }: Props) {
  const [report, setReport] = useState<TunePipelineResult | null>(null);
  const [recs, setRecs] = useState<TuneRecommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [sync, setSync] = useState(true);
  const [rounds, setRounds] = useState(30);
  const [msg, setMsg] = useState("");
  const [showLogs, setShowLogs] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setMsg("");
    try {
      const data = await api.tuneAnalyze(template, rounds, sync);
      setReport(data);
      setRecs(data.recommendations.map((r) => ({ ...r })));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [template, rounds, sync]);

  useEffect(() => {
    runAnalysis();
  }, [template]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (showLogs) logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [report?.logs, showLogs]);

  const toggleRec = (id: string) => {
    setRecs((prev) => prev.map((r) => (r.id === id ? { ...r, selected: !r.selected } : r)));
  };

  const applySelected = async () => {
    setApplying(true);
    setMsg("");
    try {
      const selected = recs.filter((r) => r.selected);
      const res = await api.tuneApply(template, selected);
      setMsg(res.message);
      onConfigApplied?.();
      await runAnalysis();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const selectedRecs = recs.filter((r) => r.selected);
  const proposedPreview = report
    ? buildPreview(report.current_config.content, selectedRecs)
    : "";

  const latest = report?.diagnosis.latest_round;
  const avg = report?.diagnosis.average;
  const displayGaps = latest?.gaps ?? report?.diagnosis.gaps;

  return (
    <div className="tune-panel">
      <div className="card tune-toolbar-card">
        <div className="tune-toolbar">
          <div className="tune-toolbar__left">
            <label className="tune-field">
              Rounds
              <input
                type="number"
                min={5}
                max={100}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
              />
            </label>
            <label className="tune-check" title="Fetch fresh leaderboard JSON from platform before analyzing">
              <input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} />
              Sync round cache first
            </label>
          </div>
          <Button variant="primary" onClick={runAnalysis} disabled={loading}>
            {loading ? "Analyzing…" : "Run tune pipeline"}
          </Button>
        </div>
        <p className="tune-toolbar-note">
          <strong>Run tune pipeline</strong> analyzes only — it does not change your config.
          Use <strong>Apply changes</strong> below to write <code>configs/{template}.conf</code>.
        </p>
      </div>

      {msg && <div className="toast toast--info">{msg}</div>}

      {report && (
        <>
          <div className="page-grid page-grid--tune-stats">
            <div className="card tune-card">
              <div className="card__header"><h2>Your diagnosis</h2></div>
              <div className="card__body">
              {!report.my_performance?.scored_rounds ? (
                <p className="tune-empty">
                  Set <code>WALLET_NAME</code> / <code>WALLET_HOTKEY</code> in <code>.env</code> and participate in scored rounds.
                </p>
              ) : (
                <div className="tune-diagnosis">
                  <p className="tune-diagnosis__text">{report.diagnosis.interpretation}</p>
                  {latest && (
                    <div className="tune-latest">
                      <h4>Latest scored round — {formatRoundId(latest.round_id ?? "")}</h4>
                      <p className="tune-latest__region"><code>{latest.region}</code></p>
                      <div className="tune-metrics tune-metrics--4">
                        <div>
                          <span>Combined</span>
                          <strong>{(latest.my_combined ?? 0).toFixed(4)}</strong>
                        </div>
                        <div>
                          <span>SNP</span>
                          <strong>{(latest.my_snp ?? 0).toFixed(4)}</strong>
                        </div>
                        <div>
                          <span>INDEL</span>
                          <strong>{(latest.my_indel ?? 0).toFixed(4)}</strong>
                        </div>
                        <div>
                          <span>Round #1</span>
                          <strong><code>{latest.winner_hotkey ?? "—"}</code></strong>
                        </div>
                      </div>
                    </div>
                  )}
                  {avg && (
                    <div className="tune-avg">
                      <h4>{report.rounds_analyzed}-round average</h4>
                      <div className="tune-metrics">
                        <div>
                          <span>Combined</span>
                          <strong>{(avg.my_combined ?? 0).toFixed(4)}</strong>
                        </div>
                        <div>
                          <span>SNP</span>
                          <strong>{(avg.my_snp ?? 0).toFixed(4)}</strong>
                        </div>
                        <div>
                          <span>INDEL</span>
                          <strong>{(avg.my_indel ?? 0).toFixed(4)}</strong>
                        </div>
                      </div>
                    </div>
                  )}
                  {displayGaps && (
                    <div className="tune-gaps">
                      {(["combined", "snp", "indel"] as const).map((k) => (
                        <div key={k} className={`tune-gap ${severityClass(displayGaps[k].severity)}`}>
                          <span>{k.toUpperCase()} gap</span>
                          <strong>{displayGaps[k].value.toFixed(4)}</strong>
                          <em>{displayGaps[k].severity}</em>
                        </div>
                      ))}
                    </div>
                  )}
                  {report.diagnosis.score_note && (
                    <p className="tune-score-note">{report.diagnosis.score_note}</p>
                  )}
                </div>
              )}
              </div>
            </div>

            <div className="card tune-card">
              <div className="card__header"><h2>Recent regions</h2></div>
              <div className="card__body">
              <div className="table-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr><th>Round</th><th>Chrom</th><th>Region</th></tr>
                  </thead>
                  <tbody>
                    {report.region_analysis.recent_rounds.slice(0, 8).map((r) => (
                      <tr key={r.round_id}>
                        <td>{formatRoundId(r.round_id)}</td>
                        <td><code>{r.chrom}</code></td>
                        <td><code>{r.region}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </div>
            </div>

            <div className="card tune-card tune-card--wide">
              <div className="card__header">
                <h2>Top miner profile</h2>
                <span className="card__meta">{report.rounds_analyzed} rounds</span>
              </div>
              <div className="card__body">
              <div className="tune-metrics">
                <div>
                  <span>Median combined</span>
                  <strong>{(report.top_miner_analysis.summary.median_combined ?? 0).toFixed(4)}</strong>
                </div>
                <div>
                  <span>Median SNP</span>
                  <strong>{(report.top_miner_analysis.summary.median_snp ?? 0).toFixed(4)}</strong>
                </div>
                <div>
                  <span>Median INDEL</span>
                  <strong>{(report.top_miner_analysis.summary.median_indel ?? 0).toFixed(4)}</strong>
                </div>
              </div>
              <p className="tune-tool-wins">
                Round wins by tool:{" "}
                {Object.entries(report.top_miner_analysis.tool_win_counts)
                  .map(([t, n]) => `${t} (${n})`)
                  .join(", ") || "—"}
              </p>
              <div className="table-wrap tune-winners-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr>
                      <th>Round</th><th>Hotkey</th><th>Coldkey</th><th>UID</th>
                      <th>Combined</th><th>SNP</th><th>INDEL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.top_miner_analysis.recent_winners.slice(0, 8).map((w) => (
                      <tr key={w.round_id}>
                        <td>{formatRoundId(w.round_id)}</td>
                        <td><code>{w.short_hotkey}</code></td>
                        <td><code>{w.short_coldkey ?? "—"}</code></td>
                        <td>{w.uid ?? "—"}</td>
                        <td className="lb-score">{w.combined_final?.toFixed(4) ?? "—"}</td>
                        <td>{w.snp_final?.toFixed(4) ?? "—"}</td>
                        <td>{w.indel_final?.toFixed(4) ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </div>
            </div>
          </div>

          {report.my_performance && report.my_performance.history.length > 0 && (
            <div className="card tune-card">
              <div className="card__header">
                <h2>Your round history (per-round scores)</h2>
                <span className="card__meta">{report.my_performance.short_hotkey}</span>
              </div>
              <div className="card__body">
              <div className="table-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr>
                      <th>Round</th><th>Region</th><th>Rank</th>
                      <th>Combined</th><th>SNP</th><th>INDEL</th><th>Tool</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.my_performance.history.map((h) => (
                      <tr key={h.round_id}>
                        <td>{formatRoundId(h.round_id)}</td>
                        <td><code>{h.region}</code></td>
                        <td>{h.rank ?? "—"}</td>
                        <td className="lb-score">{h.combined_final?.toFixed(4) ?? "—"}</td>
                        <td>{h.snp_final?.toFixed(4) ?? "—"}</td>
                        <td>{h.indel_final?.toFixed(4) ?? "—"}</td>
                        <td>{h.tool_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </div>
            </div>
          )}

          <div className="card tune-card">
            <div className="card__header">
              <h2>Recommendations</h2>
              <span className="card__meta">{selectedRecs.length} selected</span>
            </div>
            <div className="card__body">
            {recs.length === 0 ? (
              <p className="tune-empty">No changes suggested — your config matches current heuristics.</p>
            ) : (
              <div className="tune-recs">
                {recs.map((r) => (
                  <label key={r.id} className={`tune-rec ${r.selected ? "tune-rec--on" : ""}`}>
                    <input type="checkbox" checked={!!r.selected} onChange={() => toggleRec(r.id)} />
                    <div>
                      <div className="tune-rec__head">
                        <code>{r.param}</code>
                        <span>{String(r.current_value)} → <strong>{String(r.proposed_value)}</strong></span>
                        <span className="tune-rec__src">{r.source}</span>
                      </div>
                      <p>{r.reason}</p>
                    </div>
                  </label>
                ))}
              </div>
            )}
            <div className="tune-actions">
              <Button variant="primary" disabled={!selectedRecs.length || applying} onClick={applySelected}>
                {applying ? "Applying…" : `Apply ${selectedRecs.length} change(s) to configs/${template}.conf`}
              </Button>
              {onRunDemo && (
                <Button variant="secondary" onClick={onRunDemo}>
                  Run demo to validate
                </Button>
              )}
            </div>
            </div>
          </div>

          {selectedRecs.length > 0 && (
            <div className="card tune-card">
              <div className="card__header"><h2>Proposed config preview</h2></div>
              <div className="card__body">
              <pre className="tune-preview">{proposedPreview}</pre>
              </div>
            </div>
          )}

          <div className="card tune-card">
            <div className="card__header">
              <h2>Pipeline log</h2>
              <button type="button" className="lb-tab" onClick={() => setShowLogs((v) => !v)}>
                {showLogs ? "Hide" : "Show"}
              </button>
            </div>
            {showLogs && (
              <div className="card__body card__body--flush">
              <div className="tune-logs">
                {report.logs.map((entry, i) => (
                  <div key={i} className={`tune-log ${LEVEL_CLASS[entry.level] ?? ""}`}>
                    <span className="tune-log__phase">{entry.phase}</span>
                    <span className="tune-log__msg">{entry.message}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
              </div>
            )}
          </div>
        </>
      )}

      {loading && !report && <div className="empty-state">Running tune pipeline…</div>}
    </div>
  );
}

function buildPreview(content: string, recs: TuneRecommendation[]) {
  const lines = content.split("\n");
  const map = new Map<string, number>();
  lines.forEach((line, i) => {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) return;
    map.set(t.split("=")[0].trim(), i);
  });
  const out = [...lines];
  for (const r of recs) {
    const line = `${r.param}=${r.proposed_value}`;
    if (map.has(r.param)) out[map.get(r.param)!] = line;
    else out.push(line);
  }
  return out.join("\n");
}
