import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { WSMessage } from "@/lib/api";
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

const INVALIDATE_TYPES: Record<string, readonly (readonly unknown[])[]> = {
  status: [queryKeys.status, queryKeys.account],
  account: [queryKeys.account],
  positions: [queryKeys.positions],
  trades: [queryKeys.trades()],
  agents: [queryKeys.agents, queryKeys.lastCycle],
  risk: [queryKeys.risk],
  instruments: [queryKeys.instruments],
  equity: [queryKeys.equityCurve],
  cycle: [
    queryKeys.status,
    queryKeys.lastCycle,
    queryKeys.positions,
    queryKeys.risk,
  ],
  state: [
    queryKeys.status,
    queryKeys.account,
    queryKeys.positions,
    queryKeys.risk,
    queryKeys.equityCurve,
    queryKeys.lastCycle,
  ],
};

export function useLiveWebSocket() {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const invalidateForType = useCallback(
    (type: string) => {
      const keys = INVALIDATE_TYPES[type] ?? INVALIDATE_TYPES.state;
      keys.forEach((key) => {
        queryClient.invalidateQueries({ queryKey: key });
      });
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
          setLastMessage(msg);
          invalidateForType(msg.type);
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
  }, [invalidateForType]);

  return { connected, lastMessage };
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
