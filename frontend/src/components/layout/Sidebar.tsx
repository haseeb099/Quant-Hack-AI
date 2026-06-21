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
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/positions", label: "Positions", icon: Wallet },
  { to: "/trades", label: "Trades", icon: Activity },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/risk", label: "Risk", icon: ShieldAlert },
  { to: "/market", label: "Market", icon: CandlestickChart },
  { to: "/decisions", label: "Decisions", icon: Radio },
  { to: "/demo", label: "Demo", icon: Trophy },
];

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-border bg-panel">
      <div className="flex h-14 items-center border-b border-border px-4">
        <span className="text-sm font-semibold tracking-wide text-primary">
          QuantAI
        </span>
        <span className="ml-1 text-xs text-muted-foreground">Command</span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-border p-4 text-xs text-muted-foreground">
        15-min cycle engine
      </div>
    </aside>
  );
}
