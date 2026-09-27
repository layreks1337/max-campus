/** Люди: колода объявлений, отклики, профиль знакомств.
 *
 *  Свайпаем объявления, а не людей — это лечит холодный старт (один человек
 *  создаёт несколько карточек), снимает вопрос модерации и даёт понятный
 *  повод написать. */

import { AnimatePresence, motion, useMotionValue, useTransform } from "framer-motion";
import { Check, MessageCircle, Plus, Users, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { IntentCard, shortFaculty } from "@/components/cards";
import { Button, IconButton } from "@/components/ui/button";
import { Card, Chip, Empty, Skeleton } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/sheet";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { openExternal } from "@/shared/max";
import type { Intent, Match, MatchProfile } from "@/shared/types";
import { cn, dateRu, haptic } from "@/shared/utils";

type Tab = "deck" | "matches" | "profile";

const KINDS = [
  { key: "STUDY_BUDDY", label: "Напарник по учёбе" },
  { key: "TEAM", label: "Команда на проект" },
  { key: "MENTOR", label: "Ищу наставника" },
  { key: "MENTEE", label: "Готов наставлять" },
  { key: "COMMUTE", label: "Попутчики" },
  { key: "HOBBY", label: "По интересам" },
];

export default function People() {
  const [tab, setTab] = useState<Tab>("deck");

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-4 px-1">
        <h1 className="mb-1">Люди</h1>
        {/* Безопасная среда — часть позиционирования: в колоде только студенты
            с привязкой к вузу, а @username виден лишь после взаимного отклика */}
        <p className="text-[14px] leading-snug text-muted">
          Только подтверждённые студенты вуза · контакт открывается при взаимном отклике
        </p>
      </header>

      <div className="mb-5 flex gap-2 px-1">
        <Chip active={tab === "deck"} onClick={() => setTab("deck")}>
          Колода
        </Chip>
        <Chip active={tab === "matches"} onClick={() => setTab("matches")}>
          Отклики
        </Chip>
        <Chip active={tab === "profile"} onClick={() => setTab("profile")}>
          О себе
        </Chip>
      </div>

      {tab === "deck" && <Deck />}
      {tab === "matches" && <Matches />}
      {tab === "profile" && <ProfileTab />}
    </div>
  );
}

/* ── Колода ────────────────────────────────────────────────────── */

function Deck() {
  const [cards, setCards] = useState<Intent[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCards(await api.deck());
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить колоду");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (intent: Intent, decision: "LIKE" | "SKIP") => {
    setCards((prev) => prev.filter((c) => c.id !== intent.id));
    try {
      const res = await api.swipe(intent.id, decision);
      if (res.matched) {
        toast.ok(`Взаимно! ${res.match_name ?? "Отклик"} — загляните в «Отклики»`);
      }
    } catch {
      /* свайп не критичен: повтор подтянется при следующей загрузке */
    }
  };

  if (loading) return <Skeleton className="h-[440px] w-full rounded-[24px]" />;

  if (cards.length === 0) {
    return (
      <>
        <Empty
          icon={<Users size={34} strokeWidth={1.5} />}
          title="Колода закончилась"
          hint="Ты посмотрел все объявления. Создай своё — его увидят другие студенты."
          action={<Button onClick={() => setCreateOpen(true)}>Создать объявление</Button>}
        />
        <CreateIntentSheet
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={load}
        />
      </>
    );
  }

  const top = cards[0];

  return (
    <>
      <div className="relative mb-6 h-[450px]">
        {/* Стопка: две карточки под верхней создают глубину */}
        {cards
          .slice(0, 3)
          .reverse()
          .map((card, idx, arr) => {
            const depth = arr.length - 1 - idx;
            const isTop = card.id === top.id;
            if (isTop) {
              return <SwipeCard key={card.id} intent={card} onDecide={decide} />;
            }
            return (
              <div
                key={card.id}
                className="absolute inset-0"
                style={{
                  transform: `scale(${1 - depth * 0.04}) translateY(${depth * 10}px)`,
                  opacity: 1 - depth * 0.35,
                  zIndex: 10 - depth,
                }}
              >
                <IntentCard intent={card} />
              </div>
            );
          })}
      </div>

      <div className="mb-6 flex items-center justify-center gap-5">
        <IconButton label="Пропустить" size={58} onClick={() => decide(top, "SKIP")}>
          <X size={24} className="text-muted" />
        </IconButton>
        <IconButton
          label="Откликнуться"
          size={64}
          variant="primary"
          onClick={() => decide(top, "LIKE")}
        >
          <Check size={26} />
        </IconButton>
      </div>

      <Button variant="soft" full onClick={() => setCreateOpen(true)}>
        <Plus size={16} /> Своё объявление
      </Button>

      <CreateIntentSheet
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={load}
      />
    </>
  );
}

