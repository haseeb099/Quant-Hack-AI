import type { MemoryContextResponse } from "@/lib/copilot";

export type DrawdownTier =
  | "normal"
  | "elevated"
  | "warning"
  | "critical"
  | "emergency";

export interface StatusResponse {
  phase: string;
  mode: string;
  data_source?: "demo" | "simulate" | "live" | string;
  state_age_sec?: number | null;
  state_stale?: boolean;
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
  account_profile?: string | null;
  blocked_symbols?: string[];
}

export interface CompetitionScoreResponse {
  total: number;
  components: Array<{
    label: string;
    weight: number;
    value: number;
    raw: number;
  }>;
}

export type LaunchCheckStatus = "pass" | "warn" | "fail" | "skip";

export interface LaunchReadinessCheck {
  code: string;
  label: string;
  status: LaunchCheckStatus;
  message: string;
  remediation?: string | null;
}

export interface LaunchReadinessResponse {
  ready: boolean;
  mode: string;
  phase: string;
  data_source: string;
  competition_launch_at: string;
  launch_in_seconds: number;
  launched: boolean;
  summary: {
    pass: number;
    warn: number;
    fail: number;
    skip: number;
  };
  checks: LaunchReadinessCheck[];
}

export interface AdaptationPlan {
  phase: string;
  timestamp?: string;
  old_weights: Record<string, number>;
  new_weights: Record<string, number>;
  weight_deltas?: Record<string, number>;
  parameter_overrides?: Record<string, Record<string, number>>;
  regime_boost_overrides?: Record<string, Record<string, number>>;
  promoted: boolean;
  blocked_reason?: string | null;
  agent_health_status?: string;
  agent_audit_summary?: {
    trade_count?: number;
    recommendations?: number;
  };
  walk_forward?: {
    oos_return?: number;
    oos_sharpe?: number;
    oos_max_dd?: number;
    baseline_sharpe?: number;
    sharpe_delta?: number;
    historical_file?: string | null;
    symbol_count?: number;
  };
  semantic_keys?: number;
  trade_count?: number;
}

export interface AdaptationStatusResponse {
  can_run: boolean;
  reason: string;
  scheduled_window_open: boolean;
  local_time_bst: string;
  mode: string;
  engine_running: boolean;
  engine_paused: boolean;
  current_weights: Record<string, number>;
  plan: AdaptationPlan | null;
  plan_exists: boolean;
  last_promoted: boolean;
}

export interface AdaptationRunResponse {
  ok: boolean;
  plan: AdaptationPlan;
  message: string;
}

export type OperatorStepStatus = "pass" | "warn" | "fail" | "manual";

export interface OperatorRunbookStep {
  id: string;
  label: string;
  check: string;
  status: OperatorStepStatus;
  detail: string;
}

export interface OperatorRunbookPhase {
  id: string;
  title: string;
  steps: OperatorRunbookStep[];
  summary: { pass: number; total: number };
}

export interface PreflightCheck {
  code: string;
  label: string;
  passed: boolean;
  detail: string;
  remediation?: string;
}

export interface PreflightResponse {
  passed: number;
  total: number;
  ready: boolean;
  checks: PreflightCheck[];
}

export interface OperatorRunbookResponse {
  timestamp_bst: string;
  phase: string;
  mode: string;
  preflight: PreflightResponse;
  launch_readiness: boolean;
  phases: OperatorRunbookPhase[];
}

export type OperatorSnapshotStatus = "GREEN" | "YELLOW" | "RED" | "UNKNOWN";

export interface OperatorIssue {
  code: string;
  label: string;
  severity: string;
  passed: boolean;
  detail: string;
  remediation?: string;
}

export interface OperatorSnapshot {
  timestamp: string;
  status: OperatorSnapshotStatus;
  dashboard_url?: string;
  reconciliation?: {
    status: OperatorSnapshotStatus;
    issues: OperatorIssue[];
    summary?: Record<string, unknown>;
  };
  risk_compliance?: {
    status: OperatorSnapshotStatus;
    issues: OperatorIssue[];
  };
  mt5_checks?: {
    passed: number;
    total: number;
    ready: boolean;
    checks: PreflightCheck[];
  };
  mt5_log?: {
    available: boolean;
    error_count: number;
    status: string;
    detail?: string;
  };
  summary?: Record<string, unknown>;
}

