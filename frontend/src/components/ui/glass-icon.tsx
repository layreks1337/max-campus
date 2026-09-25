/** Иконки типов заявок в стиле «матового стекла».
 *
 *  Каждая собрана из слоёв на сетке 64×64: тёмная подложка → белый
 *  «бумажный» предмет → полупрозрачная матовая панель с настоящим размытием
 *  того, что под ней (backdrop-filter) → мелкие белые детали поверх.
 *  Эмодзи в этой роли выглядели случайно и по-разному рисовались на
 *  разных телефонах; здесь набор единый и одинаковый везде. */

import type { ReactNode } from "react";

import { cn } from "@/shared/utils";

type Panel = { x: number; y: number; w: number; h: number; r: number | string };

interface Spec {
  back: ReactNode;
  mid: ReactNode;
  panel: Panel;
  top?: ReactNode;
}

const DARK = "url(#gi-dark)";
const PAPER = "url(#gi-paper)";
const LINE = "#c4c4cb";

const SPECS: Record<string, Spec> = {
  // Папка со справками
  folder: {
    back: <path d="M8 18a5 5 0 0 1 5-5h12l4 4h22a5 5 0 0 1 5 5v24H8z" fill={DARK} />,
    mid: (
      <>
        <rect x="13" y="5" width="22" height="30" rx="3" fill={PAPER} transform="rotate(-7 24 20)" />
        <rect x="28" y="7" width="22" height="30" rx="3" fill={PAPER} transform="rotate(6 39 22)" />
        <rect x="16" y="10" width="13" height="2.4" rx="1.2" fill={LINE} transform="rotate(-7 24 20)" /><rect x="16" y="15" width="9" height="2.4" rx="1.2" fill={LINE} transform="rotate(-7 24 20)" />
        <rect x="31" y="12" width="13" height="2.4" rx="1.2" fill={LINE} transform="rotate(6 39 22)" /><rect x="31" y="17" width="9" height="2.4" rx="1.2" fill={LINE} transform="rotate(6 39 22)" />
      </>
    ),
    panel: { x: 6, y: 30, w: 52, h: 23, r: 6 },
  },
  // Щит со звездой — военкомат
  shield: {
    back: <path d="M32 6l21 7v15c0 13-9 22-21 28C20 50 11 41 11 28V13z" fill={DARK} />,
    mid: (
      <path
        d="M32 12l3.6 7.4 8.1 1.2-5.9 5.7 1.4 8.1L32 30.6l-7.2 3.8 1.4-8.1-5.9-5.7 8.1-1.2z"
        fill={PAPER}
      />
    ),
    panel: { x: 15, y: 37, w: 34, h: 18, r: "30% 30% 50% 50% / 25% 25% 75% 75%" },
  },
  // Кошелёк с купюрой — справка о доходах
  wallet: {
    back: <rect x="9" y="16" width="46" height="34" rx="7" fill={DARK} />,
    mid: (
      <>
        <rect x="14" y="4" width="32" height="22" rx="3" fill={PAPER} transform="rotate(-10 30 15)" />
        <circle cx="30" cy="14" r="4.5" fill="none" stroke={LINE} strokeWidth="2" transform="rotate(-10 30 15)" />
      </>
    ),
    panel: { x: 6, y: 29, w: 52, h: 24, r: 7 },
    top: <circle cx="47" cy="41" r="3.4" fill="#fff" opacity="0.9" />,
  },
  // Сердце над ладонью-подложкой — социальная стипендия
  heart: {
    back: <rect x="8" y="8" width="48" height="46" rx="12" fill={DARK} />,
    mid: (
      <path
        d="M32 40c-11-7-18-13-18-21a9.5 9.5 0 0 1 18-5 9.5 9.5 0 0 1 18 5c0 8-7 14-18 21z"
        fill={PAPER}
      />
    ),
    panel: { x: 7, y: 39, w: 50, h: 17, r: 9 },
  },
  // Спасательный круг — материальная помощь
  lifebuoy: {
    back: <circle cx="30" cy="30" r="22" fill="none" stroke={DARK} strokeWidth="11" />,
    mid: (
      <circle
        cx="30"
        cy="30"
        r="22"
        fill="none"
        stroke={PAPER}
        strokeWidth="11"
        strokeDasharray="17.3 17.3"
        strokeDashoffset="8.6"
      />
    ),
    panel: { x: 32, y: 32, w: 26, h: 26, r: "50%" },
    top: <path d="M45 39v12M39 45h12" stroke="#fff" strokeWidth="3" strokeLinecap="round" />,
  },
  // Дом — общежитие
  house: {
    back: <path d="M32 7l24 20v25H8V27z" fill={DARK} strokeLinejoin="round" />,
    mid: <rect x="26" y="26" width="13" height="18" rx="2.5" fill={PAPER} />,
    panel: { x: 6, y: 40, w: 52, h: 16, r: 6 },
    top: <circle cx="35" cy="47" r="1.8" fill="#fff" />,
  },
  // Пауза — академический отпуск
  pause: {
    back: <circle cx="32" cy="30" r="23" fill={DARK} />,
    mid: (
      <>
        <rect x="22" y="15" width="7" height="24" rx="3.5" fill={PAPER} />
        <rect x="35" y="15" width="7" height="24" rx="3.5" fill={PAPER} />
      </>
    ),
    panel: { x: 9, y: 34, w: 46, h: 20, r: "0 0 50% 50% / 0 0 100% 100%" },
  },
  // Календарь — справка-вызов на сессию
  calendar: {
    back: <rect x="8" y="12" width="48" height="42" rx="8" fill={DARK} />,
    mid: (
      <>
        <rect x="14" y="8" width="36" height="30" rx="4" fill={PAPER} />
        {[0, 1, 2, 3].map((c) =>
          [0, 1].map((r) => (
            <rect key={`${c}${r}`} x={19 + c * 7} y={19 + r * 7} width="4" height="4" rx="1" fill={LINE} />
          )),
        )}
        <rect x="21" y="5" width="3" height="8" rx="1.5" fill="#fff" />
        <rect x="40" y="5" width="3" height="8" rx="1.5" fill="#fff" />
      </>
    ),
    panel: { x: 5, y: 30, w: 54, h: 25, r: 8 },
    top: <path d="M40 43l3 3 6-6" stroke="#fff" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  },
  // Два облачка — вопрос в деканат
  chat: {
    back: <path d="M10 14a6 6 0 0 1 6-6h24a6 6 0 0 1 6 6v14a6 6 0 0 1-6 6H22l-8 7v-7.4A6 6 0 0 1 10 28z" fill={DARK} />,
    mid: (
      <>
        <rect x="16" y="15" width="22" height="3" rx="1.5" fill={PAPER} />
        <rect x="16" y="22" width="14" height="3" rx="1.5" fill={PAPER} />
      </>
    ),
    panel: { x: 24, y: 26, w: 34, h: 24, r: 8 },
    top: (
      <>
        <circle cx="34" cy="38" r="2.2" fill="#fff" />
        <circle cx="41" cy="38" r="2.2" fill="#fff" />
        <circle cx="48" cy="38" r="2.2" fill="#fff" />
      </>
    ),
  },
  // ── Быстрые действия главной ──────────────────────────────────
  // Часы над стеклом — расписание
  clock: {
    back: <rect x="8" y="8" width="48" height="46" rx="12" fill={DARK} />,
    mid: (
      <>
        <circle cx="32" cy="26" r="15" fill={PAPER} />
        <path d="M32 17v9l6 4" stroke="#8d8d96" strokeWidth="2.6" fill="none" strokeLinecap="round" />
      </>
    ),
    panel: { x: 6, y: 36, w: 52, h: 20, r: 8 },
    top: (
      <>
        <rect x="14" y="44" width="8" height="3" rx="1.5" fill="#fff" opacity="0.9" />
        <rect x="26" y="44" width="8" height="3" rx="1.5" fill="#fff" opacity="0.55" />
        <rect x="38" y="44" width="8" height="3" rx="1.5" fill="#fff" opacity="0.55" />
      </>
    ),
  },
  // Столбики — баллы
  bars: {
    back: <rect x="8" y="8" width="48" height="46" rx="12" fill={DARK} />,
    mid: (
      <>
        <rect x="16" y="26" width="8" height="24" rx="3" fill={PAPER} />
        <rect x="28" y="18" width="8" height="32" rx="3" fill={PAPER} />
        <rect x="40" y="11" width="8" height="39" rx="3" fill={PAPER} />
      </>
    ),
    panel: { x: 6, y: 37, w: 52, h: 19, r: 8 },
  },
  // Корпус с колоннами — корпуса
  columns: {
    back: <path d="M32 5l25 13v4h-2v30H9V22H7v-4z" fill={DARK} />,
    mid: (
      <>
        {[13, 23, 33, 43].map((x) => (
          <rect key={x} x={x} y="24" width="8" height="24" rx="2" fill={PAPER} />
        ))}
      </>
    ),
    panel: { x: 5, y: 40, w: 54, h: 16, r: 6 },
  },
  // Двое — группа
  people: {
    back: <rect x="8" y="8" width="48" height="46" rx="12" fill={DARK} />,
    mid: (
      <>
        <circle cx="24" cy="23" r="8" fill={PAPER} />
        <circle cx="41" cy="25" r="7" fill={PAPER} opacity="0.85" />
      </>
    ),
    panel: { x: 7, y: 34, w: 50, h: 22, r: "45% 45% 8px 8px / 60% 60% 8px 8px" },
  },
};

