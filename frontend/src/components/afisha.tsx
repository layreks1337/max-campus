/** Афиша главной: карусель обложек и полноэкранная карточка события.
 *
 *  События вуза и конкурсы идут одной лентой по дате. Карусель листается
 *  нативным scroll-snap — на телефоне это самый плавный и предсказуемый
 *  жест, — а масштаб, затемнение и параллакс обложек вычисляются из
 *  позиции прокрутки. Тап по центральной обложке раскрывает её на весь
 *  экран, дальше можно листать свайпом, не возвращаясь в карусель. */

import {
  AnimatePresence,
  motion,
  type MotionValue,
  type PanInfo,
  useMotionValueEvent,
  useScroll,
  useTransform,
} from "framer-motion";
import {
  ArrowRight,
  CalendarDays,
  Backpack,
  CalendarPlus,
  Gift,
  Navigation,
  QrCode,
  Share2,
  Star,
  UserCheck,
  UsersRound,
  Check,
  Clock,
  ExternalLink,
  MapPin,
  Trophy,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useLocation, useNavigate } from "react-router-dom";

import { Cover } from "@/components/cards";
import { Chip } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/sheet";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { openExternal, setBackButton } from "@/shared/max";
import type { CampusEvent, Details, Opportunity, Ticket } from "@/shared/types";
import {
  cn,
  dateRu,
  haptic,
  parseDate,
  plural,
  relativeDay,
  timeRu,
  universityDate,
} from "@/shared/utils";

/* ── Данные ────────────────────────────────────────────────────── */

export type Item =
  | { key: string; kind: "event"; date: string; event: CampusEvent }
  | { key: string; kind: "opportunity"; date: string; opportunity: Opportunity };

type Filter = "all" | "event" | "opportunity";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Всё" },
  { key: "event", label: "События" },
  { key: "opportunity", label: "Конкурсы" },
];

const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function titleOf(item: Item): string {
  return item.kind === "event" ? item.event.title : item.opportunity.title;
}

function coverOf(item: Item): string {
  return item.kind === "event" ? item.event.cover_url : item.opportunity.cover_url;
}

function tagOf(item: Item): string {
  return item.kind === "event" ? item.event.kind_title : item.opportunity.kind_title;
}

/** Строка под заголовком обложки: время и место или организатор. */
function subtitleOf(item: Item): string {
  if (item.kind === "event") {
    const e = item.event;
    return [timeRu(e.starts_at), e.location].filter(Boolean).join(" · ");
  }
  const o = item.opportunity;
  return [o.organizer, o.prize_text].filter(Boolean).join(" · ");
}

export function opportunityItem(o: Opportunity): Item {
  return { key: `o${o.id}`, kind: "opportunity", date: o.registration_deadline ?? "", opportunity: o };
}

function buildItems(events: CampusEvent[], opps: Opportunity[]): Item[] {
  const items: Item[] = [
    ...events.map((e) => ({ key: `e${e.id}`, kind: "event" as const, date: e.starts_at, event: e })),
    ...opps
      .filter((o) => o.registration_deadline && (o.days_left ?? 0) >= 0)
      .map((o) => ({
        key: `o${o.id}`,
        kind: "opportunity" as const,
        date: o.registration_deadline as string,
        opportunity: o,
      })),
  ];
  const now = Date.now() - 86_400_000;
  return items
    .filter((i) => (parseDate(i.date)?.getTime() ?? 0) >= now)
    .sort((a, b) => (parseDate(a.date)?.getTime() ?? 0) - (parseDate(b.date)?.getTime() ?? 0));
}

/** Дедлайн — янтарный: срок, который нельзя пропустить, а не очередное событие. */
const DEADLINE_GRADIENT = "linear-gradient(135deg,#7a5210 0%,#2a1c05 100%)";

function isDeadline(item: Item): boolean {
  return item.kind === "event" && item.event.kind === "DEADLINE";
}

/** Фон обложки без фото: у дедлайна свой, у остальных — по названию. */
function gradientOf(item: Item): string | undefined {
  return isDeadline(item) ? DEADLINE_GRADIENT : undefined;
}

/** Обложка: фото, а если его нет — типографский постер с крупным числом.
 *  Пустой градиент на весь экран выглядел как незагрузившаяся картинка.
 *
 *  Число стоит целиком внутри видимой рамки: в карусели обложка шире карточки
 *  на 40 px с каждой стороны (запас под параллакс), и раньше «2» обрезалась
 *  по краю, а над ней было «ОКТ · 18:00» без самого дня. */
function Art({ item, big }: { item: Item; big?: boolean }) {
  const cover = coverOf(item);
  if (cover) return <Cover src={cover} title={titleOf(item)} />;
  // День и месяц — по вузу, как время рядом (timeRu), а не по телефону
  const d = universityDate(item.date);
  const deadline = isDeadline(item);
  return (
    <>
      <Cover src="" title={titleOf(item)} gradient={gradientOf(item)} />
      <span
        aria-hidden
        className={cn(
          "absolute leading-none font-[800] tracking-tighter select-none",
          deadline ? "text-amber-200/[0.14]" : "text-white/[0.09]",
          big ? "top-[14%] right-5 text-[260px]" : "top-[16%] right-[52px] text-[170px]",
        )}
      >
        {d?.getUTCDate()}
      </span>
      <span
        aria-hidden
        className={cn(
          "absolute font-[750]",
          deadline ? "text-amber-300" : "text-white/60",
          big ? "top-24 left-5 text-[17px]" : "top-16 left-[60px] text-[14px]",
        )}
      >
        {d ? `${d.getUTCDate()} ${MONTHS_SHORT[d.getUTCMonth()]} · ${timeRu(item.date)}` : ""}
      </span>
    </>
  );
}

