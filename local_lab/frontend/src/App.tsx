import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api,
  streamLogs,
  type HealthReport,
  type RunRecord,
  type VcfSummary,
} from "./api/client";
import {
  IconConfig,
  IconDna,
  IconExternal,
  IconLeaderboard,
  IconOverview,
  IconPlay,
  IconRefresh,
  IconResults,
  IconTune,
  IconEval,
} from "./components/Icons";
import { LeaderboardPanel } from "./components/LeaderboardPanel";
import { LocalEvalPanel } from "./components/LocalEvalPanel";
import { TunePanel } from "./components/TunePanel";
import {
  Button,
  PipelineStepper,
  ProgressRing,
  StatCard,
  StatusBadge,
  TemplateSelect,
} from "./components/UI";

type Tab = "overview" | "config" | "tune" | "run" | "results" | "localeval" | "leaderboard";

const NAV: { id: Tab; label: string; desc: string; icon: ReactNode }[] = [
  { id: "overview", label: "Overview", desc: "System health & setup", icon: <IconOverview /> },
  { id: "config", label: "Configuration", desc: "Tool parameters", icon: <IconConfig /> },
  { id: "tune", label: "Tune Pipeline", desc: "Score-driven tuning", icon: <IconTune /> },
  { id: "run", label: "Demo Run", desc: "Live pipeline test", icon: <IconPlay /> },
  { id: "results", label: "Results", desc: "VCF output", icon: <IconResults /> },
  { id: "localeval", label: "Local Eval", desc: "Validator-parity scoring", icon: <IconEval /> },
  { id: "leaderboard", label: "Leaderboard", desc: "Rankings & analytics", icon: <IconLeaderboard /> },
];

