/** Мелкие помощники: классы, даты, статусы. */

import { haptics } from "@/shared/max";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

const MONTHS_GEN = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

const MONTHS_NOM = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

/* Время вуза, а не часовой пояс телефона: расписание, события и сообщения бота
 * живут по вузу, и эксперт из Москвы должен видеть то же «18:00», что и в чате.
 * Смещение приходит с сервера в /me (UNIVERSITY_TZ_HOURS); до ответа — Иркутск,
 * как по умолчанию на сервере. */
let universityOffsetHours = 8;

export function setUniversityOffset(hours: number | undefined): void {
  if (typeof hours === "number" && Number.isFinite(hours)) universityOffsetHours = hours;
}

/** Тот же момент, сдвинутый во время вуза. Читать через getUTC*(). */
function toUniversity(d: Date): Date {
  return new Date(d.getTime() + universityOffsetHours * 3600_000);
}

/** Текущее время вуза. Читать через getUTC*(): часы и минуты — уже по вузу. */
export function universityNow(): Date {
  return toUniversity(new Date());
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Дата-время из API во времени вуза, читать через getUTC*(). Дата без времени
 *  («2026-09-28») — календарный день, её не сдвигаем. */
export function universityDate(value: string | null | undefined): Date | null {
  const d = parseDate(value);
  if (!d) return null;
  return /^\d{4}-\d{2}-\d{2}$/.test(value ?? "") ? d : toUniversity(d);
}

const pad2 = (n: number): string => String(n).padStart(2, "0");

/** 23 сентября */
export function dateRu(value: string | null | undefined): string {
  const d = universityDate(value);
  if (!d) return "";
  return `${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]}`;
}

/** 23 сентября 2026 */
export function dateFullRu(value: string | null | undefined): string {
  const d = universityDate(value);
  if (!d) return "";
  return `${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** 23 сентября, 17:00 */
export function dateTimeRu(value: string | null | undefined): string {
  const d = universityDate(value);
  if (!d) return "";
  return `${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]}, ${timeRu(value)}`;
}

/** 17:00 — по времени вуза */
export function timeRu(value: string | null | undefined): string {
  const d = universityDate(value);
  if (!d) return "";
  return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
}

export function monthName(value: string | null | undefined): string {
  const d = universityDate(value);
  return d ? MONTHS_NOM[d.getUTCMonth()] : "";
}

/** «сегодня», «завтра», «через 3 дня», «23 сентября» — дни считаются по вузу */
export function relativeDay(value: string | null | undefined): string {
  const d = universityDate(value);
  if (!d) return "";
  const dayNo = (x: Date) => Math.floor(x.getTime() / 86_400_000);
  const diff = dayNo(d) - dayNo(universityNow());

  if (diff === 0) return "сегодня";
  if (diff === 1) return "завтра";
  if (diff === 2) return "послезавтра";
  if (diff > 2 && diff < 7) return `через ${diff} дн.`;
  if (diff < 0) return dateRu(value);
  return dateRu(value);
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

/** Цвет индикатора статуса заявки. Карточка целиком не красится —
 *  цвет несёт только точка и подпись (см. docs/04-design.md). */
export function statusTone(status: string): "neutral" | "accent" | "warn" | "ok" | "danger" {
  switch (status) {
    case "DRAFT":
      return "neutral";
    case "SUBMITTED":
    case "IN_REVIEW":
    case "SIGNING":
      return "accent";
    case "NEEDS_INFO":
      return "warn";
    case "READY":
    case "ISSUED":
      return "ok";
    case "REJECTED":
      return "danger";
    case "CANCELLED":
      return "neutral";
    default:
      return "neutral";
  }
}

export const TONE_TEXT: Record<string, string> = {
  neutral: "text-faint",
  accent: "text-accent",
  warn: "text-warn",
  ok: "text-ok",
  danger: "text-danger",
};

export const TONE_BG: Record<string, string> = {
  neutral: "bg-faint",
  accent: "bg-accent",
  warn: "bg-warn",
  ok: "bg-ok",
  danger: "bg-danger",
};

/** Полный путь прохождения заявки — для степпера. */
export const STATUS_FLOW = ["SUBMITTED", "IN_REVIEW", "SIGNING", "READY", "ISSUED"];

export const STATUS_TITLES: Record<string, string> = {
  DRAFT: "Черновик",
  SUBMITTED: "Отправлена",
  IN_REVIEW: "Принята в работу",
  NEEDS_INFO: "Требует уточнения",
  SIGNING: "На подписи",
  READY: "Готова",
  ISSUED: "Выдана",
  REJECTED: "Отклонена",
  CANCELLED: "Отменена",
};

/* ── Данные заявки: подписи и значения ──────────────────────────── */

/** Поля, которых нет в шаблоне: их дописывает сервер (ответ на уточнение,
 *  обращение из чата). Остальные подписи приходят с заявкой из шаблона. */
const SYSTEM_FIELD_LABELS: Record<string, string> = {
  clarification: "Уточнение",
  question: "Вопрос",
  source: "Источник",
};

function formatPayloadValue(v: unknown): string {
  if (typeof v === "boolean") return v ? "да" : "нет";
  if (v === null || v === undefined || v === "") return "—";
  const s = String(v);
  // Имя загруженного файла бессмысленно показывать целиком
  if (/^\d+_[0-9a-f]{12}\.\w+$/.test(s)) return "файл приложен";
  return s;
}

/** Строки «подпись — значение» для блока «Что указано в заявке». Общие для
 *  студента и деканата: раньше у сотрудника были видны commissariat и
 *  need_original вместо подписей. */
export function payloadRows(request: {
  payload: Record<string, unknown>;
  field_labels?: Record<string, string>;
}): Array<{ key: string; label: string; value: string }> {
  return Object.entries(request.payload)
    .filter(([k]) => !k.startsWith("_"))
    .map(([k, v]) => ({
      key: k,
      label: request.field_labels?.[k] ?? SYSTEM_FIELD_LABELS[k] ?? k,
      value: formatPayloadValue(v),
    }));
}

/** Лёгкий отклик на нажатие. В MAX на телефоне — нативный HapticFeedback,
 *  в браузере — navigator.vibrate (на iOS его нет). */
export function haptic(): void {
  haptics.impact("light");
}

/** Кириллица, похожая на латиницу: код билета диктуют и набирают на русской раскладке. */
const LOOKALIKE: Record<string, string> = {
  А: "A", В: "B", Е: "E", К: "K", М: "M", Н: "H", О: "O", Р: "P", С: "C", Т: "T", Х: "X", У: "Y",
};

/** Код билета из того, что ввели или прочитал сканер: «T12-ABCDE», «т12 abcde»,
 *  или ссылка с ним (…?startapp=ticket_T12-ABCDE). Подпись — 5 символов base32
 *  (A–Z, 2–7), как в backend/app/api/routes_campus.py → ticket_code(). */
export function parseTicketCode(raw: string): string | null {
  const s = raw
    .toUpperCase()
    .replace(/[\u0400-\u04FF]/g, (ch) => LOOKALIKE[ch] ?? ch)
    .replace(/[\s\u2010-\u2015-]+/g, "-"); // «T12 ABCDE», «T12 – ABCDE» → T12-ABCDE
  const m = s.match(/T(\d{1,9})-([A-Z2-7]{5})(?![A-Z0-9])/);
  return m ? `T${m[1]}-${m[2]}` : null;
}
