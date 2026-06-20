import { AlertTriangle } from "lucide-react";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ConnectionBannerProps {
  status?: StatusResponse;
  wsConnected: boolean;
}

export function ConnectionBanner({ status, wsConnected }: ConnectionBannerProps) {
  const issues: string[] = [];

  if (!wsConnected) issues.push("WebSocket disconnected");
  if (status && status.engine_running === false) issues.push("Trading engine not running");
  if (status?.engine_running && status.mt5_connected === false) {
    issues.push("MT5 / ZeroMQ bridge offline");
  }

  if (issues.length === 0) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-3 border-b border-destructive/40 bg-destructive/10 px-6 py-2 text-sm text-destructive",
      )}
      role="alert"
    >
      <AlertTriangle className="size-4 shrink-0" />
      <span>{issues.join(" · ")}</span>
    </div>
  );
}
