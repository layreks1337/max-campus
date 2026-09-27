/** Чат с ассистентом — ключевой экран продукта.
 *
 *  Ответ ассистента намеренно без пузыря: длинный текст на чистом канвасе
 *  читается заметно лучше. Пузырь остаётся только у реплики студента. */

import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, FileText, Loader2, Mic, RotateCcw, Sparkles, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Chip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { AssistantAction, ChatMessage, Me, Source } from "@/shared/types";
import { cn, haptic } from "@/shared/utils";
import { type Recorder, startRecording, voiceSupported } from "@/shared/voice";

interface Bubble extends ChatMessage {
  pending?: boolean;
  actions?: AssistantAction[];
  /** Вопрос, который можно задать заново, — у сообщения об ошибке сети */
  retry?: string;
}

export default function Chat({ me }: { me: Me }) {
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  // Номер попытки — ключ индикатора: «Повторить» перезапускает его этапы
  const [attempt, setAttempt] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const inflight = useRef<AbortController | null>(null);
  const lastQuestion = useRef("");
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
    // До самого низа страницы, а не до последнего сообщения: поле ввода прилипает
    // к низу экрана и закрыло бы собой свежий ответ — заметнее всего на мгновенном
    // отказе по лимиту, который приходит раньше, чем докручивается экран
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // Ушли с экрана — ответ не ждём: он сохранится на сервере и придёт с историей
  useEffect(() => () => inflight.current?.abort(), []);

  /** Запрос ответа. Новый вызов бросает предыдущий — так работает «Повторить».
   *  Брошенный запрос сервер не отменяет, а повтор того же вопроса, пока ответ
   *  готовится, к нему присоединяется (решение 061): второй раз модель не
   *  спрашивается, вопрос в истории не дублируется, ответ — в срок первого запроса. */
  const requestAnswer = async (question: string) => {
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;
    lastQuestion.current = question;
    setAttempt((n) => n + 1);
    setBusy(true);

    try {
      const res = await api.ask(question, ctrl.signal);
      if (ctrl.signal.aborted) return;
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
      // Брошен кнопкой «Повторить» или уходом с экрана — это не ошибка
      if (ctrl.signal.aborted) return;
      // Лимит вопросов повтором не лечится — кнопку не показываем
      const limited = e instanceof ApiException && e.code === "RATE_LIMITED";
      const msg =
        e instanceof ApiException ? e.message : "Не получилось получить ответ — проверь связь";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: msg,
          sources: [],
          created_at: new Date().toISOString(),
          retry: limited ? undefined : question,
        },
      ]);
    } finally {
      if (inflight.current === ctrl) {
        inflight.current = null;
        setBusy(false);
        inputRef.current?.focus();
      }
    }
  };

  const send = (text: string) => {
    const question = text.trim();
    if (!question || busy) return;

    setInput("");
    setSuggestions([]);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question, sources: [], created_at: new Date().toISOString() },
    ]);
    void requestAnswer(question);
  };

  /** «Повторить» под сообщением об ошибке: убрать его и спросить заново. */
  const retryFailed = (index: number, question: string) => {
    if (busy) return;
    setMessages((prev) => prev.filter((_, i) => i !== index));
    void requestAnswer(question);
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
    // Пока ответ готовится, очищать нельзя: кнопка неактивна (см. шапку)
    if (busy) return;
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
          // Корзина, а не стрелка по кругу: стрелка — это «Повторить» у ответа,
          // и перепутать их значило бы стереть диалог вместо повтора
          <button
            onClick={clear}
            disabled={busy}
            aria-label="Очистить диалог"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-raised text-muted disabled:opacity-40"
          >
            <Trash2 size={17} />
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
              {m.retry && (
                <button
                  onClick={() => retryFailed(i, m.retry!)}
                  disabled={busy}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-surface-raised px-4 py-2 text-[13px] font-semibold text-ink disabled:opacity-50"
                >
                  <RotateCcw size={13} />
                  Повторить
                </button>
              )}
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

        {busy && (
          <Thinking key={attempt} onRetry={() => void requestAnswer(lastQuestion.current)} />
        )}
      </div>

      <div className="sticky bottom-0 bg-gradient-to-t from-canvas via-canvas to-transparent px-5 pt-3 pb-24">
        <div className="flex items-end gap-2 rounded-[22px] bg-surface-raised p-1.5">
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
          {!input.trim() && voiceSupported() && (
            <MicButton
              disabled={busy}
              onText={(text) => void send(text)}
              onError={(m) => toast.error(m)}
            />
          )}
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

/* Этапы ответа. Сервер прогресс не присылает — строки сменяются по времени,
   но в том порядке, в котором сервис и правда работает: поиск по регламентам →
   данные студента (заявки, события) → модель. Сервер отвечает не позже ~25 с —
   по таймауту присылает выдержки из регламента (решение 060). Через 20 с —
   «Повторить»: пока сервер ещё готовит ответ, повтор дожидается того же ответа
   по новому соединению, не начиная заново (решение 061), — это и лечит обрыв связи. */
const STAGES = [
  { at: 0, text: "Ищу в регламентах…" },
  { at: 2500, text: "Сверяю с твоими данными…" },
  { at: 6000, text: "Формулирую ответ…" },
];
const RETRY_AFTER_MS = 20_000;

/** Строка этапа вместо трёх точек: видно, что ассистент работает, а не завис. */
function Thinking({ onRetry }: { onRetry: () => void }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Date.now() - started), 500);
    return () => clearInterval(timer);
  }, []);

  const stage = [...STAGES].reverse().find((s) => elapsed >= s.at) ?? STAGES[0];

  return (
    <div className="mb-6" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-[15px] text-muted">
        <Sparkles size={15} className="shimmer shrink-0" />
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={stage.text}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
          >
            <span className="shimmer">{stage.text}</span>
          </motion.span>
        </AnimatePresence>
      </div>
      {elapsed >= RETRY_AFTER_MS && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-3 flex items-center gap-3"
        >
          <span className="text-[13px] text-faint">Дольше обычного</span>
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 rounded-full bg-surface-raised px-4 py-2 text-[13px] font-semibold text-ink"
          >
            <RotateCcw size={13} />
            Повторить
          </button>
        </motion.div>
      )}
    </div>
  );
}

