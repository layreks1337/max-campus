/** Главная — ближайшая пара, справка файлом в чат, афиша событий и конкурсов,
 *  активные заявки, рекомендации, вход в матчинг. */

import { ArrowRight, ChevronRight, Sparkles, Users } from "lucide-react";
import { AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Afisha, ItemOverlay, type Item, opportunityItem } from "@/components/afisha";
import {
  DayTimeline,
  LinkRow,
  NowCard,
  NowCardSkeleton,
  PollCard,
  QuickActions,
} from "@/components/campus";
import { OpportunityCard, RequestCard, shortFaculty } from "@/components/cards";
import { Button } from "@/components/ui/button";
import { GlassIcon } from "@/components/ui/glass-icon";
import { Card, CardSkeleton, Chip, Empty, Section } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Group, Home as HomeData, Me, Poll, Today } from "@/shared/types";
import { plural } from "@/shared/utils";

export default function Home({ me }: { me: Me }) {
  const [data, setData] = useState<HomeData | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const toast = useToast();

  const [today, setToday] = useState<Today | null>(null);
  const [todayLoading, setTodayLoading] = useState(true);
  const [group, setGroup] = useState<Group | null>(null);

  const load = useCallback(async () => {
    // Учебные блоки грузятся отдельно: их сбой не должен ронять всю главную
    api
      .today()
      .then(setToday)
      .catch(() => setToday(null))
      .finally(() => setTodayLoading(false));
    api.group().then(setGroup).catch(() => setGroup(null));
    try {
      setData(await api.home());
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить главную");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const student = me.student;
  const [openRec, setOpenRec] = useState<{ index: number; key: string } | null>(null);
  const recItems = useMemo<Item[]>(
    () => (data?.recommended ?? []).slice(0, 3).map(opportunityItem),
    [data],
  );
  const updateRec = (next: Item) => {
    if (next.kind !== "opportunity") return;
    setData((d) =>
      d
        ? {
            ...d,
            recommended: d.recommended.map((o) => (o.id === next.opportunity.id ? next.opportunity : o)),
          }
        : d,
    );
  };
  // На главной — самый свежий опрос, на который ещё не ответили
  const openPoll = group?.polls.find((p) => p.my_vote === null) ?? null;
  const replacePoll = (p: Poll) =>
    setGroup((g) => (g ? { ...g, polls: g.polls.map((x) => (x.id === p.id ? p : x)) } : g));

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-6 flex items-start justify-between gap-4 px-1">
        <div className="min-w-0">
          <h1 className="mb-1 text-[30px] leading-tight">
            {data?.greeting ?? `${greetingNow()}, ${student?.first_name ?? ""}`}
          </h1>
          {student && (
            <p className="truncate text-[14px] text-muted">
              {student.group_name} · {student.course}{" "}
              {plural(student.course, "курс", "курса", "курсов")} ·{" "}
              {shortFaculty(student.faculty)}
            </p>
          )}
        </div>
        <button
          onClick={() => navigate("/profile")}
          aria-label="Профиль"
          className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-raised text-[16px] font-semibold text-ink"
        >
          {me.photo_url ? (
            <img src={me.photo_url} alt="" className="h-full w-full object-cover" />
          ) : (
            (student?.first_name ?? me.display_name).slice(0, 1).toUpperCase()
          )}
        </button>
      </header>

      {today ? <NowCard today={today} /> : todayLoading && <NowCardSkeleton />}
      <CertificateCard />
      <QuickActions />

      <Afisha />

      {today && today.items.length > 0 && (
        <Section title="Сегодня">
          <DayTimeline today={today} />
        </Section>
      )}

      {openPoll && (
        <Section
          title="Группа спрашивает"
          action={<LinkRow label="все" onClick={() => navigate("/group")} />}
        >
          <PollCard
            poll={openPoll}
            onChange={replacePoll}
            onError={(m) => toast.error(m)}
          />
        </Section>
      )}

      {loading ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : (
        <>
          {data && data.active_requests.length > 0 && (
            <Section
              title="Мои заявки"
              action={
                <button
                  onClick={() => navigate("/requests")}
                  className="flex items-center gap-0.5 text-[14px] text-muted"
                >
                  все <ChevronRight size={15} />
                </button>
              }
            >
              {data.active_requests.map((r) => (
                <RequestCard
                  key={r.id}
                  request={r}
                  onClick={() => navigate(`/requests/${r.public_no}`)}
                />
              ))}
            </Section>
          )}

          {data && data.recommended.length > 0 && (
            <Section
              title="Стоит посмотреть"
              action={
                <Chip tone="accent">
                  <Sparkles size={12} /> подбор
                </Chip>
              }
            >
              {data.recommended.slice(0, 3).map((o, i) => (
                <OpportunityCard
                  key={o.id}
                  opportunity={o}
                  layoutId={`rec-o${o.id}`}
                  hidden={openRec?.index === i && openRec.key === `o${o.id}`}
                  onClick={() => setOpenRec({ index: i, key: `o${o.id}` })}
                />
              ))}
            </Section>
          )}

          {data && (
            <Section title="Люди">
              <Card onClick={() => navigate("/people")}>
                <div className="flex items-center gap-4">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
                    <Users size={22} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="mb-0.5 text-[16px] font-semibold text-ink">
                      {data.deck_size > 0
                        ? `${data.deck_size} ${plural(data.deck_size, "объявление", "объявления", "объявлений")} рядом`
                        : "Найти своих"}
                    </p>
                    <p className="text-[13px] leading-snug text-muted">
                      {data.new_matches > 0
                        ? `${data.new_matches} ${plural(data.new_matches, "отклик", "отклика", "откликов")} · напарники, наставники, попутчики`
                        : "Напарники по учёбе, наставники, попутчики"}
                    </p>
                  </div>
                  <ChevronRight size={18} className="shrink-0 text-faint" />
                </div>
              </Card>
            </Section>
          )}

          {data &&
            data.active_requests.length === 0 &&
            data.upcoming_events.length === 0 &&
            data.recommended.length === 0 && (
              <Empty
                title="Пока тихо"
                hint="Событий и заявок нет. Можно оформить справку или заглянуть в раздел «Люди»."
              />
            )}
        </>
      )}

      <AnimatePresence>
        {openRec && recItems.length > 0 && (
          <ItemOverlay
            items={recItems}
            index={openRec.index}
            prefix="rec"
            onIndex={(index) => setOpenRec((o) => (o ? { ...o, index } : o))}
            onClose={() => setOpenRec(null)}
            onChange={updateRec}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

/** То же приветствие, что считает сервер (по Иркутску, UTC+8), — пока грузится
 *  главная. Раньше здесь было «Привет, Анна», и через секунду заголовок
 *  менялся на «Доброе утро, Анна» с переносом на вторую строку. */
function greetingNow(): string {
  const hour = new Date(Date.now() + 8 * 3600_000).getUTCHours();
  if (hour >= 5 && hour < 12) return "Доброе утро";
  if (hour >= 12 && hour < 18) return "Добрый день";
  if (hour >= 18 && hour < 23) return "Добрый вечер";
  return "Доброй ночи";
}

/** Главный сценарий продукта — сразу под ближайшей парой, а не в конце ленты:
 *  раньше карточка «Нужна справка?» стояла ~1300 px ниже и только при пустом
 *  списке заявок. Ведёт прямо в форму справки об обучении — она типовая
 *  и выдаётся автоматически (решение 059). */
function CertificateCard() {
  const navigate = useNavigate();
  return (
    <Card className="mb-3">
      <div className="mb-4 flex items-start gap-4">
        <GlassIcon template="study_certificate" size={56} />
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[22px] leading-[1.15] font-[700] text-ink">
            Справка — <span className="whitespace-nowrap">файлом в чат</span>
          </p>
          <p className="text-[14px] leading-snug text-muted">
            Справка об обучении выдаётся сразу: PDF придёт в чат MAX, в деканат идти не нужно.
          </p>
        </div>
      </div>
      {/* Две кнопки в ряд на экране 360 px переносили подпись на вторую строку */}
      <Button full onClick={() => navigate("/requests/new/study_certificate")}>
        Справка об обучении <ArrowRight size={16} />
      </Button>
      <button
        onClick={() => navigate("/requests/new")}
        className="mt-3 w-full text-center text-[14px] text-muted"
      >
        Другие справки и заявления
      </button>
    </Card>
  );
}
