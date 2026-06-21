import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type {
  Instrument,
  InstrumentsResponse,
  LastCycleResponse,
  PositionsResponse,
  Position,
  RiskResponse,
  RuntimeStatePayload,
  StatusResponse,
  TicksPayload,
  MarketAlertPayload,
  WSMessage,
} from "@/lib/api";
import { queryKeys } from "@/lib/api";

function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = import.meta.env.VITE_DASHBOARD_AUTH_TOKEN as string | undefined;
  const base = `${protocol}//${window.location.host}/ws/live`;
  if (token?.trim()) {
    return `${base}?token=${encodeURIComponent(token.trim())}`;
  }
  return base;
}

function mapRiskPayload(raw: Record<string, unknown>): RiskResponse {
  const margin = raw.margin as Record<string, unknown> | undefined;
  const events = (raw.events as Array<Record<string, unknown>> | undefined) ?? [];
  return {
    dd_tier: (raw.dd_tier as RiskResponse["dd_tier"]) ?? "normal",
    drawdown_pct: Number(raw.drawdown_pct ?? 0),
    sharpe: Number(raw.sharpe ?? 0),
    discipline: Number(raw.discipline ?? 100),
    compliance_score: Number(raw.discipline ?? 100),
    margin_state: {
      margin_pct: Number(
        margin?.margin_usage_pct ?? raw.margin_usage_pct ?? 0,
      ) * 100,
      leverage: Number(
        margin?.effective_leverage ?? raw.effective_leverage ?? 0,
      ),
      concentration_pct: Number(
        margin?.concentration_pct ?? raw.concentration_pct ?? 0,
      ) * 100,
    },
    violations: events.map((e) => ({
      timestamp: String(e.timestamp ?? ""),
      type: String(e.type ?? ""),
      severity: String(e.severity ?? ""),
      message: String(e.message ?? ""),
    })),
  };
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

function applyStatePayload(
  queryClient: ReturnType<typeof useQueryClient>,
  payload: RuntimeStatePayload,
) {
  if (payload.phase !== undefined || payload.mode !== undefined) {
    queryClient.setQueryData<StatusResponse>(queryKeys.status, (prev) => ({
      phase: payload.phase ?? prev?.phase ?? "round1",
      mode: payload.mode ?? prev?.mode ?? "simulate",
      last_cycle_at: payload.last_cycle_at ?? prev?.last_cycle_at ?? null,
      next_cycle_at: payload.next_cycle_at ?? prev?.next_cycle_at ?? null,
      connected: payload.connected ?? prev?.connected ?? false,
      engine_running: payload.engine_running ?? prev?.engine_running,
      engine_paused: payload.engine_paused ?? prev?.engine_paused,
      cycle_in_progress: payload.cycle_in_progress ?? prev?.cycle_in_progress,
      mt5_connected: payload.mt5_connected ?? prev?.mt5_connected,
      zmq_last_error: payload.zmq_last_error ?? prev?.zmq_last_error,
      timestamp: payload.timestamp ?? prev?.timestamp,
      last_tick_at: payload.market?.last_tick_at ?? prev?.last_tick_at ?? null,
      last_tick_age_ms:
        payload.market?.last_tick_age_ms ?? prev?.last_tick_age_ms ?? null,
    }));
  }

  if (payload.account) {
    const equity = Number(payload.account.equity ?? 0);
    const initial = Number(payload.account.initial_equity ?? equity);
    queryClient.setQueryData(queryKeys.account, {
      ...payload.account,
      return_pct: initial ? ((equity - initial) / initial) * 100 : 0,
      daily_pnl: equity - Number(payload.account.balance ?? equity),
    });
  }

  if (payload.positions) {
    const positions = payload.positions.map((p) =>
      mapPosition(p as Record<string, unknown>),
    );
    const totalPnl = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
    const totalExposure = positions.reduce(
      (sum, p) => sum + Math.abs(p.size * p.entry),
      0,
    );
    queryClient.setQueryData<PositionsResponse>(queryKeys.positions, {
      positions,
      total_unrealized_pnl: totalPnl,
      total_exposure: totalExposure,
    });
  }

  if (payload.risk) {
    queryClient.setQueryData(
      queryKeys.risk,
      mapRiskPayload(payload.risk as Record<string, unknown>),
    );
  }

  if (payload.equity_history?.length) {
    queryClient.setQueryData(queryKeys.equityCurve, {
      points: payload.equity_history,
    });
  }

  if (payload.last_cycle) {
    queryClient.setQueryData<LastCycleResponse>(
      queryKeys.lastCycle,
      payload.last_cycle,
    );
  }

  if (payload.instruments) {
    queryClient.setQueryData<InstrumentsResponse>(
      queryKeys.instruments,
      (prev) => {
        const base = prev?.instruments ?? [];
        const merged = base.map((inst) => ({
          ...inst,
          ...(payload.instruments?.[inst.symbol] as Partial<Instrument>),
        }));
        return { instruments: merged, count: merged.length };
      },
    );
  }

  if (payload.market) {
    queryClient.setQueryData(queryKeys.marketLive, (prev: unknown) => ({
      ...(typeof prev === "object" && prev ? prev : {}),
      last_tick_at: payload.market?.last_tick_at ?? null,
      last_tick_age_ms: payload.market?.last_tick_age_ms ?? null,
    }));
  }
}

function applyTicksPayload(
  queryClient: ReturnType<typeof useQueryClient>,
  payload: TicksPayload,
) {
  queryClient.setQueryData(queryKeys.marketLive, payload);

  queryClient.setQueryData<StatusResponse>(queryKeys.status, (prev) =>
    prev
      ? {
          ...prev,
          last_tick_at: payload.last_tick_at,
          last_tick_age_ms: payload.last_tick_age_ms,
        }
      : prev,
  );

  queryClient.setQueryData<InstrumentsResponse>(
    queryKeys.instruments,
    (prev) => {
      const base = prev?.instruments ?? [];
      const merged = base.map((inst) => {
        const live = payload.instruments[inst.symbol];
        if (!live) return inst;
        return {
          ...inst,
          bid: live.bid != null ? Number(live.bid) : inst.bid,
          ask: live.ask != null ? Number(live.ask) : inst.ask,
          mid: live.mid != null ? Number(live.mid) : inst.mid,
          spread: live.spread != null ? Number(live.spread) : inst.spread,
          change_pct:
            live.change_pct != null ? Number(live.change_pct) : inst.change_pct,
          tick_age_ms:
            live.tick_age_ms != null
              ? Number(live.tick_age_ms)
              : inst.tick_age_ms,
          market_health:
            (live.market_health as Instrument["market_health"]) ??
            inst.market_health,
          bar_age_sec:
            live.bar_age_sec != null
              ? Number(live.bar_age_sec)
              : inst.bar_age_sec,
        };
      });
      return { instruments: merged, count: merged.length };
    },
  );
}

export function useLiveWebSocket() {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [lastAlert, setLastAlert] = useState<MarketAlertPayload | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      setLastMessage(msg);
      switch (msg.type) {
        case "state":
          applyStatePayload(queryClient, msg.payload as RuntimeStatePayload);
          break;
        case "ticks":
          applyTicksPayload(queryClient, msg.payload as TicksPayload);
          break;
        case "market_alert":
          setLastAlert(msg.payload as MarketAlertPayload);
          break;
        default:
          break;
      }
    },
    [queryClient],
  );

  useEffect(() => {
    let mounted = true;

    function connect() {
      if (!mounted) return;

      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mounted) return;
        setConnected(true);
      };

      ws.onclose = () => {
        if (!mounted) return;
        setConnected(false);
        wsRef.current = null;
        retryRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };

      ws.onmessage = (event) => {
        if (!mounted) return;
        try {
          const msg = JSON.parse(event.data as string) as WSMessage;
          handleMessage(msg);
        } catch {
          // ignore malformed messages
        }
      };
    }

    connect();

    return () => {
      mounted = false;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [handleMessage]);

  return { connected, lastMessage, lastAlert };
}

export function useCycleCountdown(nextCycleAt: string | null | undefined) {
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    if (!nextCycleAt) {
      setSecondsLeft(0);
      return;
    }

    function tick() {
      const diff = Math.max(
        0,
        Math.floor((new Date(nextCycleAt!).getTime() - Date.now()) / 1000),
      );
      setSecondsLeft(diff);
    }

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [nextCycleAt]);

  return secondsLeft;
}

export function useLastTickAge(lastTickAgeMs?: number | null) {
  const [displaySec, setDisplaySec] = useState<number | null>(null);

  useEffect(() => {
    if (lastTickAgeMs == null) {
      setDisplaySec(null);
      return;
    }

    const start = Date.now() - lastTickAgeMs;
    function tick() {
      setDisplaySec(Math.max(0, (Date.now() - start) / 1000));
    }
    tick();
    const id = setInterval(tick, 200);
    return () => clearInterval(id);
  }, [lastTickAgeMs]);

  return displaySec;
}
