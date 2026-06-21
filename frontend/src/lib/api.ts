export type DrawdownTier =
  | "normal"
  | "elevated"
  | "warning"
  | "critical"
  | "emergency";

export interface StatusResponse {
  phase: string;
  mode: string;
  last_cycle_at: string | null;
  next_cycle_at: string | null;
  connected: boolean;
  mt5_connected?: boolean;
  engine_running?: boolean;
  engine_paused?: boolean;
  cycle_in_progress?: boolean;
  timestamp?: string;
  zmq_last_error?: string | null;
  last_tick_at?: string | null;
  last_tick_age_ms?: number | null;
}

export interface ControlStateResponse {
  engine_available: boolean;
  engine_running: boolean;
  engine_paused: boolean;
  cycle_in_progress: boolean;
  mode: string;
  mt5_connected: boolean;
  zmq_last_error?: string | null;
}

export interface ControlActionResponse {
  ok: boolean;
  status?: string;
  message?: string;
  result?: Record<string, unknown>;
}

export interface AccountResponse {
  equity: number;
  balance: number;
  margin: number;
  free_margin: number;
  gross_exposure: number;
  daily_pnl?: number;
  return_pct?: number;
}

export interface Position {
  id: string;
  symbol: string;
  direction: "long" | "short";
  size: number;
  entry: number;
  sl: number | null;
  tp: number | null;
  unrealized_pnl: number;
  opened_at: string;
}

export interface PositionsResponse {
  positions: Position[];
  total_exposure?: number;
  total_unrealized_pnl?: number;
}

export interface AgentVote {
  agent: string;
  symbol?: string;
  vote: "buy" | "sell" | "hold" | "skip";
  confidence: number;
  reasoning?: string;
}

export interface Trade {
  id: string;
  timestamp: string;
  symbol: string;
  direction: string;
  size: number;
  entry: number;
  exit?: number;
  pnl?: number;
  status: string;
  confidence?: number;
  agent_votes?: AgentVote[];
  reasoning?: string;
  regime?: string;
  session?: string;
  slippage?: number;
  latency_ms?: number;
}

export interface TradesResponse {
  trades: Trade[];
  total: number;
  limit: number;
  offset: number;
}

export interface AgentStats {
  agent: string;
  win_rate: number;
  avg_r: number;
  samples: number;
}

export interface CycleDecision {
  symbol: string;
  action: string;
  executed: boolean;
  reason?: string;
  features_summary?: string;
  orchestrator_output?: string;
  agent_votes?: AgentVote[];
}

export interface LastCycleResponse {
  symbols_processed: number;
  decisions: CycleDecision[];
  agent_votes: AgentVote[];
}

export interface RiskViolation {
  timestamp: string;
  type: string;
  severity: string;
  message: string;
}

export interface MarginState {
  margin_pct: number;
  leverage: number;
  concentration_pct: number;
}

export interface RiskResponse {
  dd_tier: DrawdownTier;
  drawdown_pct: number;
  sharpe: number;
  discipline: number;
  margin_state: MarginState;
  violations?: RiskViolation[];
  compliance_score?: number;
}

export type MarketHealth = "green" | "amber" | "red";

export interface Instrument {
  symbol: string;
  category: string;
  bias: string;
  allocation: number;
  session_active: boolean;
  last_regime: string;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  spread?: number | null;
  change_pct?: number | null;
  tick_age_ms?: number | null;
  market_health?: MarketHealth | null;
  bar_age_sec?: number | null;
}

export interface InstrumentsResponse {
  instruments: Instrument[];
  count?: number;
}

export interface MarketLiveResponse {
  last_tick_at: string | null;
  last_tick_age_ms: number | null;
  instruments: Record<
    string,
    Pick<
      Instrument,
      | "bid"
      | "ask"
      | "mid"
      | "spread"
      | "change_pct"
      | "tick_age_ms"
      | "market_health"
      | "bar_age_sec"
    >
  >;
  count?: number;
}