/** Шаблон заявки → иконка. Неизвестные ключи получают папку. */
const BY_TEMPLATE: Record<string, keyof typeof SPECS> = {
  study_certificate: "folder",
  military_certificate: "shield",
  income_certificate: "wallet",
  social_scholarship: "heart",
  financial_aid: "lifebuoy",
  dormitory: "house",
  academic_leave: "pause",
  session_summons: "calendar",
  support_question: "chat",
  // Быстрые действия главной
  schedule: "clock",
  grades: "bars",
  campus: "columns",
  group: "people",
};

function Defs() {
  return (
    <defs>
      <linearGradient id="gi-dark" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#4a4a50" />
        <stop offset="1" stopColor="#141416" />
      </linearGradient>
      <linearGradient id="gi-paper" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#ffffff" />
        <stop offset="1" stopColor="#e2e2e8" />
      </linearGradient>
    </defs>
  );
}

const pct = (v: number) => `${(v / 64) * 100}%`;

export function GlassIcon({
  template,
  size = 44,
  className,
}: {
  template: string;
  size?: number;
  className?: string;
}) {
  const spec = SPECS[BY_TEMPLATE[template] ?? "folder"];

  const inner = Math.round(size * 0.78);
  return (
    <span
      aria-hidden
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center",
        "bg-gradient-to-b from-[#f7f7f9] to-[#e4e4e9] shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_1px_2px_rgba(0,0,0,0.12)]",
        className,
      )}
      style={{ width: size, height: size, borderRadius: size * 0.3 }}
    >
      <GlassBody spec={spec} size={inner} />
    </span>
  );
}