export interface OperatorSnapshotResponse {
  available: boolean;
  snapshot: OperatorSnapshot | null;
}

export interface OperatorSnapshotHistoryResponse {
  count: number;
  history: OperatorSnapshot[];
}

export interface OperatorWatchdogTriggerResponse {
  ok: boolean;
  snapshot: OperatorSnapshot;
}

export interface NorthflankService {
  name: string;
  dockerfile: string;
  ready: boolean;
  volume_mounts: string[];
  public: boolean;
  port?: number;
}

export interface NorthflankDeployResponse {
  platform: string;
  services: NorthflankService[];
  env_configured: Record<string, boolean>;
  smoke_commands: string[];
  docs: string;
  preflight: PreflightResponse;
}

export type WalkthroughStepStatus = "pass" | "warn" | "fail" | "manual";

export interface DemoWalkthroughStep {
  id: string;
  order: number;
  title: string;
  duration_sec: number;
  narration: string;
  dashboard_route: string | null;
  doc_path: string | null;
  command: string | null;
  check: string;
  status: WalkthroughStepStatus;
  detail: string;
  doc_available: boolean;
}

export interface DemoWalkthroughResponse {
  title: string;
  audience: string;
  duration_sec: number;
  duration_label: string;
  closing_line: string;
  steps: DemoWalkthroughStep[];
  summary: { pass: number; total: number; ready: boolean };
  docs: string;
}

export type PrizeCheckStatus = "pass" | "warn" | "fail" | "skip";

export interface TechnologyPrizeCheck {
  code: string;
  sponsor: string;
  label: string;
  status: PrizeCheckStatus;
  message: string;
  file_path: string | null;
  remediation?: string | null;
}

export interface TechnologyPrizeResponse {
  ready: boolean;
  summary: { pass: number; warn: number; fail: number; skip: number };
  checks: TechnologyPrizeCheck[];
  docs: string;
  notion_doc: string;
}

export interface CompetitionSession {
  phase: string;
  label: string;
  local_time_bst: string;
  launch_at_bst: string;
  seconds_to_launch: number;
  launched: boolean;
}

export interface VerificationCheck {
  code: string;
  label: string;
  passed: boolean;
  detail: string;
  remediation?: string;
}

export interface OperatorVerificationResponse {
  last_run_at: string | null;
  last_mode: string | null;
  ready: boolean;
  passed: number;
  total: number;
  checks: VerificationCheck[];
  session: CompetitionSession | null;
  has_run: boolean;
}

export interface OperatorVerificationRunResponse extends OperatorVerificationResponse {
  ok: boolean;
  mode: string;
  launch_readiness?: boolean;
}

export interface NotionSyncChannelStats {
  success?: number;
  failure?: number;
  last_at?: string | null;
  last_error?: string | null;
}

export interface NotionStatusResponse {
  enabled: boolean;
  notion_sync_enabled?: boolean;
  api_key_set: boolean;
  databases: {
    trade_journal: boolean;
    agent_performance: boolean;
    risk_events: boolean;
    tasks: boolean;
  };
  sync_stats: Record<string, NotionSyncChannelStats>;
}

export interface NotionTask {
  id: string;
  title: string;
  status: string;
  step: number | null;
  url?: string | null;
}

export interface NotionTasksResponse {
  tasks: NotionTask[];
  enabled: boolean;
  count?: number;
  message?: string;
}

export interface EngineHealthResponse {
  data_source: string;
  state_stale: boolean;
  state_age_sec?: number | null;
  engine_running: boolean;
  engine_paused: boolean;
  cycle_in_progress: boolean;
  mode: string;
  mt5_connected: boolean;
  zmq_last_error?: string | null;
  last_cycle_at?: string | null;
  next_cycle_at?: string | null;
  last_tick_at?: string | null;
  last_tick_age_ms?: number | null;
  dd_tier?: string;
  drawdown_pct?: number;
  discipline?: number;
  account_profile?: string | null;
  risk_events?: RiskEvent[];
}

export interface AgentAttribution {
  agent: string;
  label: string;
  trades: number;
  win_rate: number;
  avg_r: number;
  symbols: string[];
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
  risk_check?: TradeCheckResponse;
}

