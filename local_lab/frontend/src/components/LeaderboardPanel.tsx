import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type LeaderboardAnalytics, type LeaderboardData, type RoundInfo } from "../api/client";
import { Button } from "./UI";

type LbView = "ranking" | "analytics" | "miner";
type AnalyticsGroup = "hotkey" | "coldkey";

function shortHotkey(hk: string) {
  return hk.length > 16 ? `${hk.slice(0, 6)}...${hk.slice(-4)}` : hk;
}


function formatRoundLabel(roundId: string) {
  const dt = new Date(roundId);
  if (Number.isNaN(dt.getTime())) return roundId.slice(0, 16);
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  const hh = String(dt.getHours()).padStart(2, "0");
  const mi = String(dt.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${mi}`;
}

function statusPill(status: string) {
  const s = status.toLowerCase();
  if (s === "completed") return "lb-pill lb-pill--ok";
  if (s === "scoring") return "lb-pill lb-pill--warn";
  if (s === "open") return "lb-pill lb-pill--live";
  return "lb-pill";
}

export function LeaderboardPanel() {
  const [view, setView] = useState<LbView>("ranking");
  const [rounds, setRounds] = useState<RoundInfo[]>([]);
  const [selectedRoundId, setSelectedRoundId] = useState<string>("");
  const [mode, setMode] = useState<"latest" | "live" | "history">("latest");
  const [leaderboard, setLeaderboard] = useState<LeaderboardData | null>(null);
  const [analytics, setAnalytics] = useState<LeaderboardAnalytics | null>(null);
  const [myHotkey, setMyHotkey] = useState<string | null>(null);
  const [myColdkey, setMyColdkey] = useState<string | null>(null);
  const [analyticsGroup, setAnalyticsGroup] = useState<AnalyticsGroup>("hotkey");
  const [expandedColdkey, setExpandedColdkey] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [minerQuery, setMinerQuery] = useState("");
  const [minerHistory, setMinerHistory] = useState<Awaited<ReturnType<typeof api.minerHistory>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const loadSeq = useRef(0);

  const loadRounds = useCallback(async () => {
    const data = await api.leaderboardRounds();
    setRounds(data.rounds);
    setSelectedRoundId((prev) => prev || data.latest_finalized_round_id || "");
    return data;
  }, []);

  const loadLeaderboard = useCallback(async (roundId?: string, m?: "latest" | "live") => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setError("");
    try {
      const data = await api.leaderboard(roundId, m);
      if (seq !== loadSeq.current) return;
      setLeaderboard(data);
      setSelectedRoundId(data.round_id);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

  const loadAnalytics = useCallback(async (sync = false) => {
    setLoading(true);
    setError("");
    try {
      if (sync) {
        setSyncing(true);
        await api.leaderboardSync(sync);
      }
      setAnalytics(await api.leaderboardAnalytics(sync));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [_, my] = await Promise.all([loadRounds(), api.myHotkey()]);
        setMyHotkey(my.hotkey);
        setMyColdkey(my.coldkey);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [loadRounds]);

  useEffect(() => {
    if (view !== "ranking") return;
    if (mode === "latest") loadLeaderboard(undefined, "latest");
    else if (mode === "live") loadLeaderboard(undefined, "live");
    else if (mode === "history" && selectedRoundId) loadLeaderboard(selectedRoundId);
  }, [view, mode, loadLeaderboard]);

  // History round changes (dropdown) — load only when round id changes in history mode
  useEffect(() => {
    if (view !== "ranking" || mode !== "history" || !selectedRoundId) return;
    loadLeaderboard(selectedRoundId);
  }, [view, mode, selectedRoundId, loadLeaderboard]);

  useEffect(() => {
    if (view === "analytics" && !analytics) loadAnalytics();
  }, [view, analytics, loadAnalytics]);

  const filtered = useMemo(() => {
    if (!leaderboard?.entries) return [];
    const q = search.trim().toLowerCase();
    if (!q) return leaderboard.entries;
    return leaderboard.entries.filter(
      (e) =>
        e.hotkey.toLowerCase().includes(q) ||
        String(e.uid).includes(q),
    );
  }, [leaderboard, search]);

  const podium = filtered.slice(0, 3);

  const lookupMiner = async (hotkey?: string) => {
    const q = (hotkey ?? minerQuery).trim();
    if (!q) return;
    setMinerQuery(q);
    setLoading(true);
    setError("");
    try {
      setMinerHistory(await api.minerHistory(q));
      setView("miner");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="lb-panel">
      <div className="lb-toolbar">
        <div className="lb-toolbar__left">
          <button type="button" className={`lb-tab ${view === "ranking" ? "lb-tab--active" : ""}`} onClick={() => setView("ranking")}>
            Ranking
          </button>
          <button type="button" className={`lb-tab ${view === "analytics" ? "lb-tab--active" : ""}`} onClick={() => setView("analytics")}>
            Analytics
          </button>
          <button type="button" className={`lb-tab ${view === "miner" ? "lb-tab--active" : ""}`} onClick={() => setView("miner")}>
            Miner lookup
          </button>
        </div>
        <div className="lb-toolbar__right">
          <Button variant="secondary" onClick={() => {
            if (view === "analytics") loadAnalytics(true);
            else if (mode === "live") loadLeaderboard(undefined, "live");
            else if (mode === "history" && selectedRoundId) loadLeaderboard(selectedRoundId);
            else loadLeaderboard(undefined, "latest");
          }}>
            {syncing ? "Syncing…" : "Refresh"}
          </Button>
        </div>
      </div>

      {error && <div className="toast toast--error">{error}</div>}

      {view === "ranking" && (
        <>
          <div className="lb-controls card">
            <div className="lb-mode">
              <button type="button" className={`lb-mode__btn ${mode === "latest" ? "lb-mode__btn--active" : ""}`} onClick={() => setMode("latest")}>
                Latest finalized
              </button>
              <button type="button" className={`lb-mode__btn ${mode === "live" ? "lb-mode__btn--active" : ""}`} onClick={() => setMode("live")}>
                Live round
              </button>
              <button type="button" className={`lb-mode__btn ${mode === "history" ? "lb-mode__btn--active" : ""}`} onClick={() => setMode("history")}>
                Round history
              </button>
            </div>
            {mode === "history" && (
              <select
                className="template-select__input lb-round-select"
                value={selectedRoundId}
                onChange={(e) => setSelectedRoundId(e.target.value)}
              >
                {rounds.map((r) => (
                  <option key={r.round_id} value={r.round_id}>
                    {formatRoundLabel(r.round_id)} — {r.status.toUpperCase()} — {r.region}
                  </option>
                ))}
              </select>
            )}
          </div>

          {leaderboard && (
            <div className="lb-round-meta card card--highlight">
              <div>
                <span className={statusPill(leaderboard.round.status)}>{leaderboard.round.status}</span>
                <strong className="lb-round-meta__title">Round {formatRoundLabel(leaderboard.round.round_id ?? leaderboard.round_id)}</strong>
                <span className="lb-round-meta__region">{leaderboard.round.region}</span>
              </div>
              <div className="lb-round-meta__stats">
                <span>Scored {leaderboard.scored_count}/{leaderboard.total_miners}</span>
                <span>{leaderboard.round.submission_count} submissions</span>
              </div>
            </div>
          )}

          {podium.length > 0 && (
            <div className="lb-podium">
              {podium.map((e, i) => (
                <div key={e.hotkey} className={`lb-podium__card lb-podium__card--${i + 1} ${e.hotkey === myHotkey ? "lb-podium__card--mine" : ""}`}>
                  <span className="lb-podium__rank">#{String(e.rank).padStart(3, "0")}</span>
                  <span className="lb-podium__uid">UID {e.uid}</span>
                  <code className="lb-podium__hotkey">{shortHotkey(e.hotkey)}</code>
                  <span className="lb-podium__score">{(e.combined_final ?? 0).toFixed(4)}</span>
                  <span className="lb-podium__label">ADV score</span>
                </div>
              ))}
            </div>
          )}

          <div className="card">
            <div className="card__header">
              <h2>Finalized ranking</h2>
              <input
                className="lb-search"
                placeholder="Search by hotkey or UID…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            {loading && !leaderboard ? (
              <div className="empty-state">Loading leaderboard…</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>UID</th>
                      <th>Hotkey</th>
                      <th>Score</th>
                      <th>Weight</th>
                      <th>Elig</th>
                      <th>Part</th>
                      <th>Vals</th>
                      <th>Tool</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((e) => (
                      <tr
                        key={e.hotkey}
                        className={e.hotkey === myHotkey ? "lb-row--mine" : ""}
                        onClick={() => lookupMiner(e.hotkey)}
                        style={{ cursor: "pointer" }}
                      >
                        <td><strong>#{e.rank}</strong></td>
                        <td>{e.uid}</td>
                        <td><code>{shortHotkey(e.hotkey)}</code></td>
                        <td className="lb-score">{(e.combined_final ?? 0).toFixed(4)}</td>
                        <td>{(e.weight ?? 0).toFixed(4)}</td>
                        <td>{e.eligible ? "YES" : "NO"}</td>
                        <td>{e.participation_count} RDS</td>
                        <td>{e.validator_count}</td>
                        <td>{e.tool_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="lb-foot">Total: {filtered.length} miners · Click a row for history</p>
          </div>
        </>
      )}

      {view === "analytics" && (
        <div className="page-grid page-grid--analytics">
          <div className="card">
            <div className="card__header">
              <div className="lb-analytics-header">
                <h2>Wins leaderboard (#1 count)</h2>
                <div className="lb-mode" role="tablist" aria-label="Group analytics by">
                  <button
                    type="button"
                    className={`lb-mode__btn ${analyticsGroup === "hotkey" ? "lb-mode__btn--active" : ""}`}
                    onClick={() => {
                      setAnalyticsGroup("hotkey");
                      setExpandedColdkey(null);
                    }}
                  >
                    By hotkey
                  </button>
                  <button
                    type="button"
                    className={`lb-mode__btn ${analyticsGroup === "coldkey" ? "lb-mode__btn--active" : ""}`}
                    onClick={() => setAnalyticsGroup("coldkey")}
                  >
                    By coldkey
                  </button>
                </div>
              </div>
              <span className="card__meta">
                {analytics?.rounds_analyzed ?? 0} rounds analyzed
                {analyticsGroup === "coldkey" && analytics?.unique_coldkeys != null
                  ? ` · ${analytics.unique_coldkeys} coldkeys`
                  : ""}
              </span>
            </div>
            {analyticsGroup === "coldkey" && analytics && analytics.unmapped_hotkey_count > 0 && (
              <p className="lb-source">
                {analytics.unmapped_hotkey_count} hotkey(s) could not be mapped to a coldkey
                (deregistered or not on SN107). Those rounds are excluded from coldkey totals.
              </p>
            )}
            {loading && !analytics ? (
              <div className="empty-state">Computing analytics…</div>
            ) : analyticsGroup === "hotkey" ? (
              <div className="table-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Hotkey</th>
                      <th>UID</th>
                      <th>Wins</th>
                      <th>Win rate</th>
                      <th>Podiums</th>
                      <th>Avg score</th>
                      <th>Rounds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics?.winner_leaderboard.map((w, i) => (
                      <tr key={w.hotkey} className={w.hotkey === myHotkey ? "lb-row--mine" : ""}>
                        <td>{i + 1}</td>
                        <td><code>{w.short_hotkey}</code></td>
                        <td>{w.uid ?? "—"}</td>
                        <td><strong>{w.wins}</strong></td>
                        <td>{w.win_rate != null ? `${(w.win_rate * 100).toFixed(1)}%` : "—"}</td>
                        <td>{w.podium_count}</td>
                        <td>{w.avg_score?.toFixed(4) ?? "—"}</td>
                        <td>{w.rounds_participated}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Coldkey</th>
                      <th>Hotkeys</th>
                      <th>UIDs</th>
                      <th>Wins</th>
                      <th>Win rate</th>
                      <th>Podiums</th>
                      <th>Avg score</th>
                      <th>Rounds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics?.coldkey_winner_leaderboard.map((w, i) => {
                      const expanded = expandedColdkey === w.coldkey;
                      const clickable = w.hotkeys.length > 0;
                      return (
                        <Fragment key={w.coldkey}>
                          <tr
                            className={[
                              w.coldkey === myColdkey ? "lb-row--mine" : "",
                              clickable ? "lb-row--clickable" : "",
                              expanded ? "lb-row--expanded" : "",
                            ].filter(Boolean).join(" ")}
                            onClick={() => {
                              if (!clickable) return;
                              setExpandedColdkey(expanded ? null : w.coldkey);
                            }}
                            title={clickable ? "Click to show hotkeys" : undefined}
                          >
                            <td>{i + 1}</td>
                            <td>
                              <code>{w.short_coldkey}</code>
                              {clickable && (
                                <span className={`lb-expand-icon ${expanded ? "lb-expand-icon--open" : ""}`} aria-hidden>
                                  ▸
                                </span>
                              )}
                            </td>
                            <td>{w.hotkey_count}</td>
                            <td>{w.uids.length ? w.uids.join(", ") : "—"}</td>
                            <td><strong>{w.wins}</strong></td>
                            <td>{w.win_rate != null ? `${(w.win_rate * 100).toFixed(1)}%` : "—"}</td>
                            <td>{w.podium_count}</td>
                            <td>{w.avg_score?.toFixed(4) ?? "—"}</td>
                            <td>{w.rounds_participated}</td>
                          </tr>
                          {expanded && (
                            <tr className="lb-row-detail">
                              <td colSpan={9}>
                                <div className="lb-coldkey-detail">
                                  <div className="lb-coldkey-detail__header">
                                    <strong>Hotkeys under {w.short_coldkey}</strong>
                                    <span className="lb-coldkey-detail__full" title={w.coldkey}>{w.coldkey}</span>
                                  </div>
                                  <table className="data-table lb-table lb-table--nested">
                                    <thead>
                                      <tr>
                                        <th>Hotkey</th>
                                        <th>UID</th>
                                        <th>Wins</th>
                                        <th>Win rate</th>
                                        <th>Podiums</th>
                                        <th>Avg score</th>
                                        <th>Rounds</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {w.hotkeys.map((hk) => (
                                        <tr
                                          key={hk.hotkey}
                                          className={hk.hotkey === myHotkey ? "lb-row--mine" : ""}
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            lookupMiner(hk.hotkey);
                                          }}
                                          title="Click for miner history"
                                        >
                                          <td><code>{hk.short_hotkey}</code></td>
                                          <td>{hk.uid ?? "—"}</td>
                                          <td><strong>{hk.wins}</strong></td>
                                          <td>{hk.win_rate != null ? `${(hk.win_rate * 100).toFixed(1)}%` : "—"}</td>
                                          <td>{hk.podium_count}</td>
                                          <td>{hk.avg_score?.toFixed(4) ?? "—"}</td>
                                          <td>{hk.rounds_participated}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <div className="card__header">
              <h2>Round winners timeline</h2>
            </div>
            <div className="lb-timeline">
              {analytics?.round_winners.map((w) => (
                <div key={w.round_id} className="lb-timeline__item">
                  <span className="lb-timeline__when">{formatRoundLabel(w.round_id)}</span>
                  <code className="lb-timeline__hk">
                    {analyticsGroup === "coldkey" && w.short_coldkey ? w.short_coldkey : w.short_hotkey}
                  </code>
                  <span className="lb-timeline__score">{(w.score ?? 0).toFixed(4)}</span>
                  <span className="lb-timeline__region">{w.region}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card__header">
              <h2>Avg score ranking</h2>
            </div>
            <div className="table-wrap">
              <table className="data-table lb-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Hotkey</th>
                    <th>Avg score</th>
                    <th>Wins</th>
                    <th>Rounds</th>
                  </tr>
                </thead>
                <tbody>
                  {analytics?.avg_score_leaderboard.slice(0, 20).map((w, i) => (
                    <tr key={w.hotkey}>
                      <td>{i + 1}</td>
                      <td><code>{w.short_hotkey}</code></td>
                      <td className="lb-score">{w.avg_score.toFixed(4)}</td>
                      <td>{w.wins}</td>
                      <td>{w.rounds_participated}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {view === "miner" && (
        <div className="card">
          <div className="card__header">
            <h2>Miner performance history</h2>
          </div>
          <div className="lb-miner-search">
            <input
              className="lb-search lb-search--wide"
              placeholder="Paste full hotkey or search from ranking…"
              value={minerQuery}
              onChange={(e) => setMinerQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && lookupMiner((e.currentTarget as HTMLInputElement).value)}
            />
            <Button variant="primary" onClick={() => lookupMiner(minerQuery)} disabled={!minerQuery.trim()}>
              Lookup
            </Button>
            {myHotkey && (
              <Button variant="secondary" onClick={() => lookupMiner(myHotkey)}>
                My hotkey
              </Button>
            )}
          </div>

          {minerHistory && (
            <>
              <div className="lb-miner-summary">
                <div><span>Rounds</span><strong>{minerHistory.rounds_found}</strong></div>
                <div><span>#1 wins</span><strong>{minerHistory.wins}</strong></div>
                <div><span>Podiums</span><strong>{minerHistory.podiums}</strong></div>
                <div><span>Avg score</span><strong>{minerHistory.avg_score?.toFixed(4) ?? "—"}</strong></div>
                <div><span>Best</span><strong>{minerHistory.best_score?.toFixed(4) ?? "—"}</strong></div>
              </div>
              <div className="table-wrap">
                <table className="data-table lb-table">
                  <thead>
                    <tr>
                      <th>Round</th>
                      <th>Region</th>
                      <th>Rank</th>
                      <th>Score</th>
                      <th>Weight</th>
                      <th>Part</th>
                      <th>Tool</th>
                    </tr>
                  </thead>
                  <tbody>
                    {minerHistory.history.map((h) => (
                      <tr key={h.round_id}>
                        <td>{formatRoundLabel(h.round_id)}</td>
                        <td><code>{h.region}</code></td>
                        <td><strong>#{h.rank}</strong></td>
                        <td className="lb-score">{(h.combined_final ?? 0).toFixed(4)}</td>
                        <td>{(h.weight ?? 0).toFixed(4)}</td>
                        <td>{h.participation_count}</td>
                        <td>{h.tool_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      <p className="lb-source">
        Data from <a href="https://api.theminos.ai/scoring/rounds" target="_blank" rel="noreferrer">api.theminos.ai</a>
        {" · "}
        <a href="https://theminos.ai/dashboard/leaderboard" target="_blank" rel="noreferrer">Official leaderboard</a>
      </p>
    </div>
  );
}