function SwipeCard({
  intent,
  onDecide,
}: {
  intent: Intent;
  onDecide: (i: Intent, d: "LIKE" | "SKIP") => void;
}) {
  const x = useMotionValue(0);
  const rotate = useTransform(x, [-220, 220], [-14, 14]);
  const likeOpacity = useTransform(x, [30, 130], [0, 1]);
  const skipOpacity = useTransform(x, [-130, -30], [1, 0]);

  return (
    <motion.div
      className="absolute inset-0 z-20 cursor-grab active:cursor-grabbing"
      style={{ x, rotate }}
      drag="x"
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={0.7}
      onDragEnd={(_, info) => {
        if (info.offset.x > 110 || info.velocity.x > 700) {
          haptic();
          onDecide(intent, "LIKE");
        } else if (info.offset.x < -110 || info.velocity.x < -700) {
          haptic();
          onDecide(intent, "SKIP");
        }
      }}
    >
      <IntentCard intent={intent} />

      <motion.div
        style={{ opacity: likeOpacity }}
        className="pointer-events-none absolute top-7 left-6 rotate-[-12deg] rounded-[12px] border-2 border-ok px-3 py-1.5 text-[16px] font-[650] text-ok"
      >
        ОТКЛИК
      </motion.div>
      <motion.div
        style={{ opacity: skipOpacity }}
        className="pointer-events-none absolute top-7 right-6 rotate-[12deg] rounded-[12px] border-2 border-faint px-3 py-1.5 text-[16px] font-[650] text-faint"
      >
        ПРОПУСК
      </motion.div>
    </motion.div>
  );
}

/* ── Отклики ───────────────────────────────────────────────────── */

