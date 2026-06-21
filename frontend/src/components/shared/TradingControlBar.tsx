import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  api,
  queryKeys,
  TradeBlockedError,
  type TradeCheckResponse,
} from "@/lib/api";

interface TradingControlBarProps {
  compact?: boolean;
}

function TradeRiskPreview({ check }: { check: TradeCheckResponse }) {
  if (check.allowed && check.warnings.length === 0) {
    return (
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
        Risk check passed — order may proceed.
        {check.projected.projected_leverage != null && (
          <span className="mt-1 block font-mono text-[11px] opacity-90">
            Projected leverage {String(check.projected.projected_leverage)}× · notional{" "}
            {typeof check.projected.trade_notional === "number"
              ? `$${check.projected.trade_notional.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
              : "—"}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs">
      {check.blockers.map((b) => (
        <div key={`${b.code}-${b.message}`} className="flex items-start gap-2 text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <div>
            <Badge variant="outline" className="mb-1 text-[10px] uppercase">
              {b.code}
            </Badge>
            <p>{b.message}</p>
          </div>
        </div>
      ))}
      {check.warnings.map((w) => (
        <div key={`${w.code}-${w.message}`} className="flex items-start gap-2 text-amber-200">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <p>{w.message}</p>
        </div>
      ))}
      {check.remediation.length > 0 && (
        <ul className="list-disc pl-5 text-muted-foreground">
          {check.remediation.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TradingControlBar({ compact = false }: TradingControlBarProps) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [tradeBlocked, setTradeBlocked] = useState<TradeCheckResponse | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualSymbol, setManualSymbol] = useState("EUR/USD");
  const [manualVolume, setManualVolume] = useState("0.01");
  const [manualDirection, setManualDirection] = useState<"BUY" | "SELL">("BUY");
  const [manualSl, setManualSl] = useState("");
  const [manualTp, setManualTp] = useState("");

  const parsedVolume = parseFloat(manualVolume);
  const tradeParams = useMemo(() => {
    if (!manualSymbol.trim() || Number.isNaN(parsedVolume) || parsedVolume <= 0) {
      return null;
    }
    return {
      symbol: manualSymbol.trim(),
      direction: manualDirection,
      volume: parsedVolume,
    };
  }, [manualSymbol, manualDirection, parsedVolume]);

  const { data: control } = useQuery({
    queryKey: queryKeys.controlState,
    queryFn: api.getControlState,
    refetchInterval: 10_000,
  });

  const { data: riskCheck, isFetching: riskChecking } = useQuery({
    queryKey: tradeParams
      ? queryKeys.tradeCheck(tradeParams)
      : ["tradeCheck", "invalid"],
    queryFn: () => api.checkTrade(tradeParams!),
    enabled: manualOpen && tradeParams != null,
    refetchInterval: manualOpen ? 8_000 : false,
  });

  const invalidateAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.status }),
      queryClient.invalidateQueries({ queryKey: queryKeys.positions }),
      queryClient.invalidateQueries({ queryKey: queryKeys.account }),
      queryClient.invalidateQueries({ queryKey: queryKeys.controlState }),
    ]);
  };

  const mutationOpts = {
    onSuccess: () => {
      setActionError(null);
      setTradeBlocked(null);
      void invalidateAll();
    },
    onError: (err: Error) => {
      if (err instanceof TradeBlockedError) {
        setTradeBlocked(err.check);
        setActionError(err.message);
        return;
      }
      setTradeBlocked(null);
      setActionError(err.message);
    },
  };

  const pauseMut = useMutation({ mutationFn: api.pauseEngine, ...mutationOpts });
  const resumeMut = useMutation({ mutationFn: api.resumeEngine, ...mutationOpts });
  const cycleMut = useMutation({ mutationFn: api.runCycleNow, ...mutationOpts });
  const reconnectMut = useMutation({ mutationFn: api.reconnectBridge, ...mutationOpts });
  const closeAllMut = useMutation({ mutationFn: api.closeAllPositions, ...mutationOpts });
  const manualMut = useMutation({
    mutationFn: api.manualTrade,
    ...mutationOpts,
    onSuccess: () => {
      mutationOpts.onSuccess();
      setManualOpen(false);
    },
  });

  const busy =
    pauseMut.isPending ||
    resumeMut.isPending ||
    cycleMut.isPending ||
    reconnectMut.isPending ||
    closeAllMut.isPending ||
    manualMut.isPending;

  const engineAvailable = control?.engine_available ?? false;
  const isPaused = control?.engine_paused ?? false;
  const canExecuteManual = Boolean(riskCheck?.allowed) && tradeParams != null && !busy;

  function confirmCloseAll() {
    if (
      !window.confirm(
        "Close ALL open positions immediately? This cannot be undone.",
      )
    ) {
      return;
    }
    closeAllMut.mutate();
  }

  function submitManualTrade() {
    if (!tradeParams) {
      setActionError("Enter a valid symbol and volume");
      return;
    }
    if (riskCheck && !riskCheck.allowed) {
      setTradeBlocked(riskCheck);
      setActionError(riskCheck.blockers.map((b) => b.message).join(" · "));
      return;
    }
    manualMut.mutate({
      ...tradeParams,
      sl: manualSl ? parseFloat(manualSl) : undefined,
      tp: manualTp ? parseFloat(manualTp) : undefined,
    });
  }

  const previewCheck = tradeBlocked ?? riskCheck;

  return (
    <div className={compact ? "flex flex-wrap items-center gap-2" : "flex flex-col gap-2"}>
      <div className="flex flex-wrap items-center gap-2">
        {engineAvailable && (
          isPaused ? (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => resumeMut.mutate()}
            >
              <Play className="mr-1.5 size-3.5" />
              Resume
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={busy || !control?.engine_running}
              onClick={() => pauseMut.mutate()}
            >
              <Pause className="mr-1.5 size-3.5" />
              Pause
            </Button>
          )
        )}

        {engineAvailable && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || control?.cycle_in_progress}
            onClick={() => cycleMut.mutate()}
          >
            <Zap className="mr-1.5 size-3.5" />
            Run cycle
          </Button>
        )}

        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => reconnectMut.mutate()}
        >
          <RotateCcw className="mr-1.5 size-3.5" />
          Reconnect MT5
        </Button>

        <Button
          size="sm"
          variant="destructive"
          disabled={busy}
          onClick={confirmCloseAll}
        >
          <ShieldAlert className="mr-1.5 size-3.5" />
          Close all
        </Button>

        <Sheet open={manualOpen} onOpenChange={setManualOpen}>
          <SheetTrigger asChild>
            <Button size="sm" variant="secondary" disabled={busy}>
              Manual trade
            </Button>
          </SheetTrigger>
          <SheetContent className="bg-panel border-border">
            <SheetHeader>
              <SheetTitle>Manual order</SheetTitle>
              <SheetDescription>
                Pre-trade risk check runs before every order. Blocked trades show why and how to fix.
              </SheetDescription>
            </SheetHeader>
            <div className="mt-6 flex flex-col gap-4">
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">Symbol</label>
                <Input
                  value={manualSymbol}
                  onChange={(e) => setManualSymbol(e.target.value)}
                  placeholder="EUR/USD"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">Volume</label>
                  <Input
                    value={manualVolume}
                    onChange={(e) => setManualVolume(e.target.value)}
                    inputMode="decimal"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">Direction</label>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={manualDirection === "BUY" ? "default" : "outline"}
                      className="flex-1"
                      onClick={() => setManualDirection("BUY")}
                    >
                      Buy
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={manualDirection === "SELL" ? "destructive" : "outline"}
                      className="flex-1"
                      onClick={() => setManualDirection("SELL")}
                    >
                      Sell
                    </Button>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">Stop loss</label>
                  <Input
                    value={manualSl}
                    onChange={(e) => setManualSl(e.target.value)}
                    placeholder="Optional"
                    inputMode="decimal"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">Take profit</label>
                  <Input
                    value={manualTp}
                    onChange={(e) => setManualTp(e.target.value)}
                    placeholder="Optional"
                    inputMode="decimal"
                  />
                </div>
              </div>

              {tradeParams && riskChecking && !previewCheck && (
                <p className="text-xs text-muted-foreground">Checking risk rules…</p>
              )}
              {previewCheck && <TradeRiskPreview check={previewCheck} />}

              <Button disabled={!canExecuteManual} onClick={submitManualTrade}>
                <RefreshCw className="mr-1.5 size-3.5" />
                {canExecuteManual ? "Execute order" : "Blocked by risk rules"}
              </Button>
            </div>
          </SheetContent>
        </Sheet>
      </div>

      {!engineAvailable && (
        <p className="text-[11px] text-muted-foreground">
          Start engine with{" "}
          <span className="font-mono">python main.py --with-dashboard</span> for
          pause/cycle controls. Close &amp; manual orders work via MT5 bridge.
        </p>
      )}

      {actionError && (
        <p className="text-xs text-destructive" role="alert">
          {actionError}
        </p>
      )}
    </div>
  );
}
