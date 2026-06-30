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

export type ColdkeyWinnerRow = {
  coldkey: string;
  short_coldkey: string;
  hotkey_count: number;
  uids: number[];
  hotkeys: WinnerRow[];
  wins: number;
  win_rate?: number;
  podium_count: number;
  avg_score?: number;
  rounds_participated: number;
};

export type ConfigChangeRecord = {
  id: string;
  timestamp: string;
  template: string;
  old_content: string;
  new_content: string;
  changed_params: string[];
  changes: Array<{
    param: string;
    old_value: any;
    new_value: any;
  }>;
  source: string;
};

export type LastUpdateAnalysis = {
  round_id: string;
  round_label: string;
  update_timestamp?: string;
  score_before: number;
  score_after: number;
  difference: number;
  needs_rollback?: boolean;
  message: string;
  updates: ConfigChangeRecord[];
  rounds_before_update?: number;
  rounds_after_update?: number;
};

export type LeaderboardAnalytics = {
  rounds_analyzed: number;
  coldkey_mapping_available: boolean;
  unmapped_hotkey_count: number;
  unique_coldkeys: number;
  winner_leaderboard: WinnerRow[];
  coldkey_winner_leaderboard: ColdkeyWinnerRow[];
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
    coldkey?: string | null;
    short_coldkey?: string | null;
    uid?: number;
    score?: number;
  }>;
  tool_distribution: Record<string, number>;
  unique_miners: number;
};

export type TuneLogEntry = {
  ts: string;
  phase: string;
  level: string;
  message: string;
  data: Record<string, unknown>;
};

export type TuneRecommendation = {
  id: string;
  param: string;
  current_value: unknown;
  proposed_value: unknown;
  reason: string;
  priority: number;
  source: string;
  selected?: boolean;
  llm_rank?: number;
  llm_confidence?: string;
};

export type LlmTuneAdvisory = {
  enabled: boolean;
  configured: boolean;
  model: string;
  used: boolean;
  summary?: string | null;
  strategy?: string | null;
  notes?: string | null;
  error?: string | null;
};

export type TunePipelineResult = {
  template: string;
  rounds_analyzed: number;
  generated_at: string;
  my_hotkey: string | null;
  config_flow: {
    real_time_on_chain: boolean;
    summary: string;
    steps: string[];
    restart_required_for: string[];
    no_restart_for: string[];
  };
  limitations: {
    other_miner_configs: string;
    haplotype_detail: string;
    region_specific_configs: string;
  };
  current_config: { content: string; params: Record<string, unknown> };
  region_analysis: {
    recent_rounds: Array<{ round_id: string; region: string; chrom: string; width_mb?: number }>;
    chromosome_frequency: Array<{ chrom: string; count: number }>;
    typical_window_mb: number;
  };
  top_miner_analysis: {
    summary: {
      median_combined?: number;
      median_snp?: number;
      median_indel?: number;
      tool_win_counts: Record<string, number>;
    };
    tool_win_counts: Record<string, number>;
    recent_winners: Array<{
      round_id: string;
      round_label: string;
      region: string;
      hotkey: string;
      short_hotkey: string;
      coldkey?: string | null;
      short_coldkey?: string | null;
      uid?: number;
      combined_final?: number;
      snp_final?: number;
      indel_final?: number;
      tool_name?: string;
    }>;
  };
  my_performance: {
    short_hotkey: string;
    scored_rounds: number;
    latest_round?: {
      round_id: string;
      round_label?: string;
      region: string;
      combined_final?: number;
      snp_final?: number;
      indel_final?: number;
    } | null;
    avg_combined?: number;
    avg_snp?: number;
    avg_indel?: number;
    history: Array<{
      round_id: string;
      region: string;
      rank?: number;
      combined_final?: number;
      snp_final?: number;
      indel_final?: number;
      tool_name?: string;
      updates?: ConfigChangeRecord[];
    }>;
  } | null;
  diagnosis: {
    available: boolean;
    score_note?: string;
    interpretation: string;
    gaps: Record<string, { value: number; severity: string }>;
    latest_round?: {
      round_id?: string;
      round_label?: string;
      region?: string;
      my_combined?: number;
      my_snp?: number;
      my_indel?: number;
      winner_hotkey?: string | null;
      gaps: Record<string, { value: number; severity: string }>;
    } | null;
    average?: {
      my_combined?: number;
      my_snp?: number;
      my_indel?: number;
      gaps: Record<string, { value: number; severity: string }>;
    };
  };
  last_update_analysis?: LastUpdateAnalysis | null;
  llm_advisory?: LlmTuneAdvisory | null;
  rule_recommendation_count?: number;
  rule_recommendations?: TuneRecommendation[];
  recommendations: TuneRecommendation[];
  proposed_config: { content: string; changed_params: string[]; diff_summary: string[] };
  logs: TuneLogEntry[];
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
  myHotkey: () => fetchJson<{ hotkey: string | null; coldkey: string | null; configured: boolean }>("/leaderboard/my-hotkey"),
  tuneAnalyze: (template: string, rounds = 30, sync = false) =>
    fetchJson<TunePipelineResult>(
      `/tune/analyze?template=${template}&rounds=${rounds}&sync=${sync}&use_llm=false`,
    ),
  tuneLlmJudge: (payload: {
    template: string;
    current_config: { params: Record<string, unknown> };
    diagnosis: TunePipelineResult["diagnosis"];
    rule_recommendations: TuneRecommendation[];
    top_miner_summary: TunePipelineResult["top_miner_analysis"]["summary"];
    my_performance: TunePipelineResult["my_performance"];
    last_update_analysis: TunePipelineResult["last_update_analysis"];
    region_analysis: TunePipelineResult["region_analysis"];
    logs: TuneLogEntry[];
  }) =>
    fetchJson<{
      recommendations: TuneRecommendation[];
      llm_advisory: LlmTuneAdvisory;
      rule_recommendation_count: number;
      proposed_config: TunePipelineResult["proposed_config"];
      logs: TuneLogEntry[];
    }>("/tune/llm-judge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  tuneLlmStatus: () =>
    fetchJson<{ configured: boolean; enabled: boolean; model: string; provider: string }>("/tune/llm-status"),
  tuneApply: (template: string, recommendations: TuneRecommendation[]) =>
    fetchJson<{ message: string; changed_params: string[]; content: string }>("/tune/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template, recommendations }),
    }),
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
