/** Учебные блоки главной: «сейчас и дальше», мой день, быстрые действия, опрос. */

import { AnimatePresence, motion } from "framer-motion";
import {
  CalendarClock,
  CalendarDays,
  Check,
  ChevronRight,
  FileCheck2,
  MapPin,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { GlassIcon } from "@/components/ui/glass-icon";
import { Card, Chip } from "@/components/ui/primitives";
import { api, ApiException } from "@/shared/api";
import type { Poll, Slot, Today, TodayItem } from "@/shared/types";
import { cn, haptic, plural } from "@/shared/utils";

/* ── Сейчас и дальше ───────────────────────────────────────────── */

function minutesNow(): number {
  // Время вуза — Иркутск (UTC+8), независимо от часового пояса телефона
  const d = new Date(Date.now() + 8 * 3600_000);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

function hm(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function place(slot: Slot): string {
  return /^\d/.test(slot.room) ? `ауд. ${slot.room}` : slot.room;
}

/** Главная карточка: какая пара идёт и сколько до конца, или какая следующая. */
export function NowCard({ today }: { today: Today }) {
  const navigate = useNavigate();
  const [mins, setMins] = useState(minutesNow);

  useEffect(() => {
    const t = setInterval(() => setMins(minutesNow()), 30_000);
    return () => clearInterval(t);
  }, []);

  const slot = today.now ?? today.next;
  if (!slot) return null;
  const live = Boolean(today.now);
  const total = hm(slot.ends) - hm(slot.starts);
  const progress = live ? Math.min(1, Math.max(0, (mins - hm(slot.starts)) / total)) : 0;
  const left = live ? hm(slot.ends) - mins : hm(slot.starts) - mins;

  const label = live
    ? `Идёт · ещё ${left} ${plural(left, "минута", "минуты", "минут")}`
    : today.next_day_label === "сегодня"
      ? left <= 60
        ? `Через ${left} ${plural(left, "минуту", "минуты", "минут")}`
        : `Сегодня в ${slot.starts}`
      : `${capitalize(today.next_day_label)} в ${slot.starts}`;

  return (
    <motion.button
      onClick={() => navigate("/schedule")}
      whileTap={{ scale: 0.98 }}
      className="reveal relative mb-3 block w-full overflow-hidden rounded-[28px] bg-ink p-5 text-left text-canvas"
    >
      {/* Заливка прогресса пары — видно, сколько осталось, без чтения цифр */}
      {live && (
        <motion.span
          aria-hidden
          initial={{ scaleX: 0 }}
          animate={{ scaleX: progress }}
          transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
          className="absolute inset-y-0 left-0 w-full origin-left bg-accent/25"
        />
      )}
      <span className="relative flex items-center gap-2 text-[13px] font-semibold opacity-70">
        {live && <span className="h-2 w-2 animate-pulse rounded-full bg-ok" />}
        {label}
      </span>
      <span className="relative mt-2 block text-[24px] leading-[1.1] font-[700]">{slot.subject}</span>
      <span className="relative mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] opacity-75">
        <span>
          {slot.starts}–{slot.ends}
        </span>
        <span className="flex items-center gap-1">
          <MapPin size={14} />
          {place(slot)}
          {slot.building_name && ` · ${slot.building_name}`}
        </span>
        <span>{slot.kind}</span>
      </span>
    </motion.button>
  );
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/* ── Мой день ──────────────────────────────────────────────────── */

const ITEM_ICON: Record<TodayItem["kind"], React.ReactNode> = {
  pair: <CalendarClock size={16} />,
  event: <CalendarDays size={16} />,
  deadline: <CalendarDays size={16} />,
  request: <FileCheck2 size={16} />,
};

/** Лента дня: пары, события, дедлайны и готовые справки вперемешку по времени. */
export function DayTimeline({ today }: { today: Today }) {
  const navigate = useNavigate();
  if (today.items.length === 0) return null;

  const open = (item: TodayItem) => {
    if (item.kind === "request") navigate(`/requests/${item.ref}`);
    else if (item.kind === "pair") navigate("/schedule");
    else navigate("/", { state: { openEvent: Number(item.ref) } });
  };

  return (
    <Card className="mb-3" padded={false}>
      <div className="flex items-baseline justify-between px-5 pt-4 pb-2">
        <p className="text-[15px] font-semibold text-ink">Мой день</p>
        <p className="text-[12px] text-faint">
          {today.weekday} · {today.week_no} неделя, {today.parity === "odd" ? "нечётная" : "чётная"}
        </p>
      </div>
      <ol className="px-2 pb-2">
        {today.items.map((item, i) => (
          <li key={i}>
            <button
              onClick={() => open(item)}
              className={cn(
                "flex w-full items-start gap-3 rounded-[16px] px-3 py-2.5 text-left transition-colors active:bg-surface-raised",
                item.state === "done" && "opacity-45",
              )}
            >
              <span className="w-11 shrink-0 pt-0.5 text-[13px] font-semibold text-muted tabular-nums">
                {item.time || "—"}
              </span>
              <span
                className={cn(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                  item.state === "now"
                    ? "bg-ok/15 text-ok"
                    : item.kind === "request"
                      ? "bg-ok/15 text-ok"
                      : item.kind === "deadline"
                        ? "bg-warn/15 text-warn"
                        : "bg-surface-raised text-muted",
                )}
              >
                {ITEM_ICON[item.kind]}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="truncate text-[15px] font-semibold text-ink">{item.title}</span>
                  {item.state === "now" && <Chip tone="ok">сейчас</Chip>}
                  {item.state === "next" && <Chip tone="accent">далее</Chip>}
                </span>
                {item.subtitle && (
                  <span className="block truncate text-[13px] text-muted">{item.subtitle}</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/* ── Быстрые действия ──────────────────────────────────────────── */

const ACTIONS = [
  { to: "/schedule", label: "Расписание", icon: "schedule" },
  { to: "/grades", label: "Баллы", icon: "grades" },
  { to: "/campus", label: "Корпуса", icon: "campus" },
  { to: "/group", label: "Группа", icon: "group" },
];

export function QuickActions() {
  const navigate = useNavigate();
  return (
    <div className="reveal mb-7 grid grid-cols-4 gap-2">
      {ACTIONS.map((a, i) => (
        <motion.button
          key={a.to}
          onClick={() => navigate(a.to)}
          whileTap={{ scale: 0.92 }}
          initial={{ y: 12, opacity: 0.4 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.05 * i, type: "spring", stiffness: 380, damping: 28 }}
          className="flex flex-col items-center gap-2 rounded-[20px] bg-surface/80 py-3.5 shadow-lift backdrop-blur-md"
        >
          <GlassIcon template={a.icon} size={48} />
          <span className="text-[12px] font-semibold text-ink">{a.label}</span>
        </motion.button>
      ))}
    </div>
  );
}

/* ── Опрос группы ──────────────────────────────────────────────── */

export function PollCard({
  poll,
  onChange,
  onError,
}: {
  poll: Poll;
  onChange: (p: Poll) => void;
  onError: (m: string) => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const voted = poll.my_vote !== null;
  const max = Math.max(1, ...poll.counts);

  const choose = async (idx: number) => {
    setBusy(idx);
    try {
      onChange(await api.vote(poll.id, idx));
      haptic();
    } catch (e) {
      onError(e instanceof ApiException ? e.message : "Не удалось отправить голос");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="mb-3">
      <div className="mb-3 flex items-center gap-2">
        <Chip tone="accent">Опрос группы</Chip>
        <span className="text-[12px] text-faint">
          {poll.voted} {plural(poll.voted, "голос", "голоса", "голосов")}
        </span>
      </div>
      <p className="mb-4 text-[17px] leading-snug font-semibold text-ink">{poll.question}</p>
      <div className="space-y-2">
        {poll.options.map((opt, i) => {
          const share = poll.counts[i] / max;
          const mine = poll.my_vote === i;
          return (
            <motion.button
              key={i}
              onClick={() => choose(i)}
              disabled={busy !== null}
              whileTap={{ scale: 0.98 }}
              className={cn(
                "relative flex w-full items-center justify-between gap-3 overflow-hidden rounded-[14px] px-4 py-3 text-left",
                mine ? "bg-accent/15" : "bg-surface-raised",
              )}
            >
              <AnimatePresence>
                {voted && (
                  <motion.span
                    aria-hidden
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: share }}
                    transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
                    className={cn(
                      "absolute inset-y-0 left-0 w-full origin-left",
                      mine ? "bg-accent/25" : "bg-ink/[0.07]",
                    )}
                  />
                )}
              </AnimatePresence>
              <span className="relative flex items-center gap-2 text-[15px] font-medium text-ink">
                {mine && <Check size={16} className="text-accent" />}
                {opt}
              </span>
              {voted && (
                <span className="relative text-[13px] font-semibold text-muted tabular-nums">
                  {poll.counts[i]}
                </span>
              )}
            </motion.button>
          );
        })}
      </div>
    </Card>
  );
}

/** Строка-ссылка «Все опросы группы» и т.п. */
export function LinkRow({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex items-center gap-0.5 text-[14px] text-muted">
      {label} <ChevronRight size={15} />
    </button>
  );
}