export interface RiskBlocker {
  code: string;
  severity: "critical" | "warning" | "info" | string;
  message: string;
  discipline_risk?: number | null;
  penalty_in_min?: number | null;
}

export interface TradeCheckResponse {
  allowed: boolean;
  blockers: RiskBlocker[];
  warnings: RiskBlocker[];
  remediation: string[];
  projected: Record<string, unknown>;
}

export class TradeBlockedError extends Error {
  check: TradeCheckResponse;

  constructor(check: TradeCheckResponse) {
    super(
      check.blockers.map((b) => b.message).join(" · ") || "Trade blocked by risk rules",
    );
    this.name = "TradeBlockedError";
    this.check = check;
  }
}

export interface AccountResponse {
  equity: number;
  balance: number | null;
  margin: number;
  free_margin: number | null;
  gross_exposure: number;
  daily_pnl?: number | null;
  return_pct?: number;
  account_stale?: boolean;
  equity_available?: boolean;
  initial_equity?: number;
  margin_level?: number | null;
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
  notional?: number;
  contract_size?: number;
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
  win_rate: number | null;
  avg_r: number;
  samples: number;
}

export interface AgentHealthAgentReport {
  active: boolean;
  symbols_firing?: number;
  symbols_tested?: number;
  fixture_fired?: boolean;
  issue?: string | null;
}

export interface AgentHealthResponse {
  status: "GREEN" | "YELLOW" | "RED" | string;
  timestamp?: string;
  agents: Record<string, AgentHealthAgentReport>;
  red_agents?: string[];
  error?: string;
}

export interface AgentAuditRecommendation {
  agent: string;
  regime: string;
  sample_size: number;
  win_rate: number;
  recommendation: string;
  severity: string;
}

export interface AgentAuditAgentMetrics {
  agent: string;
  sample_size: number;
  win_rate: number | null;
  avg_r: number;
  by_regime?: Record<string, { sample_size: number; win_rate: number | null; avg_r: number }>;
  attribution?: { win_rate: number | null; avg_r: number; sample_size: number };
}

export interface AgentAuditResponse {
  timestamp?: string;
  trade_count: number;
  semantic_keys?: number;
  agents: Record<string, AgentAuditAgentMetrics>;
  recommendations: AgentAuditRecommendation[];
  skip_reasons?: Record<string, number>;
  error?: string;
}

export interface AgentTunedConfigResponse {
  exists: boolean;
  path: string;
  yaml: string | null;
  plan: AdaptationPlan | null;
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
  symbols_attempted: number;
  decisions: CycleDecision[];
  agent_votes: AgentVote[];
  skip_summary?: Record<string, number>;
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
  margin_level_pct?: number | null;
  net_directional_pct?: number;
  action?: string;
}

export interface RiskTiers {
  normal_max: number;
  elevated_max: number;
  warning_max: number;
  critical_max: number;
  emergency_close: number;
}

export interface RiskCaps {
  margin_emergency_pct: number;
  leverage_max: number;
  concentration_max_pct: number;
  net_directional_cap: number;
  stop_out_level_pct: number;
}

export interface RiskEvent {
  timestamp: string;
  type: string;
  severity: string;
  message: string;
}

