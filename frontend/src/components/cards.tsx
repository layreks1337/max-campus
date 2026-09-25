/** Карточки предметной области.
 *
 * Два визуальных языка, как решено в дизайне:
 *  — документные (заявки) — плоские, типографические, без фото;
 *  — обложечные (события, возможности) — фото на всю ширину и крупный
 *    заголовок поверх градиента.
 */

import { motion } from "framer-motion";
import { CalendarDays, Clock, MapPin, Users } from "lucide-react";
import { useState } from "react";
import { Card, Chip, StatusDot } from "@/components/ui/primitives";
import { GlassIcon } from "@/components/ui/glass-icon";
import type { CampusEvent, CampusRequest, Intent, Opportunity } from "@/shared/types";
import {
  cn,
  dateRu,
  plural,
  relativeDay,
  statusTone,
  timeRu,
  TONE_TEXT,
} from "@/shared/utils";

/* ── Обложка ───────────────────────────────────────────────────── */

const COVER_GRADIENTS = [
  "linear-gradient(135deg,#1e3a5f 0%,#0f172a 100%)",
  "linear-gradient(135deg,#3b2f5e 0%,#14101f 100%)",
  "linear-gradient(135deg,#1f4037 0%,#0b1a16 100%)",
  "linear-gradient(135deg,#5a2d2d 0%,#1c0f0f 100%)",
  "linear-gradient(135deg,#2c3e50 0%,#0e141b 100%)",
];

/** Под фотографией всегда лежит детерминированный градиент.
 *  Внешние картинки — самая ненадёжная часть демонстрации: если Unsplash
 *  не ответит, карточка обязана остаться читаемой, а не показывать
 *  сломанную иконку. */
