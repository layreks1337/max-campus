/** Баллы БРС по предметам: кольцо общего прогресса и раскрывающиеся предметы. */

import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import { CardSkeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Grades as GradesData, SubjectGrades } from "@/shared/types";
import { cn, dateRu } from "@/shared/utils";

export default function Grades() {
  const [data, setData] = useState<GradesData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    api
      .grades()
      .then(setData)
      .catch((e) => toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить баллы"));
  }, [toast]);

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-5 px-1">
        <h1 className="mb-1">Баллы</h1>
        <p className="text-[14px] text-muted">{data?.semester ?? "Балльно-рейтинговая система"}</p>
      </header>

      {!data ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : (
        <>
          <Summary data={data} />
          {data.subjects.map((s) => (
            <SubjectRow
              key={s.subject}
              subject={s}
              open={open === s.subject}
              onToggle={() => setOpen(open === s.subject ? null : s.subject)}
            />
          ))}
          <p className="mt-4 px-2 text-center text-[12px] leading-relaxed text-faint">
            Прогноз считается по доле набранных баллов: от 85% — «отлично», от 70% — «хорошо»,
            от 55% — «удовлетворительно» или зачёт. Демонстрационные данные.
          </p>
        </>
      )}
    </div>
  );
}

function Summary({ data }: { data: GradesData }) {
  const share = data.total_max ? data.total_points / data.total_max : 0;
  const R = 44;
  const C = 2 * Math.PI * R;
  return (
    <div className="reveal mb-5 flex items-center gap-5 rounded-[28px] bg-ink p-5 text-canvas">
      <svg width="108" height="108" viewBox="0 0 108 108" className="shrink-0 -rotate-90">
        <circle cx="54" cy="54" r={R} fill="none" strokeWidth="10" className="stroke-canvas/15" />
        <motion.circle
          cx="54"
          cy="54"
          r={R}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          className="stroke-accent"
          strokeDasharray={C}
          initial={{ strokeDashoffset: C }}
          animate={{ strokeDashoffset: C * (1 - share) }}
          transition={{ duration: 1.3, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
        />
      </svg>
      <div className="min-w-0">
        <p className="text-[40px] leading-none font-[750] tabular-nums">{Math.round(share * 100)}%</p>
        <p className="mt-2 text-[14px] opacity-70">
          {data.total_points} из {data.total_max} баллов за текущие контрольные точки
        </p>
      </div>
    </div>
  );
}

function tone(share: number): string {
  if (share >= 0.85) return "bg-ok";
  if (share >= 0.7) return "bg-accent";
  if (share >= 0.55) return "bg-warn";
  return "bg-danger";
}

function SubjectRow({
  subject,
  open,
  onToggle,
}: {
  subject: SubjectGrades;
  open: boolean;
  onToggle: () => void;
}) {
  const share = subject.max_points ? subject.points / subject.max_points : 0;
  return (
    <div className="reveal mb-3 overflow-hidden rounded-[24px] border border-hairline-soft bg-surface shadow-lift">
      <button onClick={onToggle} className="w-full p-5 text-left">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[16px] leading-snug font-semibold text-ink">{subject.subject}</p>
            <p className="text-[13px] text-muted">
              {subject.control} · {subject.forecast}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <span className="text-[18px] font-[700] text-ink tabular-nums">
              {subject.points}
              <span className="text-[13px] font-semibold text-faint">/{subject.max_points}</span>
            </span>
            <motion.span animate={{ rotate: open ? 180 : 0 }} className="text-faint">
              <ChevronDown size={18} />
            </motion.span>
          </div>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-surface-raised">
          <motion.div
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: share }}
            viewport={{ once: true }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            className={cn("h-full w-full origin-left rounded-full", tone(share))}
          />
        </div>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            <div className="border-t border-hairline-soft px-5 py-3">
              {subject.items.map((it) => (
                <div key={it.title} className="flex items-center justify-between py-1.5 text-[14px]">
                  <span className="text-ink-soft">
                    {it.title}
                    <span className="ml-2 text-[12px] text-faint">{dateRu(it.graded_at)}</span>
                  </span>
                  <span className="font-semibold text-ink tabular-nums">
                    {it.points}/{it.max_points}
                  </span>
                </div>
              ))}
              <p className="pt-1.5 text-[12px] text-faint">Преподаватель: {subject.teacher}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