/** Голосовой вопрос: тап — запись, второй тап — распознать и отправить.
 *  Кольцо вокруг кнопки дышит громкостью голоса — видно, что микрофон слышит. */
function MicButton({
  disabled,
  onText,
  onError,
}: {
  disabled: boolean;
  onText: (text: string) => void;
  onError: (message: string) => void;
}) {
  const [state, setState] = useState<"idle" | "rec" | "busy">("idle");
  const [level, setLevel] = useState(0);
  const rec = useRef<Recorder | null>(null);

  useEffect(() => {
    if (state !== "rec") return;
    let raf = 0;
    const tick = () => {
      setLevel(rec.current?.level() ?? 0);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // Страховка: запись дольше 30 секунд всё равно обрезается сервером
    const limit = setTimeout(() => void toggle(), 30_000);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(limit);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  useEffect(() => () => rec.current?.cancel(), []);

  const toggle = async () => {
    if (state === "idle") {
      try {
        rec.current = await startRecording();
        setState("rec");
        haptic();
      } catch {
        onError("Нет доступа к микрофону — разрешите его в настройках");
      }
      return;
    }
    if (state !== "rec" || !rec.current) return;
    setState("busy");
    try {
      const pcm = await rec.current.stop();
      rec.current = null;
      const { text } = await api.transcribe(pcm);
      if (text) onText(text);
      else onError("Не расслышал — попробуйте ещё раз");
    } catch (e) {
      onError(e instanceof ApiException ? e.message : "Не удалось распознать речь");
    } finally {
      setState("idle");
      setLevel(0);
    }
  };

  return (
    <button
      onClick={toggle}
      disabled={disabled || state === "busy"}
      aria-label={state === "rec" ? "Остановить запись" : "Спросить голосом"}
      className={cn(
        "relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full",
        state === "rec" ? "bg-danger text-white" : "text-muted",
      )}
    >
      {state === "rec" && (
        <motion.span
          aria-hidden
          className="absolute inset-0 rounded-full bg-danger/30"
          animate={{ scale: 1 + level * 0.9 }}
          transition={{ type: "spring", stiffness: 500, damping: 20 }}
        />
      )}
      <span className="relative">
        {state === "busy" ? (
          <Loader2 size={19} className="animate-spin" />
        ) : state === "rec" ? (
          <Square size={15} fill="currentColor" />
        ) : (
          <Mic size={20} />
        )}
      </span>
    </button>
  );
}