/* ── Афиша на главной ──────────────────────────────────────────── */

export function Afisha() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState<{ index: number; key: string } | null>(null);
  const toast = useToast();
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    Promise.all([api.events(60), api.opportunities()])
      .then(([ev, op]) => alive && setItems(buildItems(ev, op)))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, []);

  const visible = useMemo(
    () => (items ?? []).filter((i) => filter === "all" || i.kind === filter),
    [items, filter],
  );

  const updateItem = useCallback((next: Item) => {
    setItems((prev) => prev?.map((i) => (i.key === next.key ? next : i)) ?? prev);
  }, []);

  const location = useLocation();
  const deepLinked = (location.state as { openEvent?: number } | null)?.openEvent;
  useEffect(() => {
    if (!items || !deepLinked) return;
    const index = items.findIndex((i) => i.key === `e${deepLinked}`);
    if (index >= 0) {
      setFilter("all");
      setActive(index);
      setOpen({ index, key: items[index].key });
    }
    // Состояние навигации одноразовое: иначе событие раскрывалось бы при каждом возврате
    navigate(".", { replace: true, state: null });
  }, [items, deepLinked, navigate]);

  if (items === null) return <AfishaSkeleton />;
  if (items.length === 0) return null;

  const current = visible[Math.min(active, visible.length - 1)];

  return (
    <section className="relative mb-8">
      <div className="mb-3 px-1">
        <FilterPills
          value={filter}
          onChange={(f) => {
            setFilter(f);
            setActive(0);
          }}
        />
      </div>
      <div className="mb-1 px-1">
        <BigDate item={current} />
      </div>

      {visible.length === 0 ? (
        <p className="px-1 py-10 text-center text-[14px] text-muted">В этой категории пока пусто</p>
      ) : (
        <Carousel
          key={filter}
          items={visible}
          active={active}
          onActive={setActive}
          openKey={open?.key ?? null}
          onOpen={(index) => {
            haptic();
            setOpen({ index, key: visible[index].key });
          }}
        />
      )}

      <AnimatePresence>
        {open && (
          <Detail
            items={visible}
            index={open.index}
            openedKey={open.key}
            onIndex={(index) => {
              setOpen((o) => (o ? { ...o, index } : o));
              setActive(index);
            }}
            onClose={() => setOpen(null)}
            onChange={updateItem}
            onError={(m) => toast.error(m)}
            onApply={() => {
              setOpen(null);
              navigate("/requests/new");
            }}
          />
        )}
      </AnimatePresence>
    </section>
  );
}

/** Крупная дата активной обложки: цифры меняются вертикальной прокруткой. */
function BigDate({ item }: { item: Item | undefined }) {
  const d = universityDate(item?.date);
  const label = d ? `${d.getUTCDate()} ${MONTHS_SHORT[d.getUTCMonth()]}` : "";
  const caption = item
    ? item.kind === "event"
      ? relativeDay(item.date)
      : `приём заявок до`
    : "";

  return (
    <div className="min-w-0">
      <div className="relative h-[18px] overflow-hidden">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.p
            key={caption}
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -14, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 32 }}
            className="text-[13px] font-semibold text-muted"
          >
            {caption}
          </motion.p>
        </AnimatePresence>
      </div>
      <div className="relative h-[52px] overflow-hidden">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.p
            key={label}
            initial={{ y: 40, opacity: 0, filter: "blur(6px)" }}
            animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
            exit={{ y: -40, opacity: 0, filter: "blur(6px)" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="text-[46px] leading-[52px] font-[750] tracking-tight whitespace-nowrap text-ink uppercase"
          >
            {label}
          </motion.p>
        </AnimatePresence>
      </div>
    </div>
  );
}

function FilterPills({ value, onChange }: { value: Filter; onChange: (f: Filter) => void }) {
  return (
    <div className="inline-flex rounded-full bg-surface/70 p-1 backdrop-blur-md">
      {FILTERS.map((f) => (
        <button
          key={f.key}
          onClick={() => onChange(f.key)}
          className={cn(
            "relative rounded-full px-3 py-1.5 text-[12px] font-semibold transition-colors",
            value === f.key ? "text-canvas" : "text-muted",
          )}
        >
          {value === f.key && (
            <motion.span
              layoutId="afisha-filter"
              className="absolute inset-0 rounded-full bg-ink"
              transition={{ type: "spring", stiffness: 420, damping: 34 }}
            />
          )}
          <span className="relative">{f.label}</span>
        </button>
      ))}
    </div>
  );
}

/* ── Карусель ──────────────────────────────────────────────────── */

const GAP = 12;

