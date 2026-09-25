/** Заявка: степпер статуса, детали, документ.
 *
 *  Степпер — главный ответ на боль «отправил письмо и сижу в тишине»:
 *  видно, где заявка сейчас, кто её вёл и сколько осталось. */

import { AnimatePresence, motion } from "framer-motion";
import { Check, Download, FileCheck2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { GlassIcon } from "@/components/ui/glass-icon";
import { ConfirmSheet, Sheet } from "@/components/ui/sheet";
import { Card, CardSkeleton, Chip, Divider, StatusDot } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { openExternal } from "@/shared/max";
import type { CampusRequest } from "@/shared/types";
import {
  cn,
  haptic,
  dateFullRu,
  dateTimeRu,
  relativeDay,
  statusTone,
  STATUS_FLOW,
  STATUS_TITLES,
  TONE_TEXT,
} from "@/shared/utils";

export default function RequestDetail() {
  const { no } = useParams<{ no: string }>();
  const [request, setRequest] = useState<CampusRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();

  const load = useCallback(async () => {
    if (!no) return;
    try {
      setRequest(await api.request(no));
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Заявка не найдена");
      navigate("/requests", { replace: true });
    } finally {
      setLoading(false);
    }
  }, [no, navigate, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="px-4 pb-28 safe-top">
        <CardSkeleton />
      </div>
    );
  }
  if (!request) return null;

  const tone = statusTone(request.status);
  const terminal = ["ISSUED", "REJECTED", "CANCELLED"].includes(request.status);

  const cancel = async () => {
    try {
      setRequest(await api.cancelRequest(request.public_no));
      toast.ok("Заявка отменена");
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось отменить");
    }
  };

  const sendInfo = async () => {
    if (answer.trim().length < 2) return;
    setSending(true);
    try {
      setRequest(await api.answerInfo(request.public_no, answer.trim()));
      setInfoOpen(false);
      setAnswer("");
      toast.ok("Ответ отправлен в деканат");
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось отправить");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="px-4 pb-28 safe-top">
      <Celebrate request={request} />
      <header className="mb-6 px-1">
        <div className="mb-2 flex items-center gap-2">
          <StatusDot tone={tone} pulse={request.is_active} />
          <span className={cn("text-[13px] font-semibold", TONE_TEXT[tone])}>
            {request.status_title}
          </span>
          <span className="ml-auto font-mono text-[12px] text-faint">
            №{request.public_no}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <GlassIcon template={request.template_key} size={64} />
          <h1 className="min-w-0 text-[26px] leading-tight">{request.title}</h1>
        </div>
      </header>

      {request.status === "NEEDS_INFO" && (
        <Card className="mb-4 !border-warn/30 !bg-warn/10">
          <p className="mb-1 text-[15px] font-semibold text-warn">Нужно уточнение</p>
          <p className="mb-4 text-[14px] leading-relaxed text-ink">{request.comment}</p>
          <Button size="sm" onClick={() => setInfoOpen(true)}>
            Ответить
          </Button>
        </Card>
      )}

      {request.document && (
        <Card className="mb-4">
          <div className="mb-4 flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-ok/15 text-ok">
              <FileCheck2 size={21} />
            </span>
            <div className="min-w-0">
              <p className="text-[16px] font-semibold text-ink">Документ готов</p>
              <p className="truncate text-[13px] text-muted">
                Выдал {request.document.issued_by}
              </p>
            </div>
          </div>

          <Button
            full
            onClick={() => openExternal(request.document!.download_url)}
          >
            <Download size={17} /> Открыть PDF
          </Button>

          <button
            onClick={() => openExternal(request.document!.verify_url)}
            className="mt-3 flex w-full items-center justify-center gap-1.5 text-[13px] text-muted"
          >
            <ShieldCheck size={14} /> Проверить подлинность
          </button>

          {request.document.valid_until && (
            <p className="mt-3 text-center text-[12px] text-faint">
              Действителен до {dateFullRu(request.document.valid_until)}
            </p>
          )}
        </Card>
      )}

      <Card className="mb-4">
        <p className="mb-4 text-[13px] font-semibold text-muted">Как продвигается</p>
        <Stepper request={request} />
        {request.is_active && request.due_at && (
          <>
            <Divider className="my-4" />
            <p className="text-[13px] text-muted">
              Ориентировочный срок — {relativeDay(request.due_at)}
            </p>
          </>
        )}
      </Card>

      {Object.keys(request.payload).length > 0 && (
        <Card className="mb-4">
          <p className="mb-3 text-[13px] font-semibold text-muted">Что указано в заявке</p>
          <div className="flex flex-col gap-2.5">
            {Object.entries(request.payload)
              .filter(([k]) => !k.startsWith("_"))
              .map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-4">
                  <span className="shrink-0 text-[13px] text-faint">{fieldLabel(k)}</span>
                  <span className="text-right text-[14px] text-ink">{formatValue(v)}</span>
                </div>
              ))}
          </div>
        </Card>
      )}

      {!terminal && request.status !== "READY" && (
        <Button variant="danger" full onClick={() => setCancelOpen(true)}>
          Отменить заявку
        </Button>
      )}

      <ConfirmSheet
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={cancel}
        title="Отменить заявку?"
        description="Отменённую заявку нельзя вернуть — придётся подавать заново."
        confirmLabel="Отменить заявку"
        danger
      />

      <Sheet open={infoOpen} onClose={() => setInfoOpen(false)} title="Ответ деканату">
        <p className="mb-4 text-[14px] leading-relaxed text-muted">{request.comment}</p>
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          rows={5}
          placeholder="Напишите, что уточняете"
          className="mb-4 w-full resize-none rounded-[16px] bg-field px-4 py-3 text-[15px] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
        />
        <Button full loading={sending} onClick={sendInfo}>
          Отправить
        </Button>
      </Sheet>
    </div>
  );
}

