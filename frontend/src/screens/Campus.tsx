/** Корпуса: адрес, как найти аудиторию, маршрут в картах. */

import { motion } from "framer-motion";
import { Layers, MapPin, Navigation, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Cover } from "@/components/cards";
import { CardSkeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { openExternal } from "@/shared/max";
import type { BuildingInfo } from "@/shared/types";

export default function Campus() {
  const [items, setItems] = useState<BuildingInfo[] | null>(null);
  const [room, setRoom] = useState("");
  const toast = useToast();

  useEffect(() => {
    api
      .buildings()
      .then(setItems)
      .catch((e) => toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить корпуса"));
  }, [toast]);

  // «Где ауд. 412?» — первая цифра номера аудитории в ИГУ означает этаж
  const hint = useMemo(() => {
    const m = room.trim().match(/^(\d)(\d{1,2})[а-яa-z]?$/i);
    if (!m) return null;
    return `${m[1]} этаж, аудитория ${room.trim()}. Лестница и лифт — у центрального входа.`;
  }, [room]);

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-5 px-1">
        <h1 className="mb-1">Корпуса</h1>
        <p className="text-[14px] text-muted">Где что находится и как добраться</p>
      </header>

      <div className="reveal mb-6 rounded-[24px] bg-surface p-4 shadow-lift">
        <label className="flex items-center gap-3 rounded-[14px] bg-field px-4 py-3">
          <Search size={18} className="text-muted" />
          <input
            value={room}
            onChange={(e) => setRoom(e.target.value)}
            inputMode="numeric"
            placeholder="Номер аудитории, например 412"
            className="w-full bg-transparent text-[16px] text-ink outline-none placeholder:text-faint"
          />
        </label>
        {hint && (
          <motion.p
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 flex items-start gap-2 px-1 text-[14px] text-ink-soft"
          >
            <Layers size={16} className="mt-0.5 shrink-0 text-accent" />
            {hint}
          </motion.p>
        )}
      </div>

      {!items ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : (
        items.map((b) => (
          <div key={b.code} className="reveal mb-4 overflow-hidden rounded-[28px] bg-surface shadow-lift">
            <div className="relative h-[150px]">
              <Cover src={b.cover_url} title={b.name} />
              <div className="absolute inset-0 bg-gradient-to-t from-black/75 to-transparent" />
              <div className="absolute inset-x-0 bottom-0 p-4">
                <p className="text-[22px] leading-tight font-[700] text-white">{b.name}</p>
                <p className="flex items-center gap-1 text-[13px] text-white/75">
                  <MapPin size={13} /> {b.address}
                </p>
              </div>
            </div>
            <div className="p-4">
              <p className="mb-4 text-[14px] leading-relaxed text-ink-soft">{b.hint}</p>
              <div className="flex items-center justify-between">
                <span className="text-[13px] text-muted">{b.floors} этажей</span>
                <motion.button
                  whileTap={{ scale: 0.96 }}
                  onClick={() => openExternal(b.map_url)}
                  className="flex items-center gap-2 rounded-full bg-ink px-4 py-2.5 text-[14px] font-semibold text-canvas"
                >
                  <Navigation size={15} /> Маршрут
                </motion.button>
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
