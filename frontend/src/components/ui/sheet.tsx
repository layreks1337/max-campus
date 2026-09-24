/** Нижняя шторка. В мини-приложении это основной способ показать выбор
 *  или подтверждение: модалка по центру на телефоне неудобна большому пальцу. */

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { cn } from "@/shared/utils";

const SPRING = { type: "spring" as const, stiffness: 380, damping: 36 };

export function Sheet({
  open,
  onClose,
  title,
  children,
  maxHeight = "85vh",
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  maxHeight?: string;
}) {
  // Фон не должен скроллиться под открытой шторкой
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <div className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" onClick={onClose} />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={title}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={SPRING}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.4 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 110 || info.velocity.y > 600) onClose();
            }}
            style={{ maxHeight }}
            className={cn(
              "safe-bottom relative flex w-full max-w-[560px] flex-col",
              "rounded-t-[28px] border-t border-hairline bg-canvas shadow-lift-strong",
            )}
          >
            <div className="flex shrink-0 justify-center pt-3 pb-1">
              <div className="h-1 w-10 rounded-full bg-hairline" />
            </div>

            {title && (
              <div className="flex shrink-0 items-center justify-between px-5 pt-1 pb-3">
                <h2 className="text-[22px]">{title}</h2>
                <button
                  onClick={onClose}
                  aria-label="Закрыть"
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-raised text-muted"
                >
                  <X size={18} />
                </button>
              </div>
            )}

            <div className="no-scrollbar flex-1 overflow-y-auto px-5 pb-6">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Подтверждение действия — отдельный компонент, чтобы не плодить
 *  разметку в каждом экране. */
export function ConfirmSheet({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Подтвердить",
  danger,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
}) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      {description && <p className="mb-6 text-[15px] leading-relaxed text-muted">{description}</p>}
      <div className="flex flex-col gap-2">
        <button
          onClick={() => {
            onConfirm();
            onClose();
          }}
          className={cn(
            "h-12 w-full rounded-full font-semibold",
            danger ? "bg-danger text-white" : "bg-ink text-canvas",
          )}
        >
          {confirmLabel}
        </button>
        <button onClick={onClose} className="h-12 w-full rounded-full font-semibold text-muted">
          Отмена
        </button>
      </div>
    </Sheet>
  );
}