export interface RuntimeStatePayload {
  phase?: string;
  mode?: string;
  last_cycle_at?: string | null;
  next_cycle_at?: string | null;
  connected?: boolean;
  engine_running?: boolean;
  mt5_connected?: boolean;
  engine_paused?: boolean;
  cycle_in_progress?: boolean;
  zmq_last_error?: string | null;
  timestamp?: string;
  account?: AccountResponse & { initial_equity?: number };
  positions?: Array<Record<string, unknown>>;
  risk?: Record<string, unknown>;
  last_cycle?: LastCycleResponse;
  equity_history?: EquityPoint[];
  instruments?: Record<string, Record<string, unknown>>;
  market?: {
    last_tick_at?: string | null;
    last_tick_age_ms?: number | null;
  };
}

export interface EquityPoint {
  t: string;
  equity: number;
}

export interface EquityCurveResponse {
  points: EquityPoint[];
}

export interface WSMessage {
  type: string;
  payload: unknown;
}

export interface MarketAlertPayload {
  severity: string;
  message: string;
  symbols: string[];
  last_tick_age_ms?: number | null;
}

export interface TicksPayload {
  last_tick_at: string | null;
  last_tick_age_ms: number | null;
  instruments: Record<string, Record<string, unknown>>;
}

const API_BASE = "/api";

function authHeaders(): HeadersInit {
  const token = import.meta.env.VITE_DASHBOARD_AUTH_TOKEN as string | undefined;
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (token?.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: body != null ? JSON.stringify(body) : undefined,
  });
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : `API ${path} failed: ${res.status}`,
    );
  }
  return data;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : `API ${path} failed: ${res.status}`,
    );
  }
  return data;
}

function directionToVote(direction: string): AgentVote["vote"] {
  const d = direction.toLowerCase().replace("direction.", "");
  if (d === "buy") return "buy";
  if (d === "sell") return "sell";
  if (d === "hold") return "hold";
  return "skip";
}

function mapAgentVotes(raw: Array<Record<string, unknown>> | undefined): AgentVote[] {
  return (raw ?? []).map((v) => ({
    agent: String(v.agent ?? ""),
    symbol: v.symbol ? String(v.symbol) : undefined,
    vote: directionToVote(String(v.direction ?? v.vote ?? "hold")),
    confidence: Number(v.confidence ?? 0),
    reasoning: v.reasoning ? String(v.reasoning) : undefined,
  }));
}

function mapPosition(raw: Record<string, unknown>): Position {
  const dir = String(raw.type ?? raw.direction ?? "BUY").toUpperCase();
  return {
    id: String(raw.ticket ?? raw.id ?? ""),
    symbol: String(raw.symbol ?? ""),
    direction: dir.includes("SELL") ? "short" : "long",
    size: Number(raw.volume ?? raw.size ?? 0),
    entry: Number(raw.price_open ?? raw.entry ?? 0),
    sl: raw.sl != null ? Number(raw.sl) : null,
    tp: raw.tp != null ? Number(raw.tp) : null,
    unrealized_pnl: Number(raw.profit ?? raw.unrealized_pnl ?? 0),
    opened_at: String(raw.time ?? raw.opened_at ?? ""),
  };
}