function Matches() {
  const [items, setItems] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .matches()
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton className="h-28 w-full rounded-[24px]" />;

  if (items.length === 0) {
    return (
      <Empty
        icon={<MessageCircle size={34} strokeWidth={1.5} />}
        title="Откликов пока нет"
        hint="Полистай колоду: когда интерес окажется взаимным, здесь появится контакт."
      />
    );
  }

  return (
    <>
      {items.map((m) => (
        <Card key={m.id} className="mb-3">
          <div className="flex items-center gap-3.5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-raised text-[17px] font-semibold text-ink">
              {m.partner_photo ? (
                <img src={m.partner_photo} alt="" className="h-full w-full object-cover" />
              ) : (
                m.partner_name.slice(0, 1).toUpperCase()
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="mb-0.5 flex items-center gap-2 text-[16px] font-semibold text-ink">
                <span className="truncate">{m.partner_name}</span>
                {m.origin === "BUDDY" && <Chip tone="accent">наставник</Chip>}
              </p>
              <p className="truncate text-[13px] text-muted">{m.about}</p>
              <p className="text-[12px] text-faint">{dateRu(m.created_at)}</p>
            </div>
          </div>

          {m.partner_username && (
            <Button
              variant="soft"
              size="sm"
              full
              className="mt-4"
              onClick={() => openExternal(`https://max.ru/${m.partner_username}`)}
            >
              <MessageCircle size={15} /> Написать @{m.partner_username}
            </Button>
          )}
        </Card>
      ))}
    </>
  );
}

/* ── Профиль знакомств ─────────────────────────────────────────── */

function ProfileTab() {
  const [profile, setProfile] = useState<MatchProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const toast = useToast();

  useEffect(() => {
    api
      .matchProfile()
      .then(setProfile)
      .catch(() => {});
  }, []);

  if (!profile) return <Skeleton className="h-64 w-full rounded-[24px]" />;

  const save = async (next: MatchProfile) => {
    setProfile(next);
    setSaving(true);
    try {
      await api.saveMatchProfile(next);
      toast.ok("Сохранено");
    } catch {
      toast.error("Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t || profile.tags.includes(t)) return;
    void save({ ...profile, tags: [...profile.tags, t] });
    setTagInput("");
  };

  return (
    <Card>
      <p className="mb-4 text-[13px] font-semibold text-muted">О себе</p>
      <textarea
        value={profile.bio}
        onChange={(e) => setProfile({ ...profile, bio: e.target.value })}
        onBlur={() => save(profile)}
        rows={3}
        placeholder="Пара строк: чем занимаешься, что ищешь"
        className="mb-5 w-full resize-none rounded-[16px] bg-field px-4 py-3 text-[15px] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
      />

      <p className="mb-2 text-[13px] font-semibold text-muted">Интересы и предметы</p>
      <div className="mb-3 flex flex-wrap gap-2">
        {profile.tags.map((t) => (
          <Chip
            key={t}
            tone="soft"
            onClick={() => save({ ...profile, tags: profile.tags.filter((x) => x !== t) })}
          >
            #{t} <X size={12} />
          </Chip>
        ))}
      </div>
      <div className="mb-6 flex gap-2">
        <input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addTag()}
          placeholder="Например: базы данных"
          className="h-11 flex-1 rounded-[14px] bg-field px-4 text-[14px] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
        />
        <Button size="sm" variant="soft" onClick={addTag}>
          <Plus size={15} />
        </Button>
      </div>

      <ToggleRow
        label="Хочу наставника"
        hint="Старшекурсник с твоего направления. Подбор автоматический."
        value={profile.wants_mentor}
        onChange={(v) => save({ ...profile, wants_mentor: v })}
      />
      <ToggleRow
        label="Готов наставлять"
        hint="Будешь помогать первокурсникам освоиться."
        value={profile.wants_mentee}
        onChange={(v) => save({ ...profile, wants_mentee: v })}
      />
      <ToggleRow
        label="Показывать меня в колоде"
        value={profile.visible}
        onChange={(v) => save({ ...profile, visible: v })}
      />

      {saving && <p className="mt-3 text-center text-[12px] text-faint">Сохраняю…</p>}
    </Card>
  );
}

function ToggleRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!value)}
      className="mb-3 flex w-full items-center justify-between gap-4 text-left"
    >
      <span className="min-w-0">
        <span className="block text-[15px] text-ink">{label}</span>
        {hint && <span className="block text-[12px] leading-snug text-faint">{hint}</span>}
      </span>
      <span
        className={cn(
          "relative h-7 w-12 shrink-0 rounded-full transition-colors",
          value ? "bg-accent" : "bg-surface-raised",
        )}
      >
        <span
          className={cn(
            "absolute top-1 h-5 w-5 rounded-full bg-white transition-all",
            value ? "left-6" : "left-1",
          )}
        />
      </span>
    </button>
  );
}

/* ── Создание объявления ───────────────────────────────────────── */

function CreateIntentSheet({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState("STUDY_BUDDY");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  const submit = async () => {
    if (title.trim().length < 3) {
      toast.error("Опишите, что ищете");
      return;
    }
    setSaving(true);
    try {
      await api.createIntent({ kind, title: title.trim(), description: description.trim(), tags: [] });
      toast.ok("Объявление опубликовано");
      setTitle("");
      setDescription("");
      onClose();
      onCreated();
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось опубликовать");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Новое объявление">
      <p className="mb-2 text-[13px] font-semibold text-muted">Что ищешь</p>
      <div className="mb-5 flex flex-wrap gap-2">
        {KINDS.map((k) => (
          <Chip key={k.key} active={kind === k.key} onClick={() => setKind(k.key)}>
            {k.label}
          </Chip>
        ))}
      </div>

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Ищу напарника на лабы по БД"
        maxLength={160}
        className="mb-3 h-12 w-full rounded-[16px] bg-field px-4 text-[15px] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={4}
        placeholder="Подробности: что уже знаешь, чем можешь помочь, когда удобно"
        className="mb-5 w-full resize-none rounded-[16px] bg-field px-4 py-3 text-[15px] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
      />

      <Button full loading={saving} onClick={submit}>
        Опубликовать
      </Button>
    </Sheet>
  );
}
