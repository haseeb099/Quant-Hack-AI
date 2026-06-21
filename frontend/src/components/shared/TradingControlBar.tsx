import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Zap,
} from "lucide-react";
import { useState } from "react";
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
import { api, queryKeys } from "@/lib/api";

interface TradingControlBarProps {
  compact?: boolean;
}

export function TradingControlBar({ compact = false }: TradingControlBarProps) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [manualSymbol, setManualSymbol] = useState("EUR/USD");
  const [manualVolume, setManualVolume] = useState("0.01");
  const [manualDirection, setManualDirection] = useState<"BUY" | "SELL">("BUY");
  const [manualSl, setManualSl] = useState("");
  const [manualTp, setManualTp] = useState("");

  const { data: control } = useQuery({
    queryKey: queryKeys.controlState,
    queryFn: api.getControlState,
    refetchInterval: 10_000,
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
      void invalidateAll();
    },
    onError: (err: Error) => setActionError(err.message),
  };

  const pauseMut = useMutation({ mutationFn: api.pauseEngine, ...mutationOpts });
  const resumeMut = useMutation({ mutationFn: api.resumeEngine, ...mutationOpts });
  const cycleMut = useMutation({ mutationFn: api.runCycleNow, ...mutationOpts });
  const reconnectMut = useMutation({ mutationFn: api.reconnectBridge, ...mutationOpts });
  const closeAllMut = useMutation({ mutationFn: api.closeAllPositions, ...mutationOpts });
  const manualMut = useMutation({
    mutationFn: api.manualTrade,
    ...mutationOpts,
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
    const volume = parseFloat(manualVolume);
    if (!manualSymbol.trim() || Number.isNaN(volume) || volume <= 0) {
      setActionError("Enter a valid symbol and volume");
      return;
    }
    manualMut.mutate({
      symbol: manualSymbol.trim(),
      direction: manualDirection,
      volume,
      sl: manualSl ? parseFloat(manualSl) : undefined,
      tp: manualTp ? parseFloat(manualTp) : undefined,
    });
  }

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

        <Sheet>
          <SheetTrigger asChild>
            <Button size="sm" variant="secondary" disabled={busy}>
              Manual trade
            </Button>
          </SheetTrigger>
          <SheetContent className="bg-panel border-border">
            <SheetHeader>
              <SheetTitle>Manual order</SheetTitle>
              <SheetDescription>
                Send a market order through the MT5 bridge. Use with caution.
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
              <Button disabled={busy} onClick={submitManualTrade}>
                <RefreshCw className="mr-1.5 size-3.5" />
                Execute order
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