export interface RiskResponse {
  dd_tier: DrawdownTier;
  drawdown_pct: number;
  sharpe: number;
  discipline: number;
  margin_state: MarginState;
  violations?: RiskViolation[];
  compliance_score?: number;
  tiers?: RiskTiers;
  caps?: RiskCaps;
  events?: RiskEvent[];
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
  sentiment_score?: number | null;
  sentiment_confidence?: number | null;
  sentiment_summary?: string | null;
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

export function getApiAuthHeaders(contentType = "application/json"): Record<string, string> {
  const token = import.meta.env.VITE_DASHBOARD_AUTH_TOKEN as string | undefined;
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": contentType,
  };
  if (token?.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

function authHeaders(): HeadersInit {
  return getApiAuthHeaders();
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
  const flat: AgentVote[] = [];
  for (const item of raw ?? []) {
    const nested = item.votes;
    if (Array.isArray(nested)) {
      const symbol = item.symbol ? String(item.symbol) : undefined;
      for (const vote of nested) {
        const v = vote as Record<string, unknown>;
        flat.push({
          agent: String(v.agent ?? ""),
          symbol,
          vote: directionToVote(String(v.direction ?? v.vote ?? "hold")),
          confidence: Number(v.confidence ?? 0),
          reasoning: v.reasoning ? String(v.reasoning) : undefined,
        });
      }
      continue;
    }
    flat.push({
      agent: String(item.agent ?? ""),
      symbol: item.symbol ? String(item.symbol) : undefined,
      vote: directionToVote(String(item.direction ?? item.vote ?? "hold")),
      confidence: Number(item.confidence ?? 0),
      reasoning: item.reasoning ? String(item.reasoning) : undefined,
    });
  }
  return flat;
}

export function mapRiskViolations(
  raw: unknown,
  fallbackEvents?: Array<Record<string, unknown>>,
): RiskViolation[] {
  const source =
    Array.isArray(raw) && raw.length > 0 ? raw : (fallbackEvents ?? []);
  return source.map((item) => {
    if (typeof item === "string") {
      return {
        timestamp: "",
        type: item,
        severity: "warning",
        message: item.replace(/_/g, " "),
      };
    }
    const e = item as Record<string, unknown>;
    return {
      timestamp: String(e.timestamp ?? ""),
      type: String(e.type ?? e.code ?? ""),
      severity: String(e.severity ?? "warning"),
      message: String(e.message ?? e.type ?? ""),
    };
  });
}

export function mapLastCycleResponse(raw: {
  symbols_processed?: number;
  symbols_attempted?: number;
  decisions?: Array<Record<string, unknown>>;
  agent_votes?: Array<Record<string, unknown>>;
  skip_summary?: Record<string, number>;
}): LastCycleResponse {
  return {
    symbols_processed: Number(raw.symbols_processed ?? 0),
    symbols_attempted: Number(raw.symbols_attempted ?? raw.symbols_processed ?? 0),
    agent_votes: mapAgentVotes(raw.agent_votes),
    skip_summary: raw.skip_summary,
    decisions: (raw.decisions ?? []).map((d) => ({
      symbol: String(d.symbol ?? ""),
      action: String(d.direction ?? d.action ?? "HOLD"),
      executed:
        d.status === "executed" || d.status === "simulated" || Boolean(d.executed),
      reason: String(d.skip_reason ?? d.reason ?? d.reasoning ?? ""),
      features_summary: d.features
        ? `ADX ${(d.features as Record<string, number>).adx?.toFixed?.(1)} · RSI ${(d.features as Record<string, number>).rsi_14?.toFixed?.(1)}`
        : undefined,
      orchestrator_output: d.reasoning ? String(d.reasoning) : undefined,
      agent_votes: mapAgentVotes(d.agent_votes as Array<Record<string, unknown>>),
    })),
  };
}

export function positionNotional(raw: Record<string, unknown> | Position): number {
  if ("notional" in raw && raw.notional != null) {
    return Math.abs(Number(raw.notional));
  }
  const size = Number("size" in raw ? raw.size : raw.volume ?? 0);
  const entry = Number("entry" in raw ? raw.entry : raw.price_open ?? 0);
  const contract = Number(
    "contract_size" in raw ? raw.contract_size : raw.contract_size ?? 1,
  );
  return Math.abs(size * contract * entry);
}

function mapPosition(raw: Record<string, unknown>): Position {
  const dir = String(raw.type ?? raw.direction ?? "BUY").toUpperCase();
  const size = Number(raw.volume ?? raw.size ?? 0);
  const entry = Number(raw.price_open ?? raw.entry ?? 0);
  const contractSize =
    raw.contract_size != null ? Number(raw.contract_size) : undefined;
  const notional =
    raw.notional != null ? Math.abs(Number(raw.notional)) : positionNotional(raw);
  return {
    id: String(raw.ticket ?? raw.id ?? ""),
    symbol: String(raw.symbol ?? ""),
    direction: dir.includes("SELL") ? "short" : "long",
    size,
    entry,
    sl: raw.sl != null ? Number(raw.sl) : null,
    tp: raw.tp != null ? Number(raw.tp) : null,
    unrealized_pnl: Number(raw.profit ?? raw.unrealized_pnl ?? 0),
    opened_at: String(raw.time ?? raw.opened_at ?? ""),
    notional,
    contract_size: contractSize,
  };
}

function mapRiskTiers(raw: unknown): RiskTiers | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const t = raw as Record<string, unknown>;
  return {
    normal_max: Number(t.normal_max ?? 0.05),
    elevated_max: Number(t.elevated_max ?? 0.1),
    warning_max: Number(t.warning_max ?? 0.12),
    critical_max: Number(t.critical_max ?? 0.14),
    emergency_close: Number(t.emergency_close ?? 0.15),
  };
}

function mapRiskCaps(raw: unknown): RiskCaps | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const c = raw as Record<string, unknown>;
  return {
    margin_emergency_pct: Number(c.margin_emergency_pct ?? 0.88),
    leverage_max: Number(c.leverage_max ?? 20),
    concentration_max_pct: Number(c.concentration_max_pct ?? 0.4),
    net_directional_cap: Number(c.net_directional_cap ?? 0.85),
    stop_out_level_pct: Number(c.stop_out_level_pct ?? 30),
  };
}

