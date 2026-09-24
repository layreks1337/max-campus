/** Кнопка. Все варианты — стадион-пилюли: прямоугольных кнопок в системе нет.
 *  Акцентный цвет для главного действия НЕ используется — он зарезервирован
 *  под сигналы (новое, срочно, готово). См. docs/04-design.md. */

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { cn, haptic } from "@/shared/utils";

type Variant = "primary" | "outline" | "soft" | "ghost" | "danger";
type Size = "md" | "sm" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-canvas",
  outline: "bg-transparent text-ink border border-hairline",
  soft: "bg-surface-raised text-ink",
  ghost: "bg-transparent text-muted",
  danger: "bg-transparent text-danger border border-danger/30",
};

const SIZES: Record<Size, string> = {
  sm: "h-9 px-4 text-[13px]",
  md: "h-12 px-5 text-[15px]",
  lg: "h-14 px-6 text-[16px]",
};

interface Props {
  children: ReactNode;
  onClick?: () => void;
  variant?: Variant;
  size?: Size;
  full?: boolean;
  disabled?: boolean;
  loading?: boolean;
  className?: string;
  type?: "button" | "submit";
  ariaLabel?: string;
}

export function Button({
  children,
  onClick,
  variant = "primary",
  size = "md",
  full,
  disabled,
  loading,
  className,
  type = "button",
  ariaLabel,
}: Props) {
  const isDisabled = disabled || loading;
  return (
    <motion.button
      type={type}
      aria-label={ariaLabel}
      aria-busy={loading || undefined}
      disabled={isDisabled}
      whileTap={isDisabled ? undefined : { scale: 0.97 }}
      transition={{ type: "spring", stiffness: 420, damping: 30 }}
      onClick={() => {
        if (isDisabled) return;
        haptic();
        onClick?.();
      }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-full font-semibold",
        "outline-none transition-opacity select-none",
        "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
        "focus-visible:ring-offset-canvas",
        VARIANTS[variant],
        SIZES[size],
        full && "w-full",
        isDisabled && "opacity-45",
        className,
      )}
    >
      {loading ? <Spinner /> : children}
    </motion.button>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}

/** Круглая иконочная кнопка — «…», закрыть, свайп-действия. */
export function IconButton({
  children,
  onClick,
  label,
  variant = "soft",
  size = 44,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  label: string;
  variant?: Variant;
  size?: number;
  className?: string;
}) {
  return (
    <motion.button
      type="button"
      aria-label={label}
      whileTap={{ scale: 0.92 }}
      transition={{ type: "spring", stiffness: 420, damping: 30 }}
      onClick={() => {
        haptic();
        onClick?.();
      }}
      style={{ width: size, height: size }}
      className={cn(
        "inline-flex items-center justify-center rounded-full outline-none",
        VARIANTS[variant],
        className,
      )}
    >
      {children}
    </motion.button>
  );
}