function Carousel({
  items,
  active,
  onActive,
  openKey,
  onOpen,
}: {
  items: Item[];
  active: number;
  onActive: (i: number) => void;
  openKey: string | null;
  onOpen: (i: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const { scrollX } = useScroll({ container: ref });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const cardW = Math.min(Math.round(width * 0.7), 300);
  const step = cardW + GAP;
  const side = Math.max(0, (width - cardW) / 2);

  useMotionValueEvent(scrollX, "change", (x) => {
    if (!step) return;
    const i = Math.max(0, Math.min(items.length - 1, Math.round(x / step)));
    if (i !== active) {
      onActive(i);
      haptic();
    }
  });

  // Листание внутри раскрытой карточки: карусель за ней тихо догоняет,
  // чтобы после закрытия под пальцем оказалась та же обложка.
  useEffect(() => {
    const el = ref.current;
    if (!el || !step || !openKey) return;
    el.scrollTo({ left: active * step, behavior: "auto" });
  }, [active, openKey, step]);

  return (
    <div className="scroll-recede relative -mx-4">
      <Glow item={items[active]} />
      <div
        ref={ref}
        className="no-scrollbar flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain pt-2 pb-6"
        style={{ gap: GAP, paddingInline: side, scrollPaddingInline: side }}
      >
        {width > 0 &&
          items.map((item, i) => (
            <Poster
              key={item.key}
              item={item}
              index={i}
              step={step}
              width={cardW}
              scrollX={scrollX}
              hidden={openKey === item.key}
              onClick={() => {
                if (i === active) onOpen(i);
                else ref.current?.scrollTo({ left: i * step, behavior: "smooth" });
              }}
            />
          ))}
      </div>
      <Dots count={items.length} active={active} />
    </div>
  );
}

/** Размытое свечение цвета активной обложки позади карусели. */
function Glow({ item }: { item: Item | undefined }) {
  if (!item) return null;
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 top-6 bottom-10"
      // Маска вместо overflow: hidden — обрезка давала видимую прямую кромку
      style={{
        maskImage: "radial-gradient(closest-side, black 55%, transparent)",
        WebkitMaskImage: "radial-gradient(closest-side, black 55%, transparent)",
      }}
    >
      <AnimatePresence initial={false}>
        <motion.div
          key={item.key}
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.55 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="absolute inset-[12%] scale-110 blur-[48px] saturate-150"
        >
          <Cover src={coverOf(item)} title={titleOf(item)} gradient={gradientOf(item)} />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

function Poster({
  item,
  index,
  step,
  width,
  scrollX,
  hidden,
  onClick,
}: {
  item: Item;
  index: number;
  step: number;
  width: number;
  scrollX: MotionValue<number>;
  hidden: boolean;
  onClick: () => void;
}) {
  const range = [(index - 1) * step, index * step, (index + 1) * step];
  const scale = useTransform(scrollX, range, [0.86, 1, 0.86]);
  const y = useTransform(scrollX, range, [18, 0, 18]);
  const rotate = useTransform(scrollX, range, [4, 0, -4]);
  const dim = useTransform(scrollX, range, [0.45, 0, 0.45]);
  // Параллакс: снимок внутри рамки едет медленнее самой карточки
  const imageX = useTransform(scrollX, range, [-36, 0, 36]);

  return (
    <motion.button
      onClick={onClick}
      style={{ width, scale, y, rotate }}
      whileTap={{ scale: 0.96 }}
      className="relative shrink-0 snap-center text-left"
      aria-label={titleOf(item)}
    >
      <motion.div
        layoutId={`poster-${item.key}`}
        className={cn(
          "relative aspect-[3/4] w-full overflow-hidden rounded-[28px] shadow-[0_18px_40px_-12px_rgba(0,0,0,0.45)]",
          hidden && "invisible",
        )}
        transition={{ type: "spring", stiffness: 260, damping: 30 }}
      >
        <motion.div className="absolute -inset-x-10 inset-y-0" style={{ x: imageX }}>
          <Art item={item} />
        </motion.div>
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/15 to-black/5" />
        <motion.div className="absolute inset-0 bg-black" style={{ opacity: dim }} />

        <div className="absolute inset-x-0 top-0 flex flex-wrap gap-1.5 p-3.5">
          <Chip tone="overlay">{tagOf(item)}</Chip>
          {item.kind === "event" && item.event.my_status === "REGISTERED" && (
            <Chip tone="overlay">
              <Check size={12} /> Иду
            </Chip>
          )}
        </div>

        <div className="absolute inset-x-0 bottom-0 p-4">
          <p className="mb-1.5 line-clamp-3 text-[22px] leading-[1.08] font-[700] break-words text-white">
            {titleOf(item)}
          </p>
          <p className="truncate text-[13px] text-white/70">{subtitleOf(item)}</p>
        </div>
      </motion.div>
    </motion.button>
  );
}

function Dots({ count, active }: { count: number; active: number }) {
  if (count < 2) return null;
  return (
    <div className="flex justify-center gap-1.5">
      {Array.from({ length: count }, (_, i) => (
        <motion.span
          key={i}
          animate={{ width: i === active ? 18 : 6, opacity: i === active ? 1 : 0.35 }}
          transition={{ type: "spring", stiffness: 420, damping: 32 }}
          className="h-1.5 rounded-full bg-ink"
        />
      ))}
    </div>
  );
}

function AfishaSkeleton() {
  return (
    <section className="mb-8">
      <div className="shimmer mb-4 h-[64px] w-40 rounded-[16px] bg-surface-raised" />
      <div className="shimmer mx-auto aspect-[3/4] w-[70%] max-w-[300px] rounded-[28px] bg-surface-raised" />
    </section>
  );
}

/* ── Раскрытая карточка ────────────────────────────────────────── */

const SWIPE = 70;

function Detail({
  items,
  index,
  openedKey,
  onIndex,
  onClose,
  onChange,
  onError,
  onApply,
  prefix = "poster",
}: {
  items: Item[];
  index: number;
  openedKey: string;
  prefix?: string;
  onIndex: (i: number) => void;
  onClose: () => void;
  onChange: (item: Item) => void;
  onError: (message: string) => void;
  onApply: () => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [dir, setDir] = useState(0);
  // После первого свайпа обложка больше не связана с карточкой в карусели:
  // иначе новая обложка прилетала бы из-под затемнения, где её не видно.
  const [detached, setDetached] = useState(false);
  const item = items[index];

  const { scrollY } = useScroll({ container: scroller });
  const heroScale = useTransform(scrollY, [-120, 0], [1.18, 1]);
  const heroY = useTransform(scrollY, [0, 400], [0, 140]);
  const heroFade = useTransform(scrollY, [0, 320], [1, 0.35]);
  const barOpacity = useTransform(scrollY, [220, 320], [0, 1]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const off = setBackButton(onClose);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      off();
      setBackButton(null);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const go = (delta: number) => {
    const next = index + delta;
    if (next < 0 || next >= items.length) return;
    haptic();
    setDir(delta);
    setDetached(true);
    onIndex(next);
    scroller.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const onDragEnd = (_: unknown, info: PanInfo) => {
    if (info.offset.x < -SWIPE || info.velocity.x < -500) go(1);
    else if (info.offset.x > SWIPE || info.velocity.x > 500) go(-1);
  };

  const linked = !detached && item.key === openedKey;
  const next = items[index + 1];

  return (
    <motion.div
      initial={{ backgroundColor: "rgba(0,0,0,0)" }}
      animate={{ backgroundColor: "rgba(0,0,0,0.5)" }}
      exit={{ backgroundColor: "rgba(0,0,0,0)" }}
      className="fixed inset-0 z-[95]"
    >
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0, transition: { duration: 0.2 } }}
        className="absolute inset-0 bg-canvas"
      />

      {/* Плашка с названием появляется, когда обложка уехала за край */}
      <motion.div
        style={{ opacity: barOpacity }}
        className="pointer-events-none absolute inset-x-0 top-0 z-20 border-b border-hairline-soft bg-canvas/85 px-16 pt-[calc(env(safe-area-inset-top,0px)+14px)] pb-3 text-center backdrop-blur-md"
      >
        <p className="truncate text-[15px] font-semibold text-ink">{titleOf(item)}</p>
      </motion.div>

      <div className="absolute top-[calc(env(safe-area-inset-top,0px)+10px)] right-0 left-0 z-30 flex items-center justify-between px-4">
        <motion.button
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.6 }}
          onClick={onClose}
          aria-label="Закрыть"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-md"
        >
          <X size={20} />
        </motion.button>
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="rounded-full bg-black/45 px-3 py-1.5 text-[12px] font-semibold text-white tabular-nums backdrop-blur-md"
        >
          {index + 1} / {items.length}
        </motion.span>
      </div>

      <div ref={scroller} className="no-scrollbar relative z-10 h-full overflow-y-auto overscroll-contain">
        <div className="mx-auto w-full max-w-[560px]">
          <AnimatePresence initial={false} custom={dir} mode="popLayout">
            <motion.div
              key={item.key}
              custom={dir}
              variants={{
                enter: (d: number) => ({ x: d > 0 ? "60%" : "-60%", opacity: 0, scale: 0.94 }),
                center: { x: 0, opacity: 1, scale: 1 },
                exit: (d: number) => ({ x: d > 0 ? "-45%" : "45%", opacity: 0, scale: 0.94 }),
              }}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ type: "spring", stiffness: 260, damping: 30 }}
            >
              <motion.div
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.35}
                dragDirectionLock
                onDragEnd={onDragEnd}
                style={{ scale: heroScale, y: heroY, opacity: heroFade }}
                className="relative origin-bottom touch-pan-y"
              >
                <motion.div
                  layoutId={linked ? `${prefix}-${item.key}` : undefined}
                  transition={{ type: "spring", stiffness: 260, damping: 30 }}
                  className="relative h-[62vh] max-h-[560px] min-h-[340px] w-full overflow-hidden rounded-b-[32px]"
                >
                  <Art item={item} big />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/10 to-black/30" />
                  {/* Снизу 48 px: текст карточки наезжает на обложку на 28 px (-mt-7
                      в Body) и раньше срезал последнюю строку заголовка */}
                  <div className="absolute inset-x-0 bottom-0 px-5 pt-5 pb-12">
                    <div className="mb-3 flex flex-wrap gap-1.5">
                      <Chip tone="overlay">{tagOf(item)}</Chip>
                      <Chip tone="overlay">{relativeDay(item.date)}</Chip>
                    </div>
                    <p className="text-[30px] leading-[1.05] font-[750] break-words text-white">
                      {titleOf(item)}
                    </p>
                  </div>
                </motion.div>
              </motion.div>

              <Body item={item} onChange={onChange} onError={onError} onApply={onApply} />
            </motion.div>
          </AnimatePresence>

          {next && (
            <motion.button
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0, transition: { delay: 0.25 } }}
              onClick={() => go(1)}
              className="reveal mx-5 mt-2 mb-[calc(env(safe-area-inset-bottom,0px)+28px)] flex w-[calc(100%-40px)] items-center gap-3 overflow-hidden rounded-[20px] bg-surface-raised p-2.5 pr-4 text-left"
            >
              <span className="relative h-14 w-14 shrink-0 overflow-hidden rounded-[14px]">
                <Cover src={coverOf(next)} title={titleOf(next)} gradient={gradientOf(next)} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] font-semibold text-muted">Дальше · {dateRu(next.date)}</span>
                <span className="block truncate text-[15px] font-semibold text-ink">{titleOf(next)}</span>
              </span>
              <ArrowRight size={18} className="shrink-0 text-muted" />
            </motion.button>
          )}
          {!next && <div className="h-[calc(env(safe-area-inset-bottom,0px)+28px)]" />}
        </div>
      </div>
    </motion.div>
  );
}

