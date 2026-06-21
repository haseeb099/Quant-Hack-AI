import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  ChevronRight,
  Loader2,
  Send,
  Sparkles,
  Square,
  Trash2,
} from "lucide-react";
import { useEffect, useRef } from "react";
import { CopilotMessageBubble } from "@/components/copilot/CopilotMessageBubble";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

const QUICK_PROMPTS = [
  "What's my account status?",
  "Analyze Gold setup",
  "EUR/USD agent consensus",
  "Any open risk blockers?",
];

interface CopilotPanelProps {
  open: boolean;
  onToggle: () => void;
  className?: string;
}

export function CopilotPanel({ open, onToggle, className }: CopilotPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    input,
    setInput,
    symbol,
    setSymbol,
    status,
    isLoading,
    sendMessage,
    handleSubmit,
    stop,
    clear,
  } = useCopilotChat();

  const { data: instruments } = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: api.getInstruments,
    enabled: open,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "fixed bottom-6 right-4 z-40 flex items-center gap-2 rounded-full border border-primary/30 bg-card px-4 py-2.5 text-sm font-medium text-primary shadow-lg hover:bg-primary/10",
          className,
        )}
        aria-label="Open trading copilot"
      >
        <Sparkles className="size-4" />
        Copilot
      </button>
    );
  }

  return (
    <aside
      className={cn(
        "fixed inset-y-0 right-0 z-40 flex w-96 flex-col border-l border-border bg-card/95 shadow-2xl backdrop-blur",
        className,
      )}
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Bot className="size-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold">Trading Copilot</h2>
            <p className="text-[11px] text-muted-foreground">Read-only · grounded analysis</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={clear}
            disabled={messages.length === 0 && !isLoading}
            aria-label="Clear chat"
          >
            <Trash2 className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={onToggle}
            aria-label="Collapse copilot"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </header>

      <div className="border-b border-border px-4 py-2">
        <label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
          Context symbol
        </label>
        <select
          value={symbol ?? ""}
          onChange={(e) => setSymbol(e.target.value || null)}
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
        >
          <option value="">Auto-detect from message</option>
          {(instruments?.instruments ?? []).map((inst) => (
            <option key={inst.symbol} value={inst.symbol}>
              {inst.symbol}
            </option>
          ))}
        </select>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          <div className="space-y-3 rounded-lg border border-dashed border-border/70 bg-background/40 p-4">
            <p className="text-sm text-muted-foreground">
              Ask about any competition instrument. Every number is cited from live state,
              agents, or risk gate — no hallucinated prices.
            </p>
            <div className="flex flex-wrap gap-2">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => void sendMessage(prompt)}
                  className="rounded-full border border-border/80 bg-card px-3 py-1 text-xs text-foreground/90 hover:border-primary/40 hover:text-primary"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <CopilotMessageBubble key={message.id} message={message} />
          ))
        )}
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-border p-4"
      >
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about XAU/USD, risk, agents…"
            disabled={isLoading}
            className="text-sm"
            autoComplete="off"
          />
          {isLoading ? (
            <Button type="button" variant="outline" size="icon" onClick={stop} aria-label="Stop">
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim()}
              aria-label="Send message"
            >
              <Send className="size-4" />
            </Button>
          )}
        </div>
        <p className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
          {status === "streaming" ? (
            <>
              <Loader2 className="size-3 animate-spin" />
              Streaming grounded analysis…
            </>
          ) : (
            <>Rate limit 10/min · does not execute trades</>
          )}
        </p>
      </form>
    </aside>
  );
}
