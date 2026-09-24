/** Мелкие помощники: классы, даты, статусы. */

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

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 23 сентября */
export function dateRu(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "";
  return `${d.getDate()} ${MONTHS_GEN[d.getMonth()]}`;
}

/** 23 сентября 2026 */
export function dateFullRu(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "";
  return `${d.getDate()} ${MONTHS_GEN[d.getMonth()]} ${d.getFullYear()}`;
}

/** 23 сентября, 17:00 */
export function dateTimeRu(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "";
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `${d.getDate()} ${MONTHS_GEN[d.getMonth()]}, ${time}`;
}

export function timeRu(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "";
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function monthName(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? MONTHS_NOM[d.getMonth()] : "";
}

/** «сегодня», «завтра», «через 3 дня», «23 сентября» */
export function relativeDay(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "";
  const today = new Date();
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((startOf(d) - startOf(today)) / 86_400_000);

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

export function haptic(): void {
  try {
    navigator.vibrate?.(8);
  } catch {
    /* не везде поддерживается */
  }
}