function mapRiskEvents(raw: unknown): RiskEvent[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const e = item as Record<string, unknown>;
    return {
      timestamp: String(e.timestamp ?? ""),
      type: String(e.type ?? e.code ?? ""),
      severity: String(e.severity ?? "warning"),
      message: String(e.message ?? e.type ?? ""),
    };
  });
}

export function mapRiskResponse(raw: Record<string, unknown>): RiskResponse {
  const margin = raw.margin as Record<string, unknown> | undefined;
  const events = mapRiskEvents(raw.events);
  return {
    dd_tier: (raw.dd_tier as DrawdownTier) ?? "normal",
    drawdown_pct: Number(raw.drawdown_pct ?? 0) * 100,
    sharpe: Number(raw.sharpe ?? 0),
    discipline: Number(raw.discipline ?? 100),
    compliance_score: Number(raw.compliance_score ?? raw.discipline ?? 100),
    margin_state: {
      margin_pct: Number(margin?.margin_usage_pct ?? raw.margin_usage_pct ?? 0) * 100,
      leverage: Number(margin?.effective_leverage ?? raw.effective_leverage ?? 0),
      concentration_pct:
        Number(margin?.concentration_pct ?? raw.concentration_pct ?? 0) * 100,
      margin_level_pct:
        margin?.margin_level_pct != null
          ? Number(margin.margin_level_pct)
          : raw.margin_level_pct != null
            ? Number(raw.margin_level_pct)
            : null,
      net_directional_pct:
        Number(margin?.net_directional_pct ?? raw.net_directional_pct ?? 0) * 100,
      action: String(
        margin?.action ?? raw.margin_state ?? raw.margin_action ?? "",
      ) || undefined,
    },
    violations: mapRiskViolations(
      raw.violations,
      raw.events as Array<Record<string, unknown>> | undefined,
    ),
    tiers: mapRiskTiers(raw.tiers),
    caps: mapRiskCaps(raw.caps),
    events,
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

  getTrades: async (params?: {
    limit?: number;
    offset?: number;
    symbol?: string;
    status?: string;
  }) => {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set("limit", String(params.limit));
    if (params?.offset != null) search.set("offset", String(params.offset));
    if (params?.symbol) search.set("symbol", params.symbol);
    if (params?.status) search.set("status", params.status);
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
      win_rate: a.win_rate == null ? null : Number(a.win_rate),
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
    return mapLastCycleResponse(raw);
  },

  getRisk: async (): Promise<RiskResponse> => {
    const raw = await fetchJson<Record<string, unknown>>("/risk");
    return mapRiskResponse(raw);
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

  getCompetitionScore: () => fetchJson<CompetitionScoreResponse>("/competition-score"),

  getLaunchReadiness: () =>
    fetchJson<LaunchReadinessResponse>("/competition/launch-readiness"),

  getEngineHealth: () => fetchJson<EngineHealthResponse>("/health/engine"),

  getIntegrations: () => fetchJson<Record<string, unknown>>("/integrations"),

  getNotionStatus: () => fetchJson<NotionStatusResponse>("/notion/status"),

  getNotionTasks: (limit = 30) =>
    fetchJson<NotionTasksResponse>(`/notion/tasks?limit=${limit}`),

  getOperatorRunbook: () => fetchJson<OperatorRunbookResponse>("/operator/runbook"),

  getOperatorPreflight: (zmqOnly = true, withCycle = false) =>
    fetchJson<PreflightResponse>(
      `/operator/preflight?zmq_only=${zmqOnly}&with_cycle=${withCycle}`,
    ),

  getOperatorSnapshot: () =>
    fetchJson<OperatorSnapshotResponse>("/operator/snapshot"),

  getOperatorSnapshotHistory: (limit = 50) =>
    fetchJson<OperatorSnapshotHistoryResponse>(
      `/operator/snapshot/history?limit=${limit}`,
    ),

  triggerOperatorWatchdog: (body: { confirm: boolean; zmq_only?: boolean }) =>
    postJson<OperatorWatchdogTriggerResponse>("/operator/watchdog/trigger", body),

  getNorthflankDeploy: () => fetchJson<NorthflankDeployResponse>("/deploy/northflank"),

  getDemoWalkthrough: () => fetchJson<DemoWalkthroughResponse>("/demo/walkthrough"),

  getTechnologyPrizeChecklist: () =>
    fetchJson<TechnologyPrizeResponse>("/prize/technology-checklist"),

  getOperatorVerification: () =>
    fetchJson<OperatorVerificationResponse>("/operator/verification"),

  runOperatorVerification: (body: { confirm: boolean; quick?: boolean }) =>
    postJson<OperatorVerificationRunResponse>("/operator/verification/run", body),

  getAgentAttribution: () =>
    fetchJson<{ attribution: AgentAttribution[]; total_closed_trades: number }>(
      "/agents/attribution",
    ),

  getAgentHealth: () => fetchJson<AgentHealthResponse>("/agents/health"),

  getAgentAudit: () => fetchJson<AgentAuditResponse>("/agents/audit"),

  getAgentTunedConfig: () => fetchJson<AgentTunedConfigResponse>("/agents/tuned-config"),

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

  manualTrade: async (body: {
    symbol: string;
    direction: "BUY" | "SELL";
    volume: number;
    sl?: number;
    tp?: number;
  }) => {
    const res = await fetch(`${API_BASE}/trades/manual`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => ({}))) as ControlActionResponse & {
      detail?: TradeCheckResponse & { message?: string };
    };
    if (res.status === 422 && data.detail && Array.isArray(data.detail.blockers)) {
      throw new TradeBlockedError(data.detail);
    }
    if (!res.ok) {
      const msg =
        typeof data.detail === "string"
          ? data.detail
          : data.detail?.message || `API /trades/manual failed: ${res.status}`;
      throw new Error(msg);
    }
    return data;
  },

  checkTrade: (params: {
    symbol: string;
    direction: "BUY" | "SELL";
    volume: number;
    sl?: number;
    tp?: number;
    price?: number;
  }) => {
    const search = new URLSearchParams({
      symbol: params.symbol,
      direction: params.direction,
      volume: String(params.volume),
    });
    if (params.sl != null) search.set("sl", String(params.sl));
    if (params.tp != null) search.set("tp", String(params.tp));
    if (params.price != null) search.set("price", String(params.price));
    return fetchJson<TradeCheckResponse>(`/risk/check-trade?${search.toString()}`);
  },

  getMemoryContext: (symbol?: string) => {
    const qs = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
    return fetchJson<MemoryContextResponse>(`/memory/context${qs}`);
  },

  getWorkingMemory: () =>
    fetchJson<{
      trades: MemoryContextResponse["working_memory"];
      count: number;
      capacity: number;
    }>("/memory/working"),

  getAdaptationStatus: () => fetchJson<AdaptationStatusResponse>("/adaptation/status"),

  getAdaptationPlan: () => fetchJson<{ plan: AdaptationPlan | null; exists: boolean }>("/adaptation/plan"),

  runAdaptation: (body: { confirm: boolean; phase?: string; data_dir?: string }) =>
    postJson<AdaptationRunResponse>("/adaptation/run", body),

  getIntelligenceSnapshot: () =>
    fetchJson<{
      enabled: boolean;
      refresh_ok?: boolean;
      macro?: { bias: string; usd_strength: string; fear_greed?: number; notes?: string };
      upcoming_events?: Array<{
        name: string;
        currency: string;
        impact: string;
        scheduled_at: string;
      }>;
      sentiment?: Record<
        string,
        {
          score: number;
          confidence: number;
          headline_count: number;
          summary: string;
        }
      >;
    }>("/intelligence/snapshot"),

  getIntelligenceCalendar: (hours = 8) =>
    fetchJson<{ events: Array<{ name: string; currency: string; impact: string; scheduled_at: string }>; enabled: boolean }>(
      `/intelligence/calendar?hours=${hours}`,
    ),
};

export const queryKeys = {
  status: ["status"] as const,
  account: ["account"] as const,
  positions: ["positions"] as const,
  trades: (filters?: { symbol?: string; offset?: number; status?: string }) =>
    ["trades", filters] as const,
  trade: (id: string) => ["trade", id] as const,
  agents: ["agents"] as const,
  lastCycle: ["lastCycle"] as const,
  risk: ["risk"] as const,
  instruments: ["instruments"] as const,
  marketLive: ["marketLive"] as const,
  equityCurve: ["equityCurve"] as const,
  competitionScore: ["competitionScore"] as const,
  launchReadiness: ["launchReadiness"] as const,
  adaptationStatus: ["adaptationStatus"] as const,
  notionStatus: ["notionStatus"] as const,
  notionTasks: ["notionTasks"] as const,
  operatorRunbook: ["operatorRunbook"] as const,
  operatorSnapshot: ["operatorSnapshot"] as const,
  operatorSnapshotHistory: ["operatorSnapshotHistory"] as const,
  demoWalkthrough: ["demoWalkthrough"] as const,
  technologyPrize: ["technologyPrize"] as const,
  operatorVerification: ["operatorVerification"] as const,
  northflankDeploy: ["northflankDeploy"] as const,
  engineHealth: ["engineHealth"] as const,
  agentAttribution: ["agentAttribution"] as const,
  agentHealth: ["agentHealth"] as const,
  agentAudit: ["agentAudit"] as const,
  agentTunedConfig: ["agentTunedConfig"] as const,
  controlState: ["controlState"] as const,
  tradeCheck: (params: {
    symbol: string;
    direction: string;
    volume: number;
  }) => ["tradeCheck", params] as const,
  memoryContext: (symbol?: string) => ["memoryContext", symbol] as const,
  intelligence: ["intelligence"] as const,
  intelligenceCalendar: ["intelligenceCalendar"] as const,
};

export const DRAWDOWN_TIERS: { tier: DrawdownTier; label: string; maxPct: number }[] = [
  { tier: "normal", label: "Normal", maxPct: 5 },
  { tier: "elevated", label: "Elevated", maxPct: 10 },
  { tier: "warning", label: "Warning", maxPct: 12 },
  { tier: "critical", label: "Critical", maxPct: 14 },
  { tier: "emergency", label: "Emergency", maxPct: 15 },
];

export function resolveDrawdownTiers(
  risk?: RiskResponse,
): { tier: DrawdownTier; label: string; maxPct: number }[] {
  if (!risk?.tiers) return DRAWDOWN_TIERS;
  const t = risk.tiers;
  return [
    { tier: "normal", label: "Normal", maxPct: t.normal_max * 100 },
    { tier: "elevated", label: "Elevated", maxPct: t.elevated_max * 100 },
    { tier: "warning", label: "Warning", maxPct: t.warning_max * 100 },
    { tier: "critical", label: "Critical", maxPct: t.critical_max * 100 },
    { tier: "emergency", label: "Emergency", maxPct: t.emergency_close * 100 },
  ];
}

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
  netDirectional: 85,
  stopOut: 30,
};

export function resolveRiskCaps(risk?: RiskResponse) {
  if (!risk?.caps) return RISK_CAPS;
  return {
    margin: risk.caps.margin_emergency_pct * 100,
    leverage: risk.caps.leverage_max,
    concentration: risk.caps.concentration_max_pct * 100,
    netDirectional: risk.caps.net_directional_cap * 100,
    stopOut: risk.caps.stop_out_level_pct,
  };
}
