import { useState } from "react";
import { Outlet } from "react-router-dom";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { ConnectionBanner } from "@/components/shared/ConnectionBanner";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopStatusBar } from "@/components/layout/TopStatusBar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useLiveWebSocket } from "@/hooks/useWebSocket";
import { useQuery } from "@tanstack/react-query";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

export function DashboardLayout() {
  const [copilotOpen, setCopilotOpen] = useState(true);
  const { connected, lastAlert } = useLiveWebSocket();
  const { data: status } = useQuery({
    queryKey: queryKeys.status,
    queryFn: api.getStatus,
    refetchInterval: 15_000,
  });

  return (
    <TooltipProvider>
      <div className="min-h-screen dashboard-canvas">
        <Sidebar />
        <div className={cn("pl-56 transition-[padding] duration-200", copilotOpen && "pr-80 xl:pr-96")}>
          <TopStatusBar wsConnected={connected} />
          <ConnectionBanner status={status} wsConnected={connected} marketAlert={lastAlert} />
          <main className="p-6">
            <div className="page-enter mx-auto max-w-[1600px]">
              <Outlet />
            </div>
          </main>
        </div>
        <CopilotPanel
          open={copilotOpen}
          onToggle={() => setCopilotOpen((v) => !v)}
        />
      </div>
    </TooltipProvider>
  );
}