/* ── Степпер ───────────────────────────────────────────────────── */

function Stepper({ request }: { request: CampusRequest }) {
  const byStatus = new Map(request.events.map((e) => [e.to_status, e]));
  const rejected = ["REJECTED", "CANCELLED"].includes(request.status);

  const steps = rejected
    ? [...request.events.map((e) => e.to_status)]
    : STATUS_FLOW;

  const currentIndex = steps.indexOf(request.status);

  return (
    <div className="flex flex-col">
      {steps.map((status, i) => {
        const event = byStatus.get(status);
        const done = event !== undefined;
        const current = status === request.status;
        const last = i === steps.length - 1;
        const tone = rejected && last ? statusTone(status) : current ? "accent" : "ok";

        return (
          <div key={status} className="flex gap-3">
            <div className="flex w-4 shrink-0 flex-col items-center">
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.12 * i, type: "spring", stiffness: 500, damping: 22 }}
                className={cn(
                  "mt-1.5 h-2.5 w-2.5 rounded-full",
                  done ? (current ? `bg-${tone === "accent" ? "accent" : "ok"}` : "bg-ok") : "bg-hairline",
                  current && "ring-4 ring-accent/20",
                )}
                style={
                  done
                    ? { backgroundColor: current ? "var(--accent)" : "var(--ok)" }
                    : undefined
                }
              />
              {!last && (
                <span className="relative w-px flex-1" style={{ background: "var(--hairline)", minHeight: 26 }}>
                  {done && i < currentIndex && (
                    <motion.span
                      className="absolute inset-0 origin-top"
                      style={{ background: "var(--ok)" }}
                      initial={{ scaleY: 0 }}
                      animate={{ scaleY: 1 }}
                      transition={{ delay: 0.12 * i + 0.08, duration: 0.35, ease: "easeOut" }}
                    />
                  )}
                </span>
              )}
            </div>

            <div className={cn("pb-5", last && "pb-0")}>
              <p
                className={cn(
                  "text-[15px] leading-tight",
                  done ? "font-semibold text-ink" : "text-faint",
                )}
              >
                {STATUS_TITLES[status] ?? status}
              </p>
              {event && (
                <p className="mt-0.5 text-[12px] text-faint">
                  {dateTimeRu(event.created_at)}
                  {event.actor_name && ` · ${event.actor_name}`}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Человекочитаемые подписи полей ────────────────────────────── */

const FIELD_LABELS: Record<string, string> = {
  purpose: "Куда",
  copies: "Экземпляров",
  need_original: "Оригинал",
  comment: "Комментарий",
  category: "Основание",
  reason: "Причина",
  period: "Период",
  commissariat: "Военкомат",
  employer: "Работодатель",
  session: "Сессия",
  action: "Действие",
  priority_ground: "Льгота",
  details: "Описание",
  doc_scan: "Документ",
  start_date: "Дата начала",
  question: "Вопрос",
  source: "Источник",
  clarification: "Уточнение",
};

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

function formatValue(v: unknown): string {
  if (typeof v === "boolean") return v ? "да" : "нет";
  if (v === null || v === undefined || v === "") return "—";
  const s = String(v);
  // Имя загруженного файла бессмысленно показывать целиком
  if (/^\d+_[0-9a-f]{12}\.\w+$/.test(s)) return "файл приложен";
  return s;
}

/* ── Справка готова ────────────────────────────────────────────── */

const CONFETTI = ["#2f7dff", "#35c07a", "#e3a008", "#ff6b5e", "#a855f7", "#ffffff"];

/** Готовый документ — кульминация сценария, и выглядеть он должен как событие.
 *  Показывается один раз на заявку: повторное конфетти при каждом входе
 *  раздражало бы. */
function Celebrate({ request }: { request: CampusRequest }) {
  const ready = request.status === "READY" || request.status === "ISSUED";
  const key = `campus.celebrated.${request.public_no}`;
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!ready) return;
    try {
      if (localStorage.getItem(key)) return;
      localStorage.setItem(key, "1");
    } catch {
      /* без localStorage празднуем каждый раз — не страшно */
    }
    setShow(true);
    haptic();
    const t = setTimeout(() => setShow(false), 2600);
    return () => clearTimeout(t);
  }, [ready, key]);

  const pieces = useMemo(
    () =>
      Array.from({ length: 44 }, (_, i) => ({
        x: (Math.random() - 0.5) * 360,
        y: -(160 + Math.random() * 260),
        r: Math.random() * 540 - 270,
        c: CONFETTI[i % CONFETTI.length],
        w: 6 + Math.random() * 6,
        d: Math.random() * 0.15,
      })),
    [],
  );

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="pointer-events-none fixed inset-0 z-[96] flex items-center justify-center"
          exit={{ opacity: 0, transition: { duration: 0.4 } }}
        >
          <motion.div
            initial={{ scale: 0.4, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 16 }}
            className="flex flex-col items-center rounded-[32px] bg-ink/90 px-8 py-7 text-canvas backdrop-blur-md"
          >
            <motion.span
              initial={{ rotate: -90, scale: 0 }}
              animate={{ rotate: 0, scale: 1 }}
              transition={{ delay: 0.15, type: "spring", stiffness: 260, damping: 14 }}
              className="mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-ok text-white"
            >
              <Check size={34} strokeWidth={3} />
            </motion.span>
            <p className="text-[20px] font-[700]">Справка готова</p>
            <p className="mt-1 text-[13px] opacity-70">PDF уже в чате с ботом</p>
          </motion.div>
          {pieces.map((p, i) => (
            <motion.span
              key={i}
              className="absolute top-1/2 left-1/2 rounded-[2px]"
              style={{ width: p.w, height: p.w * 0.45, background: p.c }}
              initial={{ x: 0, y: 0, rotate: 0, opacity: 1 }}
              animate={{ x: p.x, y: [0, p.y, p.y + 520], rotate: p.r, opacity: [1, 1, 0] }}
              transition={{ duration: 2.2, delay: p.d, ease: [0.2, 0.7, 0.4, 1], times: [0, 0.35, 1] }}
            />
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