function groupChecks(checks: HealthReport["checks"]) {
  const groups: Record<string, typeof checks> = {
    Environment: [],
    Docker: [],
    Reference: [],
    Network: [],
    Other: [],
  };
  for (const c of checks) {
    const n = c.name.toLowerCase();
    if (n.includes("docker") || n.includes("image")) groups.Docker.push(c);
    else if (n.includes("reference") || n.includes("chr")) groups.Reference.push(c);
    else if (n.includes("platform") || n.includes("chain") || n.includes("network") || n.includes("access"))
      groups.Network.push(c);
    else if (n.includes("python") || n.includes("ram") || n.includes("disk") || n.includes("env") || n.includes("config") || n.includes("module") || n.includes("wallet") || n.includes("deps"))
      groups.Environment.push(c);
    else groups.Other.push(c);
  }
  return Object.entries(groups).filter(([, items]) => items.length > 0);
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [template, setTemplate] = useState("gatk");
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [platform, setPlatform] = useState<Record<string, unknown> | null>(null);
  const [configContent, setConfigContent] = useState("");
  const [configDirty, setConfigDirty] = useState(false);
  const [configMsg, setConfigMsg] = useState("");
  const [activeRun, setActiveRun] = useState<RunRecord | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<VcfSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  const refreshHealth = useCallback(async () => {
    setRefreshing(true);
    try {
      const [h, p] = await Promise.all([api.health(template), api.platform()]);
      setHealth(h);
      setPlatform(p);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }, [template]);

  const loadConfig = useCallback(async (tpl: string) => {
    try {
      const data = await api.getConfig(tpl);
      setConfigContent(data.content);
      setConfigDirty(false);
      setConfigMsg("");
    } catch (e) {
      setConfigMsg(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refreshResults = useCallback(async () => {
    try {
      setResults(await api.latestResults());
    } catch {
      /* optional */
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    loadConfig(template);
  }, [template, refreshHealth, loadConfig]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [logs]);

  const startDemo = async () => {
    setLoading(true);
    setLogs([]);
    setError("");
    try {
      const run = await api.startDemo(template);
      setActiveRun(run);
      setTab("run");
      streamLogs(
        run.id,
        (line) => setLogs((prev) => [...prev, line]),
        async () => {
          setLoading(false);
          const updated = await api.listRuns();
          const current = updated.runs.find((r) => r.id === run.id);
          if (current) setActiveRun(current);
          await refreshResults();
          setTab("results");
        },
      );
    } catch (e) {
      setLoading(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const stopDemo = async () => {
    if (!activeRun) return;
    try {
      setActiveRun(await api.stopRun(activeRun.id));
      setLoading(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const saveConfig = async () => {
    try {
      const res = await api.saveConfig(template, configContent);
      setConfigDirty(false);
      setConfigMsg(`Saved successfully — ${res.parsed_count} parameters validated`);
    } catch (e) {
      setConfigMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const failedCount = health?.summary.failed ?? 0;
  const passPct = health ? (health.summary.passed / health.summary.total) * 100 : 0;
  const ready = failedCount === 0;
  const pipelineStep = useMemo(() => {
    if (tab === "localeval") return 6;
    if (results?.found) return 5;
    if (activeRun?.demo_complete || activeRun?.status === "completed") return 4;
    if (loading || activeRun?.status === "running") return 3;
    if (configDirty) return 2;
    return ready ? 2 : 1;
  }, [results, activeRun, loading, configDirty, ready, tab]);

  const grouped = health ? groupChecks(health.checks) : [];
  const failedChecks = health?.checks.filter((c) => c.status === "fail") ?? [];

  return (
    <div className="layout">
      <div className="layout__bg" aria-hidden />

      <aside className="sidebar">
        <div className="sidebar__brand">
          <div className="sidebar__logo"><IconDna /></div>
          <div>
            <span className="sidebar__title">Minos</span>
            <span className="sidebar__subtitle">Local Lab</span>
          </div>
        </div>

        <nav className="sidebar__nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sidebar__link ${tab === item.id ? "sidebar__link--active" : ""}`}
              onClick={() => setTab(item.id)}
            >
              <span className="sidebar__link-icon">{item.icon}</span>
              <span className="sidebar__link-text">
                <span className="sidebar__link-label">{item.label}</span>
                <span className="sidebar__link-desc">{item.desc}</span>
              </span>
            </button>
          ))}
        </nav>

        <div className="sidebar__footer">
          <a href="https://theminos.ai/" target="_blank" rel="noreferrer" className="sidebar__external">
            Official dashboard <IconExternal />
          </a>
          <span className="sidebar__badge">Sandbox · No TAO</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1 className="topbar__title">
              {NAV.find((n) => n.id === tab)?.label}
            </h1>
            <p className="topbar__subtitle">
              Test your SN107 miner locally before registering on mainnet
            </p>
          </div>
          <div className="topbar__actions">
            <TemplateSelect value={template} onChange={setTemplate} />
            <Button variant="secondary" icon={<IconRefresh spinning={refreshing} />} onClick={refreshHealth}>
              Refresh
            </Button>
            <Button variant="primary" disabled={!ready || loading} onClick={startDemo}>
              {loading ? "Running demo…" : "Run demo"}
            </Button>
          </div>
        </header>

        <section className="pipeline-card card">
          <PipelineStepper activeStep={pipelineStep} />
        </section>

        {error && (
          <div className="toast toast--error" role="alert">{error}</div>
        )}

        {failedChecks.length > 0 && tab === "overview" && (
          <div className="alert-banner" role="status">
            <div className="alert-banner__content">
              <strong>{failedChecks.length} check{failedChecks.length > 1 ? "s" : ""} need attention</strong>
              <span>Demo runs are disabled until all health checks pass.</span>
            </div>
            <ul className="alert-banner__list">
              {failedChecks.map((c) => (
                <li key={c.name}>
                  <StatusBadge status="fail" />
                  <span>{c.name}</span>
                  <code>{c.detail}</code>
                </li>
              ))}
            </ul>
          </div>
        )}

        {tab === "overview" && (
          <div className="page-grid page-grid--overview">
            <div className="card card--highlight">
              <div className="health-summary">
                <ProgressRing pct={passPct} label="Health" />
                <div className="health-summary__stats">
                  <StatCard label="Checks passed" value={health ? `${health.summary.passed}/${health.summary.total}` : "—"} tone="success" />
                  <StatCard label="Failed" value={health?.summary.failed ?? "—"} tone={failedCount ? "danger" : "success"} />
                  <StatCard label="Template" value={template.toUpperCase()} tone="accent" hint="Active variant caller" />
                  <div className="health-summary__api">
                    <span className="health-summary__api-label">Platform API</span>
                    <span className={`health-summary__api-status ${platform?.reachable ? "is-up" : "is-down"}`}>
                      {platform?.reachable ? "Connected" : "Unreachable"}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card__header">
                <h2>Environment checks</h2>
                <span className="card__meta">{health?.checks.length ?? 0} items</span>
              </div>
              <div className="check-groups">
                {!health && (
                  <div className="check-groups">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <div key={i} className="skeleton skeleton-row" />
                    ))}
                  </div>
                )}
                {grouped.map(([name, items]) => (
                  <details key={name} className="check-group" open={items.some((c) => c.status === "fail")}>
                    <summary className="check-group__title">
                      {name}
                      <span className="check-group__count">{items.filter((c) => c.status === "pass").length}/{items.length}</span>
                    </summary>
                    <ul className="check-group__list">
                      {items.map((c) => (
                        <li key={c.name} className={`check-row check-row--${c.status}`}>
                          <StatusBadge status={c.status} />
                          <span className="check-row__name">{c.name}</span>
                          <span className="check-row__detail">{c.detail}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            </div>

            <div className="card card--guide">
              <h2>Getting started</h2>
              <ol className="guide-list">
                <li><strong>Fix health checks</strong> — Docker, reference FASTA (chr1–22), and Python venv must pass.</li>
                <li><strong>Tune configuration</strong> — Edit quality params only; threads/RAM stay local.</li>
                <li><strong>Run demo</strong> — Uses <code>neurons.miner --demo</code> against platform sandbox.</li>
                <li><strong>Go live</strong> — Register on netuid 107, configure <code>.env</code>, run <code>start-miner.sh</code>.</li>
              </ol>
            </div>
          </div>
        )}

        {tab === "config" && (
          <div className="card config-panel">
            <div className="card__header">
              <div>
                <h2>Tool configuration</h2>
                <p className="card__desc">configs/{template}.conf — picked up by live miner on the <strong>next open round</strong> (not instant on-chain)</p>
              </div>
              <div className="btn-group">
                <Button variant="secondary" onClick={() => loadConfig(template)}>Reload</Button>
                <Button variant="primary" disabled={!configDirty} onClick={saveConfig}>
                  {configDirty ? "Save changes" : "Saved"}
                </Button>
              </div>
            </div>
            {configMsg && <div className="toast toast--info">{configMsg}</div>}
            <p className="tune-inline-note">
              Saving here writes to disk immediately. Your pm2 miner re-reads this file when the next round opens (~30s poll).
              Use <button type="button" className="link-btn" onClick={() => setTab("tune")}>Tune Pipeline</button> for score-based recommendations.
            </p>
            <div className="editor-wrap">
              <div className="editor-wrap__bar">
                <span className="editor-wrap__dot editor-wrap__dot--r" />
                <span className="editor-wrap__dot editor-wrap__dot--y" />
                <span className="editor-wrap__dot editor-wrap__dot--g" />
                <span className="editor-wrap__filename">{template}.conf</span>
              </div>
              <textarea
                className="config-editor"
                value={configContent}
                onChange={(e) => {
                  setConfigContent(e.target.value);
                  setConfigDirty(true);
                }}
                spellCheck={false}
              />
            </div>
          </div>
        )}

        {tab === "tune" && (
          <TunePanel
            template={template}
            onConfigApplied={() => loadConfig(template)}
            onRunDemo={() => { setTab("run"); startDemo(); }}
          />
        )}

        {tab === "localeval" && (
          <LocalEvalPanel template={template} />
        )}

        {tab === "run" && (
          <div className="page-grid page-grid--run">
            <div className="card">
              <div className="card__header"><h2>Demo pipeline</h2></div>
              <div className="run-meta">
                {activeRun ? (
                  <>
                    <StatCard label="Run ID" value={activeRun.id} />
                    <StatCard label="Status" value={activeRun.status} tone={activeRun.status === "completed" ? "success" : "accent"} />
                    <StatCard label="Demo complete" value={activeRun.demo_complete ? "Yes" : "Pending"} />
                  </>
                ) : (
                  <p className="card__desc">Start a demo run to verify variant calling end-to-end. Est. 3–30 min depending on template.</p>
                )}
              </div>
              <div className="btn-group" style={{ marginTop: "1.25rem" }}>
                <Button variant="primary" disabled={loading} onClick={startDemo}>
                  {loading ? "Running…" : "Start demo run"}
                </Button>
                {activeRun?.status === "running" && (
                  <Button variant="danger" onClick={stopDemo}>Stop</Button>
                )}
              </div>
            </div>
            <div className="card terminal-card">
              <div className="editor-wrap__bar">
                <span className="editor-wrap__dot editor-wrap__dot--r" />
                <span className="editor-wrap__dot editor-wrap__dot--y" />
                <span className="editor-wrap__dot editor-wrap__dot--g" />
                <span className="editor-wrap__filename">miner.log</span>
                {loading && <span className="terminal-card__live">LIVE</span>}
              </div>
              <div ref={logRef} className="log-view">
                {logs.length ? logs.join("\n") : "Waiting for miner output…\n\nTip: Demo connects to api.theminos.ai sandbox — no wallet required."}
              </div>
            </div>
          </div>
        )}

        {tab === "leaderboard" && <LeaderboardPanel />}

        {tab === "results" && (
          <div className="card">
            <div className="card__header">
              <h2>Variant calling output</h2>
              <Button variant="secondary" onClick={refreshResults}>Refresh</Button>
            </div>
            {!results?.found ? (
              <div className="empty-state empty-state--large">
                <p>No VCF output yet</p>
                <span>{results?.message ?? "Complete a demo run to see variant counts and preview."}</span>
                <Button variant="primary" onClick={startDemo} disabled={!ready || loading}>Run demo</Button>
              </div>
            ) : (
              <>
                <div className="stat-row">
                  <StatCard label="Total variants" value={results.variant_count ?? 0} tone="accent" />
                  <StatCard label="SNPs" value={results.snp_count ?? 0} />
                  <StatCard label="INDELs" value={results.indel_count ?? 0} />
                </div>
                <p className="results-path">{results.path}</p>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Chrom</th>
                        <th>Position</th>
                        <th>Ref</th>
                        <th>Alt</th>
                        <th>Quality</th>
                        <th>Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.preview?.map((row, i) => (
                        <tr key={`${row.chrom}-${row.pos}-${i}`}>
                          <td><code>{row.chrom}</code></td>
                          <td>{row.pos}</td>
                          <td><code>{row.ref}</code></td>
                          <td><code>{row.alt}</code></td>
                          <td>{row.qual}</td>
                          <td><span className={`type-pill type-pill--${row.type.toLowerCase()}`}>{row.type}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </main>

      <nav className="mobile-nav" aria-label="Primary">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`mobile-nav__btn ${tab === item.id ? "mobile-nav__btn--active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.icon}
            <span>{item.label.split(" ")[0]}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
