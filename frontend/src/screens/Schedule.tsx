/** Расписание группы: неделя, дни листаются свайпом или по чипам. */

import { AnimatePresence, motion, type PanInfo } from "framer-motion";
import { Clock, Layers, ChevronLeft, ChevronRight, MapPin, Navigation, User } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CardSkeleton, Empty } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/sheet";
import { openExternal } from "@/shared/max";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { BuildingInfo, Slot, Week } from "@/shared/types";
import { cn, haptic } from "@/shared/utils";

const SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

export default function Schedule() {
  const [week, setWeek] = useState(0);
  const [data, setData] = useState<Week | null>(null);
  const [day, setDay] = useState(0);
  const [dir, setDir] = useState(0);
  const [picked, setPicked] = useState<Slot | null>(null);
  const [buildings, setBuildings] = useState<Record<string, BuildingInfo>>({});
  const toast = useToast();

  useEffect(() => {
    api
      .buildings()
      .then((list) => setBuildings(Object.fromEntries(list.map((b) => [b.code, b]))))
      .catch(() => setBuildings({}));
  }, []);

  const load = useCallback(
    async (w: number) => {
      try {
        const res = await api.schedule(w);
        setData(res);
        const todayIdx = res.days.findIndex((d) => d.is_today);
        setDay(todayIdx >= 0 ? todayIdx : 0);
      } catch (e) {
        toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить расписание");
      }
    },
    [toast],
  );

  useEffect(() => {
    void load(week);
  }, [load, week]);

  const go = (next: number) => {
    if (!data) return;
    if (next < 0) {
      setDir(-1);
      setWeek((w) => w - 1);
      return;
    }
    if (next >= data.days.length) {
      setDir(1);
      setWeek((w) => w + 1);
      return;
    }
    haptic();
    setDir(next > day ? 1 : -1);
    setDay(next);
  };

  const onDragEnd = (_: unknown, info: PanInfo) => {
    if (info.offset.x < -60) go(day + 1);
    else if (info.offset.x > 60) go(day - 1);
  };

  const current = data?.days[day];

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-5 px-1">
        <h1 className="mb-1">Расписание</h1>
        {data && (
          <p className="text-[14px] text-muted">
            {data.group_name} · {data.week_no} неделя, {data.parity === "odd" ? "нечётная" : "чётная"}
          </p>
        )}
      </header>

      <div className="mb-5 flex items-center gap-1.5">
        <button
          onClick={() => setWeek((w) => w - 1)}
          aria-label="Прошлая неделя"
          className="flex h-10 w-8 shrink-0 items-center justify-center text-muted"
        >
          <ChevronLeft size={20} />
        </button>
        <div className="grid flex-1 grid-cols-6 gap-1.5">
          {(data?.days ?? Array.from({ length: 6 })).map((d, i) => {
            const info = d as Week["days"][number] | undefined;
            const active = i === day;
            return (
              <button
                key={i}
                onClick={() => go(i)}
                className={cn(
                  "relative flex flex-col items-center rounded-[14px] py-2",
                  active ? "text-canvas" : "text-ink",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="schedule-day"
                    className="absolute inset-0 rounded-[14px] bg-ink"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  />
                )}
                <span className={cn("relative text-[11px] font-semibold", !active && "text-muted")}>
                  {SHORT[i]}
                </span>
                <span className="relative text-[17px] font-[700] tabular-nums">
                  {info ? new Date(info.date).getDate() : "·"}
                </span>
                {info?.is_today && !active && (
                  <span className="relative mt-0.5 h-1 w-1 rounded-full bg-accent" />
                )}
              </button>
            );
          })}
        </div>
        <button
          onClick={() => setWeek((w) => w + 1)}
          aria-label="Следующая неделя"
          className="flex h-10 w-8 shrink-0 items-center justify-center text-muted"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      {!data ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : (
        <motion.div
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          dragElastic={0.25}
          dragDirectionLock
          onDragEnd={onDragEnd}
          className="min-h-[50vh] touch-pan-y"
        >
          <AnimatePresence mode="popLayout" initial={false} custom={dir}>
            <motion.div
              key={`${week}-${day}`}
              custom={dir}
              variants={{
                enter: (d: number) => ({ x: d >= 0 ? 60 : -60, opacity: 0 }),
                center: { x: 0, opacity: 1 },
                exit: (d: number) => ({ x: d >= 0 ? -60 : 60, opacity: 0 }),
              }}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ type: "spring", stiffness: 320, damping: 32 }}
            >
              <p className="mb-3 px-1 text-[15px] font-semibold text-muted">
                {current?.weekday}
                {current?.is_today && " · сегодня"}
              </p>
              {current && current.slots.length > 0 ? (
                current.slots.map((s, i) => (
                  <SlotCard key={s.id} slot={s} index={i} onClick={() => setPicked(s)} />
                ))
              ) : (
                <Empty title="Пар нет" hint="Свободный день — можно заглянуть в афишу." />
              )}
            </motion.div>
          </AnimatePresence>
        </motion.div>
      )}

      <Sheet open={picked !== null} onClose={() => setPicked(null)} title={picked?.subject}>
        {picked && <SlotDetails slot={picked} building={buildings[picked.building_code]} />}
      </Sheet>
    </div>
  );
}

