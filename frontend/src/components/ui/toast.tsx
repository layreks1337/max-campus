/** Тосты. Держим глобально через контекст: уведомлять об успехе и ошибке
 *  нужно из любого экрана, а таскать колбэк пропсами — лишний шум. */

import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type Tone = "ok" | "error" | "info";

interface Toast {
  id: number;
  text: string;
  tone: Tone;
}

interface ToastApi {
  show: (text: string, tone?: Tone) => void;
  ok: (text: string) => void;
  error: (text: string) => void;
}

const Ctx = createContext<ToastApi>({ show: () => {}, ok: () => {}, error: () => {} });

export const useToast = () => useContext(Ctx);

const ICONS: Record<Tone, ReactNode> = {
  ok: <CheckCircle2 size={18} className="text-ok" />,
  error: <AlertCircle size={18} className="text-danger" />,
  info: <Info size={18} className="text-accent" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const show = useCallback((text: string, tone: Tone = "info") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setItems((prev) => [...prev.slice(-2), { id, text, tone }]);
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 3600);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      ok: (t: string) => show(t, "ok"),
      error: (t: string) => show(t, "error"),
    }),
    [show],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-[100] flex flex-col items-center gap-2 px-4 pt-3 safe-top">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: -24, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -16, scale: 0.96 }}
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
              className="pointer-events-auto flex w-full max-w-[460px] items-start gap-3 rounded-[18px] border border-hairline bg-surface px-4 py-3 shadow-lift-strong"
            >
              <span className="mt-0.5 shrink-0">{ICONS[t.tone]}</span>
              <span className="text-[14px] leading-snug text-ink">{t.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}