export function Cover({ src, title }: { src: string; title: string }) {
  const [failed, setFailed] = useState(false);
  const hash = Array.from(title).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  const gradient = COVER_GRADIENTS[hash % COVER_GRADIENTS.length];

  return (
    <>
      <span className="absolute inset-0" style={{ background: gradient }} />
      {src && !failed && (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </>
  );
}

/* ── Заявка ────────────────────────────────────────────────────── */

export function RequestCard({
  request,
  onClick,
  showStudent,
}: {
  request: CampusRequest;
  onClick?: () => void;
  showStudent?: boolean;
}) {
  const tone = statusTone(request.status);
  const overdue =
    request.is_active && request.due_at && new Date(request.due_at) < new Date();

  return (
    <Card onClick={onClick} className="mb-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2">
          <StatusDot tone={tone} pulse={request.is_active} />
          <span className={cn("truncate text-[13px] font-semibold", TONE_TEXT[tone])}>
            {request.status_title}
          </span>
        </span>
        <span className="shrink-0 font-mono text-[12px] text-faint">№{request.public_no}</span>
      </div>

      <div className="mb-1 flex items-center gap-3">
        <GlassIcon template={request.template_key} size={40} />
        <p className="min-w-0 text-[17px] leading-snug font-semibold break-words text-ink">
          {request.title}
        </p>
      </div>

      {showStudent && request.student_name && (
        <p className="mb-1 text-[13px] text-muted">
          {request.student_name} · {request.student_group}
        </p>
      )}

      <p className="text-[13px] text-faint">
        Подана {dateRu(request.created_at)}
        {request.due_at && request.is_active && (
          <span className={cn(overdue && "text-danger")}>
            {" · "}
            {overdue ? "просрочена" : `срок ${relativeDay(request.due_at)}`}
          </span>
        )}
      </p>

      {request.status === "NEEDS_INFO" && request.comment && (
        <p className="mt-3 rounded-[12px] bg-warn/10 px-3 py-2 text-[13px] leading-snug text-warn">
          {request.comment}
        </p>
      )}
    </Card>
  );
}

/* ── Событие ───────────────────────────────────────────────────── */

export function EventCard({
  event,
  onClick,
}: {
  event: CampusEvent;
  onClick?: () => void;
}) {
  const registered = event.my_status === "REGISTERED";
  const waitlist = event.my_status === "WAITLIST";
  const full = event.capacity > 0 && event.taken >= event.capacity;

  if (event.cover_url) {
    return (
      <motion.button
        onClick={onClick}
        whileTap={{ scale: 0.985 }}
        className="reveal relative mb-3 block h-[200px] w-full overflow-hidden rounded-[24px] text-left"
      >
        <Cover src={event.cover_url} title={event.title} />
        {/* Затемнение обязательно: на светлых снимках белый текст иначе не читается */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-black/10" />

        <div className="absolute inset-x-0 top-0 flex items-start justify-between p-4">
          <Chip tone="overlay">{relativeDay(event.starts_at)}</Chip>
          {registered && <Chip tone="overlay">✓ Иду</Chip>}
          {waitlist && <Chip tone="overlay">В листе ожидания</Chip>}
        </div>

        <div className="absolute inset-x-0 bottom-0 p-4">
          <p className="mb-1.5 text-[24px] leading-[1.1] font-[650] break-words text-white">
            {event.title}
          </p>
          <p className="flex items-center gap-3 text-[13px] text-white/75">
            <span className="flex shrink-0 items-center gap-1">
              <Clock size={13} />
              {timeRu(event.starts_at)}
            </span>
            {event.location && (
              <span className="flex min-w-0 items-center gap-1">
                <MapPin size={13} className="shrink-0" />
                <span className="truncate">{event.location}</span>
              </span>
            )}
          </p>
        </div>
      </motion.button>
    );
  }

  return (
    <Card onClick={onClick} className="mb-3">
      <div className="mb-2 flex items-center gap-2">
        <Chip tone={event.kind === "DEADLINE" ? "warn" : "soft"}>{event.kind_title}</Chip>
        <Chip tone="soft">{relativeDay(event.starts_at)}</Chip>
        {registered && <Chip tone="ok">Иду</Chip>}
      </div>
      <p className="mb-1.5 text-[17px] leading-snug font-semibold text-ink">{event.title}</p>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
        <span className="flex items-center gap-1">
          <CalendarDays size={13} />
          {dateRu(event.starts_at)}, {timeRu(event.starts_at)}
        </span>
        {event.location && (
          <span className="flex items-center gap-1">
            <MapPin size={13} />
            {event.location}
          </span>
        )}
        {event.capacity > 0 && (
          <span className={cn("flex items-center gap-1", full && "text-warn")}>
            <Users size={13} />
            {event.taken}/{event.capacity}
          </span>
        )}
      </p>
    </Card>
  );
}

/* ── Возможность ───────────────────────────────────────────────── */

export function OpportunityCard({
  opportunity,
  onClick,
  layoutId,
  hidden,
}: {
  opportunity: Opportunity;
  onClick?: () => void;
  layoutId?: string;
  hidden?: boolean;
}) {
  const soon = opportunity.days_left !== null && opportunity.days_left <= 7;
  const deadline =
    opportunity.days_left === null
      ? null
      : opportunity.days_left === 0
        ? "сегодня последний день"
        : `${opportunity.days_left} ${plural(opportunity.days_left, "день", "дня", "дней")} до конца`;

  if (opportunity.cover_url) {
    return (
      <motion.button
        onClick={onClick}
        whileTap={{ scale: 0.985 }}
        layoutId={layoutId}
        transition={{ type: "spring", stiffness: 260, damping: 30 }}
        className={cn(
          "reveal relative mb-3 block h-[210px] w-full overflow-hidden rounded-[24px] text-left",
          hidden && "invisible",
        )}
      >
        <Cover src={opportunity.cover_url} title={opportunity.title} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-black/10" />

        <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-2 p-4">
          <Chip tone="overlay">{opportunity.kind_title}</Chip>
          {deadline && (
            <Chip tone="overlay" className={cn(soon && "!bg-warn/85 !text-black")}>
              {deadline}
            </Chip>
          )}
        </div>

        <div className="absolute inset-x-0 bottom-0 p-4">
          <p className="mb-1.5 line-clamp-3 text-[24px] leading-[1.1] font-[650] break-words text-white">
            {opportunity.title}
          </p>
          <p className="truncate text-[13px] text-white/75">
            {opportunity.organizer}
            {opportunity.prize_text && ` · ${opportunity.prize_text}`}
          </p>
        </div>
      </motion.button>
    );
  }

  return (
    <Card onClick={onClick} className="mb-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Chip tone="soft">{opportunity.kind_title}</Chip>
        <Chip tone="soft">{opportunity.level_title}</Chip>
        {deadline && <Chip tone={soon ? "warn" : "soft"}>{deadline}</Chip>}
      </div>
      <p className="mb-1.5 text-[17px] leading-snug font-semibold text-ink">
        {opportunity.title}
      </p>
      <p className="text-[13px] text-muted">
        {opportunity.organizer}
        {opportunity.prize_text && ` · ${opportunity.prize_text}`}
      </p>
    </Card>
  );
}

/* ── Карточка в колоде ─────────────────────────────────────────── */

const INTENT_GRADIENTS: Record<string, string> = {
  STUDY_BUDDY: "linear-gradient(140deg,#1e3a8a 0%,#2f7dff 100%)",
  MENTOR: "linear-gradient(140deg,#14532d 0%,#35c07a 100%)",
  TEAM: "linear-gradient(140deg,#581c87 0%,#a855f7 100%)",
  HOBBY: "linear-gradient(140deg,#7c2d12 0%,#f97316 100%)",
  COMMUTE: "linear-gradient(140deg,#0f766e 0%,#2dd4bf 100%)",
  MENTEE: "linear-gradient(140deg,#713f12 0%,#e3a008 100%)",
};

/** Карточка в колоде «Люди» — в том же постерном языке, что и афиша:
 *  цветная шапка по типу объявления, крупный заголовок, автор внизу. */
export function IntentCard({ intent }: { intent: Intent }) {
  const hash = Array.from(intent.kind).reduce((a, c) => a + c.charCodeAt(0), 0);
  const gradient = INTENT_GRADIENTS[intent.kind] ?? COVER_GRADIENTS[hash % COVER_GRADIENTS.length];
  return (
    <div className="flex h-full w-full flex-col overflow-hidden rounded-[28px] border border-hairline bg-surface shadow-lift-strong">
      <div className="relative shrink-0 px-6 pt-6 pb-7 text-white" style={{ background: gradient }}>
        <span className="relative inline-flex rounded-full bg-black/25 px-3 py-1.5 text-[12px] font-semibold backdrop-blur-sm">
          {intent.kind_title}
        </span>
        <p className="relative mt-4 line-clamp-3 text-[26px] leading-[1.1] font-[700]">{intent.title}</p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col justify-between p-6 pt-5">
        <div className="min-h-0">
          <p className="mb-4 line-clamp-5 text-[15px] leading-relaxed text-muted">
            {intent.description}
          </p>
          {intent.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {intent.tags.slice(0, 4).map((t) => (
                <Chip key={t} tone="soft">
                  #{t}
                </Chip>
              ))}
            </div>
          )}
        </div>

        <div className="mt-5 flex items-center gap-3 border-t border-hairline-soft pt-4">
          <div
            className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full text-[16px] font-semibold text-white"
            style={{ background: gradient }}
          >
            {intent.author_photo ? (
              <img src={intent.author_photo} alt="" className="h-full w-full object-cover" />
            ) : (
              intent.author_name.slice(0, 1).toUpperCase()
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold text-ink">{intent.author_name}</p>
            <p className="truncate text-[13px] text-faint">
              {intent.author_course ? `${intent.author_course} курс` : ""}
              {intent.author_faculty ? ` · ${shortFaculty(intent.author_faculty)}` : ""}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

const FACULTY_SHORT: Record<string, string> = {
  "Институт математики и информационных технологий": "ИМИТ",
  "Юридический институт": "ЮИ",
  "Институт социальных наук": "ИСН",
  "Исторический факультет": "ИФ",
  "Физический факультет": "ФФ",
};

export function shortFaculty(name: string): string {
  return FACULTY_SHORT[name] ?? name;
}
