/** Чат с ассистентом — ключевой экран продукта.
 *
 *  Ответ ассистента намеренно без пузыря: длинный текст на чистом канвасе
 *  читается заметно лучше. Пузырь остаётся только у реплики студента. */

import { motion } from "framer-motion";
import { ArrowUp, FileText, RotateCcw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Chip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { AssistantAction, ChatMessage, Me, Source } from "@/shared/types";
import { cn } from "@/shared/utils";

interface Bubble extends ChatMessage {
  pending?: boolean;
  actions?: AssistantAction[];
}

export default function Chat({ me }: { me: Me }) {
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();
  const toast = useToast();

  const enabled = me.features?.assistant !== false;

  const load = useCallback(async () => {
    try {
      const history = await api.chatHistory();
      setMessages(history.messages);
      setSuggestions(history.suggestions);
    } catch {
      /* пустая история — не ошибка */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;

    setInput("");
    setSuggestions([]);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question, sources: [], created_at: new Date().toISOString() },
    ]);
    setBusy(true);

    try {
      const res = await api.ask(question);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.answer,
          sources: res.sources,
          actions: res.actions,
          created_at: new Date().toISOString(),
        },
      ]);
    } catch (e) {
      const msg =
        e instanceof ApiException ? e.message : "Не получилось получить ответ";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: msg, sources: [], created_at: new Date().toISOString() },
      ]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const runAction = (action: AssistantAction) => {
    switch (action.type) {
      case "open_request_form":
        navigate(`/requests/new/${action.template_key}`);
        break;
      case "open_request":
        navigate(`/requests/${action.request_no}`);
        break;
      case "open_events":
        navigate("/");
        break;
      case "open_opportunities":
        navigate("/");
        break;
      case "open_matches":
        navigate("/people");
        break;
      default:
        break;
    }
  };

  const clear = async () => {
    try {
      await api.clearChat();
      setMessages([]);
      await load();
      toast.ok("Диалог очищен");
    } catch {
      toast.error("Не удалось очистить");
    }
  };

  if (!enabled) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center px-8 text-center">
        <Sparkles size={34} className="mb-4 text-faint" strokeWidth={1.5} />
        <p className="mb-2 text-[18px] font-semibold">Ассистент выключен</p>
        <p className="text-[14px] leading-relaxed text-muted">
          Не настроен доступ к языковой модели. Остальные разделы работают как обычно.
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex items-center justify-between gap-3 px-5 pt-6 pb-3 safe-top">
        <div>
          <h1 className="text-[26px] leading-tight">Ассистент</h1>
          <p className="text-[13px] text-muted">Отвечает по регламентам вуза</p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clear}
            aria-label="Очистить диалог"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-raised text-muted"
          >
            <RotateCcw size={17} />
          </button>
        )}
      </header>

      <div className="flex-1 px-5 pb-4">
        {loaded && messages.length === 0 && (
          <div className="pt-6">
            <p className="mb-5 text-[16px] leading-relaxed text-muted">
              Спроси своими словами — про справки, стипендии, события или собственные заявки.
              Отвечаю по документам вуза и показываю источник.
            </p>
            <div className="flex flex-col gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-[18px] border border-hairline bg-surface px-4 py-3 text-left text-[15px] text-ink shadow-lift active:scale-[0.99]"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="mb-5 flex justify-end">
              <div className="max-w-[82%] rounded-[20px] rounded-br-[8px] bg-surface-raised px-4 py-2.5 text-[15px] leading-relaxed text-ink">
                {m.content}
              </div>
            </div>
          ) : (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6"
            >
              <p className="text-[15px] leading-relaxed whitespace-pre-wrap text-ink">
                {m.content}
              </p>
              <SourceList sources={m.sources} />
              {m.actions && m.actions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {m.actions.map((a, idx) => (
                    <button
                      key={idx}
                      onClick={() => runAction(a)}
                      className="inline-flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-[13px] font-semibold text-canvas"
                    >
                      <FileText size={13} />
                      {a.label ?? "Открыть"}
                    </button>
                  ))}
                </div>
              )}
            </motion.div>
          ),
        )}

        {busy && <Thinking />}
        <div ref={bottomRef} />
      </div>

      <div className="sticky bottom-0 bg-gradient-to-t from-canvas via-canvas to-transparent px-5 pt-3 pb-24">
        <div className="flex items-end gap-2 rounded-[22px] bg-field p-1.5">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
            rows={1}
            placeholder="Спросите что-нибудь"
            className="max-h-32 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-[15px] text-ink placeholder:text-faint outline-none"
          />
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || busy}
            aria-label="Отправить"
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-opacity",
              input.trim() && !busy ? "bg-ink text-canvas" : "bg-surface-raised text-faint",
            )}
          >
            <ArrowUp size={19} />
          </button>
        </div>
      </div>
    </div>
  );
}

function SourceList({ sources }: { sources: Source[] }) {
  if (!sources?.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {sources.map((s, i) => (
        <Chip key={i} tone="soft">
          📎 {s.title}
        </Chip>
      ))}
    </div>
  );
}

/** Три точки вместо спиннера: ожидание ответа модели — это «думает»,
 *  а не «грузится». */
function Thinking() {
  return (
    <div className="mb-6 flex gap-1.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-faint"
          style={{ animation: `dot-pulse 1.1s ${i * 0.15}s ease-in-out infinite` }}
        />
      ))}
    </div>
  );
}