export const api = {
  getStatus: () => fetchJson<StatusResponse>("/status"),

  getAccount: () => fetchJson<AccountResponse>("/account"),

  getPositions: async (): Promise<PositionsResponse> => {
    const raw = await fetchJson<{
      positions: Array<Record<string, unknown>>;
      total_exposure?: number;
      total_unrealized_pnl?: number;
    }>("/positions");
    return {
      positions: raw.positions.map(mapPosition),
      total_exposure: raw.total_exposure,
      total_unrealized_pnl: raw.total_unrealized_pnl,
    };
  },

  getTrades: async (params?: { limit?: number; offset?: number; symbol?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set("limit", String(params.limit));
    if (params?.offset != null) search.set("offset", String(params.offset));
    if (params?.symbol) search.set("symbol", params.symbol);
    const qs = search.toString();
    const raw = await fetchJson<{
      trades: Array<Record<string, unknown>>;
      total: number;
      limit: number;
      offset: number;
    }>(`/trades${qs ? `?${qs}` : ""}`);
    return {
      ...raw,
      trades: raw.trades.map((t) => ({
        id: String(t.id ?? ""),
        timestamp: String(t.timestamp ?? ""),
        symbol: String(t.symbol ?? ""),
        direction: String(t.direction ?? ""),
        size: Number(t.size ?? 0),
        entry: Number(t.entry ?? t.price ?? 0),
        exit: t.exit != null ? Number(t.exit) : undefined,
        pnl: t.pnl != null ? Number(t.pnl) : undefined,
        status: String(t.status ?? ""),
        confidence: t.confidence != null ? Number(t.confidence) : undefined,
        agent_votes: mapAgentVotes(t.agent_votes as Array<Record<string, unknown>>),
        reasoning: t.reasoning ? String(t.reasoning) : undefined,
        regime: t.regime ? String(t.regime) : undefined,
        session: t.session ? String(t.session) : undefined,
        slippage: t.slippage != null ? Number(t.slippage) : undefined,
        latency_ms: t.latency_ms != null ? Number(t.latency_ms) : undefined,
      })),
    } satisfies TradesResponse;
  },

  getTrade: async (id: string): Promise<Trade> => {
    const t = await fetchJson<Record<string, unknown>>(`/trades/${id}`);
    return {
      id: String(t.id ?? id),
      timestamp: String(t.timestamp ?? ""),
      symbol: String(t.symbol ?? ""),
      direction: String(t.direction ?? ""),
      size: Number(t.size ?? 0),
      entry: Number(t.entry ?? 0),
      status: String(t.status ?? ""),
      confidence: t.confidence != null ? Number(t.confidence) : undefined,
      agent_votes: mapAgentVotes(t.agent_votes as Array<Record<string, unknown>>),
      reasoning: t.reasoning ? String(t.reasoning) : undefined,
      regime: t.regime ? String(t.regime) : undefined,
      session: t.session ? String(t.session) : undefined,
    };
  },

  getAgents: async (): Promise<AgentStats[]> => {
    const raw = await fetchJson<{ agents: Array<Record<string, unknown>> }>("/agents");
    return raw.agents.map((a) => ({
      agent: String(a.agent ?? ""),
      win_rate: Number(a.win_rate ?? 0),
      avg_r: Number(a.avg_r ?? 0),
      samples: Number(a.sample_size ?? a.samples ?? 0),
    }));
  },

  getLastCycle: async (): Promise<LastCycleResponse> => {
    const raw = await fetchJson<{
      symbols_processed: number;
      decisions: Array<Record<string, unknown>>;
      agent_votes: Array<Record<string, unknown>>;
    }>("/agents/last-cycle");
    return {
      symbols_processed: raw.symbols_processed,
      agent_votes: mapAgentVotes(raw.agent_votes),
      decisions: (raw.decisions ?? []).map((d) => ({
        symbol: String(d.symbol ?? ""),
        action: String(d.direction ?? d.action ?? "HOLD"),
        executed: d.status === "executed" || d.status === "simulated" || Boolean(d.executed),
        reason: String(d.skip_reason ?? d.reason ?? d.reasoning ?? ""),
        features_summary: d.features
          ? `ADX ${(d.features as Record<string, number>).adx?.toFixed?.(1)} · RSI ${(d.features as Record<string, number>).rsi_14?.toFixed?.(1)}`
          : undefined,
        orchestrator_output: d.reasoning ? String(d.reasoning) : undefined,
        agent_votes: mapAgentVotes(d.agent_votes as Array<Record<string, unknown>>),
      })),
    };
  },

  getRisk: async (): Promise<RiskResponse> => {
    const raw = await fetchJson<Record<string, unknown>>("/risk");
    const events = (raw.events as Array<Record<string, unknown>> | undefined) ?? [];
    return {
      dd_tier: (raw.dd_tier as DrawdownTier) ?? "normal",
      drawdown_pct: Number(raw.drawdown_pct ?? 0),
      sharpe: Number(raw.sharpe ?? 0),
      discipline: Number(raw.discipline ?? 100),
      compliance_score: Number(raw.discipline ?? 100),
      margin_state: {
        margin_pct: Number(raw.margin_usage_pct ?? 0) * 100,
        leverage: Number(raw.effective_leverage ?? 0),
        concentration_pct: Number(raw.concentration_pct ?? 0) * 100,
      },
      violations: events.map((e) => ({
        timestamp: String(e.timestamp ?? ""),
        type: String(e.type ?? ""),
        severity: String(e.severity ?? ""),
        message: String(e.message ?? ""),
      })),
    };
  },

  getInstruments: async (): Promise<InstrumentsResponse> => {
    const raw = await fetchJson<{ instruments: Instrument[]; count?: number }>(
      "/instruments",
    );
    return raw;
  },

  getMarketLive: () => fetchJson<MarketLiveResponse>("/market/live"),

  getEquityCurve: async (): Promise<EquityCurveResponse> => {
    const raw = await fetchJson<{ history: EquityPoint[] }>("/equity-curve");
    return { points: raw.history ?? [] };
  },

  getControlState: () => fetchJson<ControlStateResponse>("/control/state"),

  pauseEngine: () => postJson<ControlActionResponse>("/engine/pause"),

  resumeEngine: () => postJson<ControlActionResponse>("/engine/resume"),

  runCycleNow: () => postJson<ControlActionResponse>("/engine/run-cycle"),

  reconnectBridge: () => postJson<ControlActionResponse>("/bridge/reconnect"),

  closePosition: (ticket: string) =>
    postJson<ControlActionResponse>(`/positions/${ticket}/close`),

  closeAllPositions: () =>
    postJson<ControlActionResponse>("/positions/close-all"),

  modifyPosition: (ticket: string, body: { sl?: number; tp?: number }) =>
    patchJson<ControlActionResponse>(`/positions/${ticket}`, body),

  manualTrade: (body: {
    symbol: string;
    direction: "BUY" | "SELL";
    volume: number;
    sl?: number;
    tp?: number;
  }) => postJson<ControlActionResponse>("/trades/manual", body),
};

export const queryKeys = {
  status: ["status"] as const,
  account: ["account"] as const,
  positions: ["positions"] as const,
  trades: (filters?: { symbol?: string; offset?: number }) => ["trades", filters] as const,
  trade: (id: string) => ["trade", id] as const,
  agents: ["agents"] as const,
  lastCycle: ["lastCycle"] as const,
  risk: ["risk"] as const,
  instruments: ["instruments"] as const,
  marketLive: ["marketLive"] as const,
  equityCurve: ["equityCurve"] as const,
  controlState: ["controlState"] as const,
};

export const DRAWDOWN_TIERS: { tier: DrawdownTier; label: string; maxPct: number }[] = [
  { tier: "normal", label: "Normal", maxPct: 5 },
  { tier: "elevated", label: "Elevated", maxPct: 10 },
  { tier: "warning", label: "Warning", maxPct: 12 },
  { tier: "critical", label: "Critical", maxPct: 15 },
  { tier: "emergency", label: "Emergency", maxPct: 15 },
];

export const COMPETITION_WEIGHTS = {
  return: 0.7,
  drawdown: 0.15,
  sharpe: 0.1,
  discipline: 0.05,
};

export const RISK_CAPS = {
  margin: 88,
  leverage: 20,
  concentration: 40,
};
