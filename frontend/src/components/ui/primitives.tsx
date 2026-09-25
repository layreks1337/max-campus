/** Базовые поверхности и мелкие элементы.
 *  Собраны в один файл сознательно: каждый по 15 строк, разносить по
 *  отдельным модулям — только множить навигацию по проекту. */

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { cn } from "@/shared/utils";

/* ── Карточка ──────────────────────────────────────────────────── */

export function Card({
  children,
  onClick,
  className,
  padded = true,
}: {
  children: ReactNode;
  onClick?: () => void;
  className?: string;
  padded?: boolean;
}) {
  const interactive = Boolean(onClick);
  const Comp = interactive ? motion.button : motion.div;
  return (
    <Comp
      onClick={onClick}
      whileTap={interactive ? { scale: 0.985 } : undefined}
      transition={{ type: "spring", stiffness: 420, damping: 32 }}
      className={cn(
        "reveal w-full rounded-[24px] bg-surface text-left",
        "border border-hairline-soft shadow-lift",
        padded && "p-5",
        className,
      )}
    >
      {children}
    </Comp>
  );
}

/* ── Секция с заголовком ───────────────────────────────────────── */

export function Section({
  title,
  action,
  children,
  className,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("mb-7", className)}>
      <div className="reveal mb-3 flex items-baseline justify-between gap-3 px-1">
        <h2 className="text-[20px] leading-tight">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/* ── Чип ───────────────────────────────────────────────────────── */

export function Chip({
  children,
  tone = "soft",
  onClick,
  active,
  className,
}: {
  children: ReactNode;
  tone?: "soft" | "accent" | "ok" | "warn" | "danger" | "overlay";
  onClick?: () => void;
  active?: boolean;
  className?: string;
}) {
  const tones: Record<string, string> = {
    soft: "bg-surface-raised text-muted",
    accent: "bg-accent/15 text-accent",
    ok: "bg-ok/15 text-ok",
    warn: "bg-warn/15 text-warn",
    danger: "bg-danger/15 text-danger",
    overlay: "bg-black/45 text-white backdrop-blur-sm",
  };
  const Comp = onClick ? "button" : "span";
  return (
    <Comp
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5",
        "text-[12px] font-semibold leading-none",
        active ? "bg-ink text-canvas" : tones[tone],
        className,
      )}
    >
      {children}
    </Comp>
  );
}

/* ── Точка статуса ─────────────────────────────────────────────── */

export function StatusDot({ tone, pulse }: { tone: string; pulse?: boolean }) {
  const colors: Record<string, string> = {
    neutral: "bg-faint",
    accent: "bg-accent",
    warn: "bg-warn",
    ok: "bg-ok",
    danger: "bg-danger",
  };
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0">
      {pulse && (
        <span
          className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
            colors[tone])}
        />
      )}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", colors[tone])} />
    </span>
  );
}

/* ── Скелетон ──────────────────────────────────────────────────── */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("shimmer rounded-[16px] bg-surface-raised", className)} />;
}

export function CardSkeleton() {
  return (
    <div className="rounded-[24px] border border-hairline-soft bg-surface p-5">
      <Skeleton className="mb-3 h-3 w-24" />
      <Skeleton className="mb-2 h-5 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
    </div>
  );
}

/* ── Пустое состояние ──────────────────────────────────────────── */

export function Empty({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {icon && <div className="mb-4 text-faint">{icon}</div>}
      <p className="mb-1 text-[16px] font-semibold text-ink">{title}</p>
      {hint && <p className="mb-5 max-w-[280px] text-[14px] leading-relaxed text-muted">{hint}</p>}
      {action}
    </div>
  );
}

/* ── Разделитель ───────────────────────────────────────────────── */

export function Divider({ className }: { className?: string }) {
  return <div className={cn("h-px w-full bg-hairline-soft", className)} />;
}