function GlassBody({ spec, size }: { spec: Spec; size: number }) {
  const { panel } = spec;
  const blur = Math.max(2, size * 0.06);
  return (
    <span style={{ position: "relative", display: "inline-block", width: size, height: size }}>
      <svg viewBox="0 0 64 64" width={size} height={size} style={{ position: "absolute", inset: 0 }}>
        <Defs />
        {spec.back}
        {spec.mid}
      </svg>
      {/* Матовое стекло: размывает бумагу под собой, сверху — блик кромки */}
      <span
        style={{
          position: "absolute",
          left: pct(panel.x),
          top: pct(panel.y),
          width: pct(panel.w),
          height: pct(panel.h),
          borderRadius: typeof panel.r === "number" ? pct(panel.r) : panel.r,
          background: "linear-gradient(180deg, rgba(70,70,76,0.55) 0%, rgba(18,18,20,0.82) 100%)",
          backdropFilter: `blur(${blur}px) saturate(120%)`,
          WebkitBackdropFilter: `blur(${blur}px) saturate(120%)`,
          boxShadow: `inset 0 ${Math.max(1, size / 48)}px 0 rgba(255,255,255,0.28), 0 ${size * 0.08}px ${size * 0.18}px rgba(0,0,0,0.28)`,
        }}
      />
      {spec.top && (
        <svg viewBox="0 0 64 64" width={size} height={size} style={{ position: "absolute", inset: 0 }}>
          {spec.top}
        </svg>
      )}
    </span>
  );
}
