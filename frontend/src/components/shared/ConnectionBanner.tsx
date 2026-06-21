import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";
import type { MarketAlertPayload, StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ConnectionBannerProps {
  status?: StatusResponse;
  wsConnected: boolean;
  marketAlert?: MarketAlertPayload | null;
}

const STALE_TICK_MS = 5000;

export function ConnectionBanner({
  status,
  wsConnected,
  marketAlert,
}: ConnectionBannerProps) {
  const [dismissedAlert, setDismissedAlert] = useState(false);
  const issues: string[] = [];

  const isLive = status?.mode === "live";

  if (!wsConnected) issues.push("WebSocket disconnected");
  if (status && status.engine_running === false) {
    issues.push("Trading engine not running");
  }
  if (status?.engine_paused) {
    issues.push("Engine paused — no new entries");
  }
  if (isLive && status?.engine_running && status.mt5_connected === false) {
    issues.push("MT5 / ZeroMQ bridge offline");
  }
  if (
    isLive &&
    status?.engine_running &&
    status.last_tick_age_ms != null &&
    status.last_tick_age_ms > STALE_TICK_MS
  ) {
    issues.push(
      `Stale market data (${(status.last_tick_age_ms / 1000).toFixed(1)}s since last tick)`,
    );
  }

  const zmqOffline =
    isLive && status?.engine_running && status.mt5_connected === false;
  const zmqError = status?.zmq_last_error?.trim();
  const showAlert = marketAlert && !dismissedAlert;

  if (issues.length === 0 && !showAlert) return null;

  return (
    <div className="flex flex-col gap-0 border-b border-border">
      {issues.length > 0 && (
        <div
          className={cn(
            "flex flex-col gap-1 border-b border-destructive/40 bg-destructive/10 px-6 py-2 text-sm text-destructive",
          )}
          role="alert"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle className="size-4 shrink-0" />
            <span>{issues.join(" · ")}</span>
          </div>
          {zmqError && (
            <p className="pl-7 font-mono text-xs text-destructive/90">{zmqError}</p>
          )}
          {zmqOffline && (
            <p className="pl-7 text-xs text-destructive/90">
              In MT5: enable Algorithmic Trading, then Navigator → Services → restart{" "}
              <span className="font-mono">DWX_ZeroMQ_Server</span>. Run{" "}
              <span className="font-mono">python scripts/zmq_diagnose.py</span>
              {" "}or use <strong>Reconnect MT5</strong> in the control bar.
            </p>
          )}
        </div>
      )}

      {showAlert && (
        <div className="flex items-center justify-between bg-amber-500/10 px-6 py-2 text-sm text-amber-200">
          <div className="flex items-center gap-2">
            <AlertTriangle className="size-4 shrink-0" />
            <span>{marketAlert.message}</span>
            {marketAlert.symbols?.length > 0 && (
              <span className="font-mono text-xs opacity-80">
                ({marketAlert.symbols.join(", ")})
              </span>
            )}
          </div>
          <button
            type="button"
            className="rounded p-1 hover:bg-amber-500/20"
            aria-label="Dismiss alert"
            onClick={() => setDismissedAlert(true)}
          >
            <X className="size-4" />
          </button>
        </div>
      )}
    </div>
  );
}
