import {
  Activity,
  Bot,
  CandlestickChart,
  LayoutDashboard,
  Radio,
  ShieldAlert,
  Trophy,
  Wallet,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LiveIndicator } from "@/components/shared/LiveIndicator";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

const tradingNav = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/positions", label: "Positions", icon: Wallet },
  { to: "/trades", label: "Trades", icon: Activity },
  { to: "/risk", label: "Risk", icon: ShieldAlert },
  { to: "/market", label: "Market", icon: CandlestickChart },
  { to: "/decisions", label: "Scan log", icon: Radio },
];

const opsNav = [{ to: "/agents", label: "Agents", icon: Bot }];

const demoNav = [{ to: "/demo", label: "Demo", icon: Trophy }];

function NavSection({
  title,
  items,
}: {
  title: string;
  items: typeof tradingNav;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
        {title}
      </span>
      {items.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            cn(
              "group flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-all",
              isActive
                ? "bg-primary/12 text-primary shadow-[inset_2px_0_0_0_var(--color-primary)]"
                : "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
            )
          }
        >
          <Icon className="size-4 shrink-0 opacity-80 group-hover:opacity-100" />
          {label}
        </NavLink>
      ))}
    </div>
  );
}

export function Sidebar() {
  const { data: status } = useQuery({
    queryKey: queryKeys.status,
    queryFn: api.getStatus,
    refetchInterval: 15_000,
  });

  const engineLive = status?.engine_running && !status?.engine_paused;

  return (
    <aside className="glass-panel fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-border/80 bg-panel">
      <div className="flex h-14 items-center gap-2 border-b border-border/80 px-4">
        <div className="flex size-7 items-center justify-center rounded-md bg-primary/15">
          <span className="font-mono text-xs font-bold text-primary">Q</span>
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">QuantAI</div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Command
          </div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-5 overflow-y-auto p-3">
        <NavSection title="Trading" items={tradingNav} />
        <NavSection title="Intelligence" items={opsNav} />
        <NavSection title="Operations" items={demoNav} />
      </nav>

      <div className="border-t border-border/80 p-4">
        <div className="mb-2 flex items-center gap-2">
          <LiveIndicator connected={!!engineLive} label="Live" />
          <span className="text-xs text-muted-foreground">
            {status?.engine_paused
              ? "Paused"
              : status?.engine_running
                ? "Engine live"
                : "Engine offline"}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10px] font-mono uppercase text-muted-foreground">
          <span className="rounded bg-muted/60 px-1.5 py-0.5">
            {status?.mode ?? "—"}
          </span>
          <span className="rounded bg-muted/60 px-1.5 py-0.5">
            {status?.phase?.replace(/_/g, " ") ?? "—"}
          </span>
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground/80">15-min cycle</p>
      </div>
    </aside>
  );
}