/** Текст и действия под обложкой. Элементы въезжают лесенкой. */
function Body({
  item,
  onChange,
  onError,
  onApply,
}: {
  item: Item;
  onChange: (item: Item) => void;
  onError: (message: string) => void;
  onApply: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const rows: { icon: React.ReactNode; text: string }[] = [];
  let description = "";
  let action: React.ReactNode = null;

  if (item.kind === "event") {
    const e = item.event;
    description = e.description;
    rows.push({
      icon: <CalendarDays size={16} />,
      text: `${dateRu(e.starts_at)}, ${timeRu(e.starts_at)}${e.ends_at ? `–${timeRu(e.ends_at)}` : ""}`,
    });
    if (e.location) rows.push({ icon: <MapPin size={16} />, text: e.location });
    if (e.organizer_name) rows.push({ icon: <Users size={16} />, text: e.organizer_name });

    const registered = e.my_status === "REGISTERED" || e.my_status === "WAITLIST";
    const toggle = async () => {
      setBusy(true);
      try {
        const updated = registered ? await api.unregisterEvent(e.id) : await api.registerEvent(e.id);
        haptic();
        onChange({ ...item, event: updated });
      } catch (err) {
        onError(err instanceof ApiException ? err.message : "Не получилось, попробуйте ещё раз");
      } finally {
        setBusy(false);
      }
    };

    action = e.kind === "DEADLINE" ? (
      <ActionButton onClick={onApply} busy={false} done={false}>
        Подать заявление <ArrowRight size={18} />
      </ActionButton>
    ) : e.registration_required ? (
      <ActionButton onClick={toggle} busy={busy} done={registered}>
        {registered
          ? e.my_status === "WAITLIST"
            ? "Вы в листе ожидания · отменить"
            : "Вы записаны · отменить"
          : "Записаться"}
      </ActionButton>
    ) : (
      <p className="rounded-[16px] bg-surface-raised px-4 py-3 text-center text-[14px] text-muted">
        Регистрация не нужна — просто приходите
      </p>
    );
  } else {
    const o = item.opportunity;
    description = o.description;
    rows.push({
      icon: <Clock size={16} />,
      text:
        o.days_left === 0
          ? "Сегодня последний день приёма заявок"
          : `Заявки до ${dateRu(o.registration_deadline)} · ещё ${o.days_left} ${plural(o.days_left ?? 0, "день", "дня", "дней")}`,
    });
    rows.push({ icon: <Users size={16} />, text: `${o.organizer} · ${o.level_title}` });
    if (o.prize_text) rows.push({ icon: <Trophy size={16} />, text: o.prize_text });

    const going = o.my_interest === "GOING";
    const interested = o.my_interest !== null;
    const mark = async (level: "INTERESTED" | "GOING") => {
      setBusy(true);
      try {
        await api.setInterest(o.id, level);
        haptic();
        onChange({ ...item, opportunity: { ...o, my_interest: level } });
      } catch (err) {
        onError(err instanceof ApiException ? err.message : "Не получилось, попробуйте ещё раз");
      } finally {
        setBusy(false);
      }
    };

    action = (
      <>
        <div className="flex gap-2">
          <ActionButton onClick={() => mark("GOING")} busy={busy} done={going} disabled={going}>
            {going ? "Вы участвуете" : "Иду"}
          </ActionButton>
          {!going && (
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={() => mark("INTERESTED")}
              disabled={busy || interested}
              className={cn(
                "flex h-14 shrink-0 items-center gap-1.5 rounded-full px-5 text-[15px] font-semibold",
                interested ? "bg-accent/15 text-accent" : "bg-surface-raised text-ink",
              )}
            >
              {interested ? <Check size={17} /> : <Star size={17} />}
              {interested ? "В избранном" : "Интересно"}
            </motion.button>
          )}
          {o.url && (
            <button
              onClick={() => openExternal(o.url)}
              aria-label="Открыть сайт"
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-surface-raised text-ink"
            >
              <ExternalLink size={20} />
            </button>
          )}
        </div>
        {o.team_size_max > 1 && <TeamButton opportunity={o} onError={onError} />}
      </>
    );
  }

  const capacity =
    item.kind === "event" && item.event.capacity > 0
      ? { taken: item.event.taken, total: item.event.capacity }
      : null;

  const stagger = (i: number) => ({
    initial: { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { delay: 0.12 + i * 0.05, type: "spring" as const, stiffness: 300, damping: 30 },
  });

  return (
    // Текст наезжает на обложку снизу, а не обложка на текст: при параллаксе
    // обложка уходит медленнее прокрутки и иначе перекрывала бы первые строки
    <div className="relative z-10 -mt-7 rounded-t-[28px] bg-canvas px-5 pt-7">
      <div className="mb-5 space-y-2.5">
        {rows.map((r, i) => (
          <motion.p key={i} {...stagger(i)} className="flex items-start gap-3 text-[15px] text-ink-soft">
            <span className="mt-0.5 shrink-0 text-muted">{r.icon}</span>
            {r.text}
          </motion.p>
        ))}
      </div>

      {capacity && (
        <motion.div {...stagger(rows.length)} className="mb-5">
          <div className="mb-1.5 flex justify-between text-[13px] text-muted">
            <span>Записались</span>
            <span className="tabular-nums">
              {capacity.taken} из {capacity.total}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-raised">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, (capacity.taken / capacity.total) * 100)}%` }}
              transition={{ delay: 0.35, duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
              className={cn(
                "h-full rounded-full",
                capacity.taken >= capacity.total ? "bg-warn" : "bg-accent",
              )}
            />
          </div>
        </motion.div>
      )}

      <motion.div {...stagger(rows.length + 1)} className="mb-6">
        {action}
        {item.kind === "event" && item.event.kind !== "DEADLINE" && (
          <EventExtras event={item.event} onError={onError} />
        )}
      </motion.div>

      {description && (
        <motion.p
          {...stagger(rows.length + 2)}
          className="mb-6 text-[16px] leading-relaxed whitespace-pre-line text-ink-soft"
        >
          {description}
        </motion.p>
      )}

      <DetailsBlock details={item.kind === "event" ? item.event.details : item.opportunity.details} />

      {item.kind === "opportunity" && item.opportunity.tags.length > 0 && (
        <motion.div {...stagger(rows.length + 3)} className="mb-6 flex flex-wrap gap-1.5">
          {item.opportunity.tags.map((t) => (
            <Chip key={t}>#{t}</Chip>
          ))}
        </motion.div>
      )}
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  busy,
  done,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  busy: boolean;
  done: boolean;
  disabled?: boolean;
}) {
  return (
    <motion.button
      onClick={onClick}
      disabled={busy || disabled}
      whileTap={{ scale: 0.97 }}
      layout
      className={cn(
        "flex h-14 flex-1 items-center justify-center gap-2 rounded-full px-6 text-[16px] font-semibold",
        done ? "bg-ok/15 text-ok" : "bg-ink text-canvas",
        busy && "opacity-60",
      )}
    >
      <AnimatePresence mode="popLayout" initial={false}>
        {done && (
          <motion.span
            key="check"
            initial={{ scale: 0, rotate: -45 }}
            animate={{ scale: 1, rotate: 0 }}
            exit={{ scale: 0 }}
          >
            <Check size={18} />
          </motion.span>
        )}
      </AnimatePresence>
      {children}
    </motion.button>
  );
}

/* ── Поделиться, календарь, билет ──────────────────────────────── */

function EventExtras({ event, onError }: { event: CampusEvent; onError: (m: string) => void }) {
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [note, setNote] = useState("");
  const registered = event.my_status === "REGISTERED" || event.my_status === "ATTENDED";

  const share = async () => {
    haptic();
    try {
      const res = await api.shareEvent(event.id);
      if (res.sent_to_chat) {
        setNote("Карточка пришла в чат с ботом — перешлите её в чат группы.");
        return;
      }
      // Вне мессенджера (или тестовый аккаунт) — системное меню «Поделиться»
      if (navigator.share) {
        await navigator.share({ title: event.title, text: res.text });
      } else {
        await navigator.clipboard?.writeText(res.text);
        setNote("Текст со ссылкой скопирован — вставьте его в чат группы.");
      }
    } catch (e) {
      if ((e as Error)?.name === "AbortError") return;
      onError(e instanceof ApiException ? e.message : "Не получилось поделиться");
    }
  };

  const openTicket = async () => {
    try {
      setTicket(await api.ticket(event.id));
      haptic();
    } catch (e) {
      onError(e instanceof ApiException ? e.message : "Билет не загрузился");
    }
  };

  return (
    <>
      {/* Без регистрации билета не бывает — неактивная кнопка только сбивала */}
      <div
        className={cn("mt-3 grid gap-2", event.registration_required ? "grid-cols-3" : "grid-cols-2")}
      >
        <ExtraButton icon={<Share2 size={18} />} label="Поделиться" onClick={share} />
        <ExtraButton
          icon={<CalendarPlus size={18} />}
          label="В календарь"
          onClick={() => openExternal(`${window.location.origin}/ics/event/${event.id}.ics`)}
        />
        {event.registration_required && (
          <ExtraButton
            icon={<QrCode size={18} />}
            label="Мой билет"
            onClick={openTicket}
            disabled={!registered}
          />
        )}
      </div>
      <AnimatePresence>
        {note && (
          <motion.p
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 rounded-[14px] bg-ok/10 px-4 py-3 text-[13px] leading-snug text-ok"
          >
            {note}
          </motion.p>
        )}
      </AnimatePresence>
      <Sheet open={ticket !== null} onClose={() => setTicket(null)} title="Билет">
        {ticket && <TicketView ticket={ticket} />}
      </Sheet>
    </>
  );
}

function ExtraButton({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <motion.button
      whileTap={disabled ? undefined : { scale: 0.95 }}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex flex-col items-center gap-1.5 rounded-[18px] bg-surface-raised py-3 text-[12px] font-semibold text-ink",
        disabled && "opacity-35",
      )}
    >
      {icon}
      {label}
    </motion.button>
  );
}

/** Билет с QR: код проверяет организатор на входе (экран «Деканат»). */
function TicketView({ ticket }: { ticket: Ticket }) {
  const used = ticket.status === "ATTENDED";
  return (
    <motion.div
      initial={{ rotateX: -25, opacity: 0, y: 20 }}
      animate={{ rotateX: 0, opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 24 }}
      style={{ transformPerspective: 900 }}
      className="mx-auto max-w-[320px] overflow-hidden rounded-[28px] bg-white text-black"
    >
      <div className="bg-black px-6 pt-6 pb-5 text-white">
        <p className="text-[12px] font-semibold tracking-[0.18em] uppercase opacity-60">Вход на событие</p>
        <p className="mt-1 text-[20px] leading-tight font-[700]">{ticket.event_title}</p>
        <p className="mt-2 text-[13px] opacity-70">
          {ticket.when}
          {ticket.location && ` · ${ticket.location}`}
        </p>
      </div>
      {/* Линия отрыва, как у настоящего билета */}
      <div className="relative h-0 border-t-2 border-dashed border-black/15">
        <span className="absolute -top-3 -left-3 h-6 w-6 rounded-full bg-canvas" />
        <span className="absolute -top-3 -right-3 h-6 w-6 rounded-full bg-canvas" />
      </div>
      <div className="px-6 pt-5 pb-6 text-center">
        <div
          className={cn("mx-auto w-[200px] [&_svg]:h-auto [&_svg]:w-full", used && "opacity-25")}
          dangerouslySetInnerHTML={{ __html: ticket.qr_svg }}
        />
        <p className="mt-3 font-mono text-[20px] font-bold tracking-[0.12em]">{ticket.code}</p>
        <p className="mt-1 text-[13px] text-black/55">{ticket.holder}</p>
        {used && <p className="mt-3 text-[14px] font-semibold text-[#1f9d55]">✓ Проход отмечен</p>}
      </div>
    </motion.div>
  );
}

/* ── Подробности: куда, что взять, как участвовать ─────────────── */

/** Блоки появляются по мере прокрутки: whileInView с once — анимация
 *  один раз, без повторов при прокрутке туда-обратно. */
function Reveal({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -40px 0px" }}
      transition={{ type: "spring", stiffness: 260, damping: 30 }}
      className="mb-6"
    >
      {children}
    </motion.div>
  );
}

/** Обычный регистр, а не капс: заголовок блока читается, а не кричит
 *  (правило docs/04-design.md). */
function BlockTitle({ children }: { children: React.ReactNode }) {
  return <p className="mb-3 text-[17px] leading-tight font-semibold text-ink">{children}</p>;
}

function DetailsBlock({ details }: { details: Details | undefined }) {
  if (!details || Object.keys(details).length === 0) return null;
  const d = details;
  const steps = d.steps ?? [];
  const mapUrl = d.address ? `https://yandex.ru/maps/?text=${encodeURIComponent(d.address)}` : "";

  return (
    <>
      {(d.place || d.when_text) && (
        <Reveal>
          <BlockTitle>Куда и когда</BlockTitle>
          <div className="rounded-[20px] bg-surface-raised p-4">
            {d.place && (
              <p className="flex items-start gap-3 text-[15px] font-semibold text-ink">
                <MapPin size={17} className="mt-0.5 shrink-0 text-accent" />
                <span>
                  {d.place}
                  {d.address && (
                    <span className="block text-[13px] font-normal text-muted">{d.address}</span>
                  )}
                </span>
              </p>
            )}
            {d.when_text && (
              <p className="mt-3 flex items-start gap-3 text-[14px] leading-snug text-ink-soft">
                <Clock size={17} className="mt-0.5 shrink-0 text-muted" />
                {d.when_text}
              </p>
            )}
            {d.format && (
              <span className="mt-3 inline-flex rounded-full bg-canvas px-3 py-1 text-[12px] font-semibold text-muted">
                {d.format}
              </span>
            )}
            {mapUrl && (
              <motion.button
                whileTap={{ scale: 0.97 }}
                onClick={() => openExternal(mapUrl)}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-full bg-ink py-3 text-[15px] font-semibold text-canvas"
              >
                <Navigation size={16} /> Маршрут
              </motion.button>
            )}
          </div>
        </Reveal>
      )}

      {steps.length > 0 && (
        <Reveal>
          <BlockTitle>Как участвовать</BlockTitle>
          <ol>
            {steps.map((step, i) => (
              <motion.li
                key={i}
                initial={{ opacity: 0, x: -14 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.08 * i, type: "spring", stiffness: 300, damping: 28 }}
                className="relative flex gap-3 pb-4 last:pb-0"
              >
                {i < steps.length - 1 && (
                  <span aria-hidden className="absolute top-8 bottom-0 left-[13px] w-px bg-hairline" />
                )}
                <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-[13px] font-bold text-white">
                  {i + 1}
                </span>
                <span className="pt-1 text-[15px] leading-snug text-ink-soft">{step}</span>
              </motion.li>
            ))}
          </ol>
        </Reveal>
      )}

      {d.bring && d.bring.length > 0 && (
        <ListCard title="Что взять" icon={<Backpack size={16} />} items={d.bring} />
      )}
      {d.requirements && d.requirements.length > 0 && (
        <ListCard title="Кого ждут" icon={<UserCheck size={16} />} items={d.requirements} />
      )}
      {d.perks && d.perks.length > 0 && (
        <ListCard title="Что получите" icon={<Gift size={16} />} items={d.perks} accent />
      )}

      {d.contact && (
        <Reveal>
          <BlockTitle>Контакт</BlockTitle>
          <div className="flex items-center gap-3 rounded-[20px] border border-hairline-soft p-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[16px] font-bold text-accent">
              {d.contact.name.slice(0, 1)}
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-semibold text-ink">{d.contact.name}</span>
              {d.contact.role && <span className="block text-[13px] text-muted">{d.contact.role}</span>}
              {d.contact.where && <span className="block text-[13px] text-faint">{d.contact.where}</span>}
            </span>
          </div>
        </Reveal>
      )}
    </>
  );
}

function ListCard({
  title,
  icon,
  items,
  accent,
}: {
  title: string;
  icon: React.ReactNode;
  items: string[];
  accent?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, margin: "0px 0px -30px 0px" }}
      transition={{ type: "spring", stiffness: 260, damping: 28 }}
      className={cn("mb-3 rounded-[20px] p-4", accent ? "bg-ok/10" : "bg-surface-raised")}
    >
      <p className={cn("mb-2 flex items-center gap-2 text-[14px] font-semibold", accent ? "text-ok" : "text-ink")}>
        {icon} {title}
      </p>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={i} className="flex gap-2 text-[14px] leading-snug text-ink-soft">
            <span className={cn("mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full", accent ? "bg-ok" : "bg-faint")} />
            {it}
          </li>
        ))}
      </ul>
    </motion.div>
  );
}