const KIND_TONE: Record<string, string> = {
  Лекция: "bg-accent",
  Практика: "bg-ok",
  Семинар: "bg-ok",
  Лаба: "bg-warn",
};

function SlotCard({ slot, index, onClick }: { slot: Slot; index: number; onClick: () => void }) {
  return (
    <motion.button
      onClick={onClick}
      whileTap={{ scale: 0.98 }}
      initial={{ y: 16, opacity: 0.3 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ delay: 0.04 * index, type: "spring", stiffness: 340, damping: 30 }}
      className="mb-3 flex w-full gap-4 rounded-[24px] border border-hairline-soft bg-surface p-4 text-left shadow-lift"
    >
      <div className="flex w-14 shrink-0 flex-col items-center border-r border-hairline-soft pr-3">
        <span className="text-[16px] font-[700] text-ink tabular-nums">{slot.starts}</span>
        <span className="text-[12px] text-faint tabular-nums">{slot.ends}</span>
        <span className="mt-2 text-[11px] font-semibold text-muted">{slot.pair_no} пара</span>
      </div>
      <div className="min-w-0 flex-1">
        <span className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold text-muted">
          <span className={cn("h-2 w-2 rounded-full", KIND_TONE[slot.kind] ?? "bg-faint")} />
          {slot.kind}
        </span>
        <p className="mb-1.5 text-[17px] leading-snug font-semibold text-ink">{slot.subject}</p>
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] text-muted">
          <span className="flex items-center gap-1">
            <MapPin size={13} />
            {/^\d/.test(slot.room) ? `ауд. ${slot.room}` : slot.room}
            {slot.building_name && ` · ${slot.building_name}`}
          </span>
          <span className="flex items-center gap-1">
            <User size={13} />
            {slot.teacher}
          </span>
        </p>
      </div>
    </motion.button>
  );
}

/** Шторка пары: где аудитория, как пройти, кто ведёт. */
function SlotDetails({ slot, building }: { slot: Slot; building?: BuildingInfo }) {
  const numeric = /^\d/.test(slot.room);
  const floor = numeric ? slot.room[0] : null;
  const rows = [
    { icon: <Clock size={17} />, text: `${slot.starts}–${slot.ends} · ${slot.pair_no} пара · ${slot.kind}` },
    {
      icon: <MapPin size={17} />,
      text: `${numeric ? `Аудитория ${slot.room}` : slot.room}${building ? ` · ${building.name}` : ""}`,
    },
    ...(floor ? [{ icon: <Layers size={17} />, text: `${floor} этаж — первая цифра номера аудитории` }] : []),
    { icon: <User size={17} />, text: slot.teacher },
  ];
  return (
    <div className="pb-2">
      {rows.map((r, i) => (
        <motion.p
          key={i}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05 * i, type: "spring", stiffness: 320, damping: 28 }}
          className="mb-3 flex items-start gap-3 text-[15px] text-ink-soft"
        >
          <span className="mt-0.5 shrink-0 text-muted">{r.icon}</span>
          {r.text}
        </motion.p>
      ))}
      {building && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="mt-4 rounded-[18px] bg-surface-raised p-4"
        >
          <p className="mb-1 text-[14px] font-semibold text-ink">{building.address}</p>
          <p className="mb-4 text-[13px] leading-snug text-muted">{building.hint}</p>
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => openExternal(building.map_url)}
            className="flex w-full items-center justify-center gap-2 rounded-full bg-ink py-3 text-[15px] font-semibold text-canvas"
          >
            <Navigation size={16} /> Маршрут до корпуса
          </motion.button>
        </motion.div>
      )}
    </div>
  );
}
