const API = "/api";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export type Check = {
  name: string;
  status: "pass" | "fail" | "warn" | "skip";
  detail: string;
  category: string;
};

export type HealthReport = {
  role: string;
  template: string | null;
  timestamp: string;
  summary: { total: number; passed: number; failed: number; warned: number };
  checks: Check[];
};

export type RunRecord = {
  id: string;
  template: string;
  status: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  message: string;
  demo_complete: boolean;
};

export type RoundInfo = {
  round_id: string;
  status: string;
  region: string;
  label: string;
  is_live: boolean;
  is_finalized: boolean;
  submission_count: number;
  scored_submission_count: number;
  score_count: number;
};

export type LeaderboardEntry = {
  hotkey: string;
  uid: number;
  rank: number;
  combined_final: number;
  weight: number;
  eligible: boolean;
  participation_count: number;
  validator_count: number;
  tool_name: string;
  status: string;
};

export type LeaderboardData = {
  round_id: string;
  round: RoundInfo & { label: string };
  entries: LeaderboardEntry[];
  total_miners: number;
  scored_count: number;
  fetched_at?: string;
};

export type WinnerRow = {
  hotkey: string;
  short_hotkey: string;
  uid?: number;
  wins: number;
  win_rate?: number;
  podium_count: number;
  avg_score?: number;
  rounds_participated: number;
};

export type LeaderboardAnalytics = {
  rounds_analyzed: number;
  winner_leaderboard: WinnerRow[];
  avg_score_leaderboard: Array<{
    hotkey: string;
    short_hotkey: string;
    uid?: number;
    avg_score: number;
    wins: number;
    rounds_participated: number;
  }>;
  round_winners: Array<{
    round_id: string;
    label: string;
    region: string;
    hotkey: string;
    short_hotkey: string;
    uid?: number;
    score?: number;
  }>;
  tool_distribution: Record<string, number>;
  unique_miners: number;
};

export type VcfSummary = {
  found: boolean;
  message?: string;
  variant_count?: number;
  snp_count?: number;
  indel_count?: number;
  path?: string;
  preview?: Array<{
    chrom: string;
    pos: string;
    ref: string;
    alt: string;
    qual: string;
    type: string;
  }>;
};

export const api = {
  meta: () => fetchJson<{ name: string; official_dashboard: string }>("/meta"),
  health: (template: string) => fetchJson<HealthReport>(`/health?template=${template}`),
  platform: () => fetchJson<Record<string, unknown>>("/platform"),
  templates: () => fetchJson<{ templates: Array<{ id: string; label: string }> }>("/templates"),
  getConfig: (template: string) =>
    fetchJson<{ content: string; parsed_count: number }>(`/config/${template}`),
  saveConfig: (template: string, content: string) =>
    fetchJson<{ saved: boolean; parsed_count: number }>(`/config/${template}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  listRuns: () => fetchJson<{ runs: RunRecord[] }>("/runs"),
  startDemo: (template: string) =>
    fetchJson<RunRecord>("/runs/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template }),
    }),
  stopRun: (runId: string) =>
    fetchJson<RunRecord>(`/runs/${runId}/stop`, { method: "POST" }),
  latestResults: () => fetchJson<VcfSummary>("/results/latest"),
  leaderboardRounds: () => fetchJson<{ rounds: RoundInfo[]; latest_finalized_round_id?: string }>("/leaderboard/rounds"),
  leaderboard: (roundId?: string, mode?: "latest" | "live") => {
    const params = new URLSearchParams();
    if (roundId) params.set("round_id", roundId);
    else if (mode) params.set("mode", mode);
    else params.set("mode", "latest");
    return fetchJson<LeaderboardData>(`/leaderboard?${params}`);
  },
  leaderboardSync: (force = false) =>
    fetchJson<{ synced: number; finalized_available: number }>(`/leaderboard/sync?force=${force}`, { method: "POST" }),
  leaderboardAnalytics: (sync = false) =>
    fetchJson<LeaderboardAnalytics>(`/leaderboard/analytics?sync=${sync}`),
  minerHistory: (hotkey: string) => fetchJson<{
    hotkey: string;
    rounds_found: number;
    wins: number;
    podiums: number;
    avg_score?: number;
    best_score?: number;
    worst_score?: number;
    history: Array<{
      round_id: string;
      label: string;
      region: string;
      rank: number;
      combined_final?: number;
      weight?: number;
      participation_count?: number;
      tool_name?: string;
    }>;
  }>(`/leaderboard/miner/${encodeURIComponent(hotkey)}`),
  myHotkey: () => fetchJson<{ hotkey: string | null; configured: boolean }>("/leaderboard/my-hotkey"),
};

export function streamLogs(runId: string, onLine: (line: string) => void, onDone: () => void) {
  const source = new EventSource(`${API}/runs/${runId}/logs`);
  source.onmessage = (ev) => onLine(ev.data);
  source.addEventListener("done", () => {
    source.close();
    onDone();
  });
  source.onerror = () => {
    source.close();
    onDone();
  };
  return source;
}
