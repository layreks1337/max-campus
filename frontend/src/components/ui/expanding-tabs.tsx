/**
 * Раскрывающиеся табы — нижняя навигация.
 *
 * Адаптация компонента с 21st.dev под наш стек и дизайн:
 *  • убрана директива "use client" — она только для Next.js, у нас Vite;
 *  • @phosphor-icons заменены на lucide-react (одна иконочная библиотека);
 *  • убран демонстрационный враппер min-h-screen, компонент стал плавающим баром;
 *  • захардкоженные цвета заменены токенами темы;
 *  • добавлены safe-area и aria-current.
 *
 * Паттерн совпадает с нижним баром из референса Panora: неактивные табы —
 * иконкой, активный раскрывается и показывает подпись.
 */

import { AnimatePresence, motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { cn, haptic } from "@/shared/utils";

const SPRING = { type: "spring" as const, stiffness: 420, damping: 30, mass: 0.7 };

export interface TabItem {
  key: string;
  label: string;
  icon: LucideIcon;
  badge?: number;
}

export function ExpandingTabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabItem[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center pb-2 safe-bottom">
      <motion.nav
        layout
        transition={SPRING}
        role="tablist"
        aria-label="Разделы приложения"
        className={cn(
          // Пять вкладок (у сотрудника) на экране 360 px помещаются только
          // с узким зазором
          "pointer-events-auto flex max-w-[calc(100vw-1.5rem)] items-center",
          tabs.length > 4 ? "gap-1" : "gap-2",
          "rounded-full border border-hairline bg-canvas-soft/85 p-1.5 backdrop-blur-xl",
          "shadow-lift-strong",
        )}
      >
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = active === tab.key;

          return (
            <motion.button
              key={tab.key}
              layout
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-current={isActive ? "page" : undefined}
              aria-label={tab.label}
              onClick={() => {
                if (!isActive) haptic();
                onChange(tab.key);
              }}
              whileTap={{ scale: 0.94 }}
              transition={SPRING}
              className={cn(
                "relative flex h-11 shrink-0 cursor-pointer items-center justify-start",
                "overflow-hidden rounded-full pl-3 outline-none",
                "focus-visible:ring-2 focus-visible:ring-accent",
                // В светлой теме surface-raised совпадал с фоном бара и активная
                // вкладка терялась среди белых — даём ей заметно более тёмную заливку
                isActive
                  ? "gap-2 bg-[#dedee2] pr-4 shadow-lift-strong dark:bg-surface-raised"
                  : "w-11 bg-surface shadow-lift",
              )}
            >
              <motion.span
                animate={{ scale: isActive ? 1.03 : 1, opacity: isActive ? 1 : 0.62 }}
                transition={SPRING}
                className="flex shrink-0 items-center justify-center text-ink"
              >
                <Icon size={19} strokeWidth={2} aria-hidden />
              </motion.span>

              <AnimatePresence initial={false}>
                {isActive && (
                  <motion.span
                    layout
                    initial={{ opacity: 0, x: -7 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -7 }}
                    transition={SPRING}
                    className="whitespace-nowrap text-[14px] font-semibold text-ink"
                  >
                    {tab.label}
                  </motion.span>
                )}
              </AnimatePresence>

              {!isActive && !!tab.badge && (
                <span
                  aria-hidden
                  className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-accent"
                />
              )}
            </motion.button>
          );
        })}
      </motion.nav>
    </div>
  );
}
