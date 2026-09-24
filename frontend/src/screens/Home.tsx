/** Главная — лента: активные заявки, ближайшие события, рекомендации, вход в матчинг. */

import { ArrowRight, ChevronRight, Sparkles, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EventCard, OpportunityCard, RequestCard, shortFaculty } from "@/components/cards";
import { Button } from "@/components/ui/button";
import { Card, CardSkeleton, Chip, Empty, Section } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Home as HomeData, Me } from "@/shared/types";
import { plural } from "@/shared/utils";

export default function Home({ me }: { me: Me }) {
  const [data, setData] = useState<HomeData | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const toast = useToast();

  const load = useCallback(async () => {
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

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="mb-7 flex items-start justify-between gap-4 px-1">
        <div className="min-w-0">
          <h1 className="mb-1 text-[30px] leading-tight">
            {data?.greeting ?? `Привет, ${student?.first_name ?? ""}`}
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

          {data && data.active_requests.length === 0 && (
            <Section title="Заявки">
              <Card>
                <p className="mb-1 text-[16px] font-semibold text-ink">
                  Нужна справка или заявление?
                </p>
                <p className="mb-4 text-[14px] leading-relaxed text-muted">
                  Оформляется за пару минут. Готовый документ придёт файлом в чат —
                  приходить в деканат не нужно.
                </p>
                <Button size="sm" onClick={() => navigate("/requests/new")}>
                  Оформить <ArrowRight size={15} />
                </Button>
              </Card>
            </Section>
          )}

          {data && data.upcoming_events.length > 0 && (
            <Section title="Ближайшее">
              {data.upcoming_events.map((e) => (
                <EventCard key={e.id} event={e} onClick={() => navigate("/")} />
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
              {data.recommended.slice(0, 3).map((o) => (
                <OpportunityCard key={o.id} opportunity={o} />
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
    </div>
  );
}
