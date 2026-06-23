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
