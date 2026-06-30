import { useCallback, useEffect, useRef, useState } from "react";
import { api, type TunePipelineResult, type TuneRecommendation, type ConfigChangeRecord } from "../api/client";
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
  const [selectedUpdatesForModal, setSelectedUpdatesForModal] = useState<ConfigChangeRecord[] | null>(null);
  const [llmStatus, setLlmStatus] = useState<{ configured: boolean; enabled: boolean; model: string } | null>(null);
  const [llmJudging, setLlmJudging] = useState(false);

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
    api.tuneLlmStatus().then(setLlmStatus).catch(() => setLlmStatus(null));
  }, []);

  const runLlmJudge = useCallback(async () => {
    if (!report) return;
    setLlmJudging(true);
    setMsg("");
    try {
      const ruleRecs = report.rule_recommendations ?? report.recommendations;
      const result = await api.tuneLlmJudge({
        template,
        current_config: report.current_config,
        diagnosis: report.diagnosis,
        rule_recommendations: ruleRecs,
        top_miner_summary: report.top_miner_analysis.summary,
        my_performance: report.my_performance,
        last_update_analysis: report.last_update_analysis,
        region_analysis: report.region_analysis,
        logs: report.logs,
      });
      setReport((prev) =>
        prev
          ? {
              ...prev,
              recommendations: result.recommendations,
              llm_advisory: result.llm_advisory,
              rule_recommendation_count: result.rule_recommendation_count,
              proposed_config: result.proposed_config,
              logs: result.logs,
            }
          : prev,
      );
      setRecs(result.recommendations.map((r) => ({ ...r })));
      setMsg("LLM judge complete — recommendations ranked.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLlmJudging(false);
    }
  }, [report, template]);

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
          <strong>Run tune pipeline</strong> uses rules only (no API cost). Click <strong>LLM judge</strong> below
          to rank recommendations via OpenRouter when you want AI review.
          Use <strong>Apply changes</strong> to write <code>configs/{template}.conf</code>.
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
                  {report.last_update_analysis && (
                    <div className="tune-update-analysis">
                      <h4>🔄 Last Update Analysis</h4>
                      <p className="tune-update-analysis__msg">{report.last_update_analysis.message}</p>
                      <button
                        className="link-btn"
                        style={{ marginTop: "0.5rem", display: "inline-flex", alignItems: "center", gap: "4px" }}
                        onClick={() => setSelectedUpdatesForModal(report.last_update_analysis?.updates || null)}
                      >
                        View last update diff ({report.last_update_analysis.updates.length})
                      </button>
                    </div>
                  )}
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
                      <th>Combined</th><th>SNP</th><th>INDEL</th><th>Tool</th><th>Updates</th>
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
                        <td>
                          {h.updates && h.updates.length > 0 ? (
                            <button
                              type="button"
                              className="link-btn tune-update-btn"
                              onClick={() => setSelectedUpdatesForModal(h.updates || null)}
                              title={`${h.updates.length} configuration update(s) detected before this round`}
                            >
                              🔄 {formatRoundId(h.updates[0].timestamp)}
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </div>
            </div>
          )}

          <div className="card tune-card">
            <div className="card__header tune-recs-header">
              <h2>Recommendations</h2>
              <div className="tune-recs-header__actions">
                <span
                  title={
                    !llmStatus?.configured
                      ? "Set OPENROUTER_API_KEY in .env"
                      : `Rank ${report?.rule_recommendation_count ?? report?.recommendations.length ?? 0} rule candidate(s) via ${llmStatus?.model ?? "OpenRouter"} (API cost applies)`
                  }
                >
                  <Button
                    variant="secondary"
                    onClick={runLlmJudge}
                    disabled={
                      llmJudging ||
                      loading ||
                      !report ||
                      !(report.rule_recommendations?.length || report.recommendations.length) ||
                      !llmStatus?.configured ||
                      !llmStatus?.enabled
                    }
                  >
                    {llmJudging ? "LLM judging…" : "LLM judge"}
                  </Button>
                </span>
                <span className="card__meta">{selectedRecs.length} selected</span>
              </div>
            </div>
            <div className="card__body">
            {report.llm_advisory && (
              <div className={`tune-llm-advisory ${report.llm_advisory.used ? "tune-llm-advisory--on" : ""}`}>
                <div className="tune-llm-advisory__head">
                  <h4>LLM advisory {report.llm_advisory.used ? "(active)" : "(rules only)"}</h4>
                  <span className="tune-llm-advisory__model">{report.llm_advisory.model}</span>
                </div>
                {!report.llm_advisory.configured && (
                  <p className="tune-llm-advisory__msg">
                    Add <code>OPENROUTER_API_KEY</code> to <code>.env</code> to enable LLM ranking after the rule engine.
                    Default model: <code>{report.llm_advisory.model}</code>.
                  </p>
                )}
                {report.llm_advisory.configured && !report.llm_advisory.used && report.llm_advisory.notes && (
                  <p className="tune-llm-advisory__msg">{report.llm_advisory.notes}</p>
                )}
                {report.llm_advisory.error && (
                  <p className="tune-llm-advisory__msg tune-llm-advisory__msg--warn">{report.llm_advisory.error}</p>
                )}
                {report.llm_advisory.used && report.llm_advisory.summary && (
                  <p className="tune-llm-advisory__msg">{report.llm_advisory.summary}</p>
                )}
                {report.llm_advisory.used && report.llm_advisory.strategy && (
                  <p className="tune-llm-advisory__strategy">
                    Strategy: <strong>{report.llm_advisory.strategy}</strong>
                    {typeof report.rule_recommendation_count === "number" && (
                      <> · {report.rule_recommendation_count} rule candidate(s) ranked</>
                    )}
                  </p>
                )}
              </div>
            )}
            {recs.length === 0 ? (
              <p className="tune-empty">
                No changes suggested — your config already matches all heuristic targets for the current score gap.
                If your score recently dropped after an update, re-run the pipeline; rollback suggestions appear when the last config change hurt performance.
              </p>
            ) : (
              <div className="tune-recs">
                {recs.map((r) => (
                  <label key={r.id} className={`tune-rec ${r.selected ? "tune-rec--on" : ""}`}>
                    <input type="checkbox" checked={!!r.selected} onChange={() => toggleRec(r.id)} />
                    <div>
                      <div className="tune-rec__head">
                        <code>{r.param}</code>
                        <span>{String(r.current_value)} → <strong>{String(r.proposed_value)}</strong></span>
                        <span className={`tune-rec__src tune-rec__src--${r.source.replace(/_/g, "-")}`}>{r.source}</span>
                        {r.llm_confidence && (
                          <span className="tune-rec__conf">{r.llm_confidence}</span>
                        )}
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

      {selectedUpdatesForModal && (
        <div className="modal-backdrop" onClick={() => setSelectedUpdatesForModal(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Configuration Update Details</h2>
              <button type="button" className="modal-close" onClick={() => setSelectedUpdatesForModal(null)}>&times;</button>
            </div>
            <div className="modal-body">
              {selectedUpdatesForModal.map((update, index) => {
                const diffs = getDiffLines(update.old_content, update.new_content);
                return (
                  <div key={update.id} className="modal-update-record" style={{ marginBottom: index < selectedUpdatesForModal.length - 1 ? "2rem" : 0 }}>
                    <div className="modal-update-meta">
                      <span><strong>Template:</strong> {update.template.toUpperCase()}</span>
                      <span><strong>Date:</strong> {new Date(update.timestamp).toLocaleString()}</span>
                      <span><strong>Source:</strong> <span className={`source-tag source-tag--${update.source}`}>{update.source === "tune_recommendation" ? "Tune Recommendation" : "Manual Edit"}</span></span>
                    </div>

                    <h4 style={{ marginTop: "1rem", marginBottom: "0.5rem" }}>Parameter Changes</h4>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Parameter</th>
                            <th>Type</th>
                            <th>Old Value</th>
                            <th>New Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {diffs.map((d) => (
                            <tr key={d.param}>
                              <td><code>{d.param}</code></td>
                              <td>
                                <span className={`diff-type-tag diff-type-tag--${d.type}`}>
                                  {d.type.toUpperCase()}
                                </span>
                              </td>
                              <td style={{ textDecoration: d.type === "added" ? "none" : "line-through", color: "var(--text-secondary)" }}>
                                {d.oldVal ?? "—"}
                              </td>
                              <td style={{ fontWeight: "bold", color: d.type === "removed" ? "var(--text-muted)" : "var(--accent)" }}>
                                {d.newVal ?? "—"}
                              </td>
                            </tr>
                          ))}
                          {diffs.length === 0 && (
                            <tr>
                              <td colSpan={4} className="text-center" style={{ padding: "1rem" }}>No parameter changes detected (whitespace or comment only edit).</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>

                    <h4 style={{ marginTop: "1.5rem", marginBottom: "0.5rem" }}>Raw Config Diff Preview</h4>
                    <pre className="modal-diff-pre">
                      {computeRawDiff(update.old_content, update.new_content)}
                    </pre>
                  </div>
                );
              })}
            </div>
            <div className="modal-footer">
              <Button variant="secondary" onClick={() => setSelectedUpdatesForModal(null)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function getDiffLines(oldText: string, newText: string) {
  const oldLines = oldText.split("\n").map(l => l.trim());
  const newLines = newText.split("\n").map(l => l.trim());

  const oldParams: Record<string, string> = {};
  oldLines.forEach(l => {
    if (l && !l.startsWith("#") && l.includes("=")) {
      const idx = l.indexOf("=");
      oldParams[l.substring(0, idx).trim()] = l.substring(idx + 1).trim();
    }
  });

  const newParams: Record<string, string> = {};
  newLines.forEach(l => {
    if (l && !l.startsWith("#") && l.includes("=")) {
      const idx = l.indexOf("=");
      newParams[l.substring(0, idx).trim()] = l.substring(idx + 1).trim();
    }
  });

  const diffs: Array<{ type: "added" | "removed" | "modified"; param: string; oldVal?: string; newVal?: string }> = [];

  Object.keys(oldParams).forEach(k => {
    if (!(k in newParams)) {
      diffs.push({ type: "removed", param: k, oldVal: oldParams[k] });
    } else if (oldParams[k] !== newParams[k]) {
      diffs.push({ type: "modified", param: k, oldVal: oldParams[k], newVal: newParams[k] });
    }
  });

  Object.keys(newParams).forEach(k => {
    if (!(k in oldParams)) {
      diffs.push({ type: "added", param: k, newVal: newParams[k] });
    }
  });

  return diffs;
}

function computeRawDiff(oldText: string, newText: string): string {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");

  const diffLines: string[] = [];

  const getLineKey = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) return null;
    return trimmed.split("=")[0].trim();
  };

  const oldKeyMap: Record<string, string> = {};
  oldLines.forEach(l => {
    const k = getLineKey(l);
    if (k) oldKeyMap[k] = l;
  });

  const newKeyMap: Record<string, string> = {};
  newLines.forEach(l => {
    const k = getLineKey(l);
    if (k) newKeyMap[k] = l;
  });

  oldLines.forEach(l => {
    const k = getLineKey(l);
    if (k) {
      if (!(k in newKeyMap)) {
        diffLines.push(`- ${l}`);
      } else if (newKeyMap[k] !== l) {
        diffLines.push(`- ${l}`);
        diffLines.push(`+ ${newKeyMap[k]}`);
      }
    }
  });

  newLines.forEach(l => {
    const k = getLineKey(l);
    if (k && !(k in oldKeyMap)) {
      diffLines.push(`+ ${l}`);
    }
  });

  return diffLines.join("\n") || "No text diff available.";
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
