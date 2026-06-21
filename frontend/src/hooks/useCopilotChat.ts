import { useCallback, useRef, useState } from "react";
import type { CopilotAnalysis, CopilotSSEEvent, DataCitation } from "@/lib/copilot";
import { streamCopilotChat } from "@/lib/copilot";

export type CopilotMessageRole = "user" | "assistant";

export interface CopilotMessage {
  id: string;
  role: CopilotMessageRole;
  content: string;
  citations?: DataCitation[];
  analysis?: CopilotAnalysis | null;
  streaming?: boolean;
  error?: string;
}

export type CopilotChatStatus = "ready" | "streaming" | "error";

let messageCounter = 0;

function nextId() {
  messageCounter += 1;
  return `copilot-${messageCounter}-${Date.now()}`;
}

/**
 * useChat-style hook for the QuantAI copilot SSE endpoint.
 * Parses custom events (citations → text → analysis → done).
 */
export function useCopilotChat(initialSymbol?: string | null) {
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<CopilotChatStatus>("ready");
  const [error, setError] = useState<Error | undefined>();
  const [symbol, setSymbol] = useState<string | null>(initialSymbol ?? null);
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("ready");
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
  }, []);

  const clear = useCallback(() => {
    stop();
    setMessages([]);
    setError(undefined);
    setStatus("ready");
  }, [stop]);

  const sendMessage = useCallback(
    async (text: string, opts?: { symbol?: string | null }) => {
      const trimmed = text.trim();
      if (!trimmed || status === "streaming") return;

      const activeSymbol = opts?.symbol !== undefined ? opts.symbol : symbol;
      const userMessage: CopilotMessage = {
        id: nextId(),
        role: "user",
        content: trimmed,
      };
      const assistantId = nextId();
      const assistantMessage: CopilotMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        citations: [],
        streaming: true,
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setInput("");
      setStatus("streaming");
      setError(undefined);

      const controller = new AbortController();
      abortRef.current = controller;

      const applyEvent = (event: CopilotSSEEvent) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId) return m;
            switch (event.type) {
              case "start":
                return { ...m, content: event.message };
              case "citations":
                return { ...m, citations: event.data_citations };
              case "text":
                return { ...m, content: m.content + event.content };
              case "refusal":
                return {
                  ...m,
                  content: event.summary,
                  analysis: {
                    symbol: activeSymbol ?? "",
                    verdict: "REFUSE",
                    confidence: 0,
                    summary: event.summary,
                    risks: [],
                    strategy: {},
                    session: {},
                    market: {},
                    agent_consensus: [],
                    trade_check: {},
                    data_citations: m.citations ?? [],
                    provider: "template",
                    refused: true,
                    refusal_reason: event.reason,
                  },
                };
              case "analysis":
                return {
                  ...m,
                  analysis: {
                    ...(m.analysis ?? {
                      symbol: activeSymbol ?? "",
                      summary: m.content,
                      risks: event.risks,
                      strategy: {},
                      session: {},
                      market: {},
                      agent_consensus: [],
                      trade_check: event.trade_check,
                      data_citations: m.citations ?? [],
                      refused: false,
                    }),
                    verdict: event.verdict,
                    confidence: event.confidence,
                    risks: event.risks,
                    trade_check: event.trade_check,
                    provider: event.provider,
                  } as CopilotAnalysis,
                };
              case "done":
                return {
                  ...m,
                  streaming: false,
                  analysis: event.analysis ?? m.analysis ?? null,
                };
              case "error":
                return { ...m, streaming: false, error: event.message };
              default:
                return m;
            }
          }),
        );
      };

      try {
        await streamCopilotChat(
          { message: trimmed, symbol: activeSymbol },
          applyEvent,
          { signal: controller.signal },
        );
        setStatus("ready");
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          setStatus("ready");
          return;
        }
        const message = err instanceof Error ? err.message : "Copilot error";
        setError(new Error(message));
        setStatus("error");
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, streaming: false, error: message, content: m.content || message }
              : m,
          ),
        );
      } finally {
        abortRef.current = null;
      }
    },
    [status, symbol],
  );

  const handleSubmit = useCallback(
    (event?: { preventDefault?: () => void }) => {
      event?.preventDefault?.();
      void sendMessage(input);
    },
    [input, sendMessage],
  );

  return {
    messages,
    input,
    setInput,
    symbol,
    setSymbol,
    status,
    isLoading: status === "streaming",
    error,
    sendMessage,
    handleSubmit,
    stop,
    clear,
    setMessages,
  };
}