/** «Ищу команду» — объявление сразу попадает в колоду «Люди». */
function TeamButton({ opportunity, onError }: { opportunity: Opportunity; onError: (m: string) => void }) {
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const post = async () => {
    setBusy(true);
    try {
      await api.lookingForTeam(opportunity.id, "");
      haptic();
      setDone(true);
    } catch (e) {
      onError(e instanceof ApiException ? e.message : "Не удалось опубликовать");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence mode="wait" initial={false}>
      {done ? (
        <motion.button
          key="done"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={() => navigate("/people")}
          className="mt-3 flex w-full items-center justify-between rounded-[18px] bg-ok/10 px-4 py-3.5 text-left text-[14px] text-ok"
        >
          <span>
            <b>Объявление в колоде «Люди»</b>
            <span className="block text-[13px] opacity-80">Откликнувшиеся появятся во вкладке «Отклики»</span>
          </span>
          <ArrowRight size={18} className="shrink-0" />
        </motion.button>
      ) : (
        <motion.button
          key="post"
          whileTap={{ scale: 0.97 }}
          onClick={post}
          disabled={busy}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-[18px] border border-dashed border-hairline py-3.5 text-[14px] font-semibold text-ink"
        >
          <UsersRound size={17} /> Ищу команду ({opportunity.team_size_min}–{opportunity.team_size_max} чел.)
        </motion.button>
      )}
    </AnimatePresence>
  );
}

/* ── Раскрытие с других экранов ────────────────────────────────── */

/** Та же полноэкранная карточка, что у афиши, — для списков вне карусели.
 *  Обложка карточки-источника должна нести layoutId `${prefix}-${key}`. */
export function ItemOverlay({
  items,
  index,
  prefix,
  onIndex,
  onClose,
  onChange,
}: {
  items: Item[];
  index: number;
  prefix: string;
  onIndex: (i: number) => void;
  onClose: () => void;
  onChange: (item: Item) => void;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const [openedKey] = useState(items[index]?.key ?? "");
  return (
    <Detail
      items={items}
      index={index}
      openedKey={openedKey}
      prefix={prefix}
      onIndex={onIndex}
      onClose={onClose}
      onChange={onChange}
      onError={(m) => toast.error(m)}
      onApply={() => {
        onClose();
        navigate("/requests/new");
      }}
    />
  );
}
