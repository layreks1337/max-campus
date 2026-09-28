/** Выбор шаблона и заполнение формы.
 *
 *  Форма не свёрстана вручную: её рисует DynamicForm по schema_json шаблона.
 *  Поэтому новый тип справки появляется в приложении без правок фронтенда. */

import { ArrowLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { DynamicForm } from "@/components/DynamicForm";
import { GlassIcon } from "@/components/ui/glass-icon";
import { CardSkeleton, Chip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { deliversToChat } from "@/shared/max";
import type { Template } from "@/shared/types";
import { cn, plural } from "@/shared/utils";

export default function RequestNew() {
  const { key } = useParams<{ key: string }>();
  // Шаблон, выбранный в каталоге, приходит вместе с переходом: форма
  // открывается сразу, без мигания списка, пока шаблоны грузятся заново
  const picked = (useLocation().state as { template?: Template } | null)?.template;
  const preset = picked && picked.key === key ? picked : null;
  const [templates, setTemplates] = useState<Template[]>([]);
  const [active, setActive] = useState<Template | null>(preset);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<string>("Все");
  const navigate = useNavigate();
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const list = await api.templates();
      setTemplates(list);
      if (key) {
        const found = list.find((t) => t.key === key);
        if (found) setActive(found);
        else toast.error("Такой шаблон не найден");
      }
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить шаблоны");
    } finally {
      setLoading(false);
    }
  }, [key, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = useMemo(() => {
    const set = new Set(templates.map((t) => t.category));
    return ["Все", ...Array.from(set)];
  }, [templates]);

  const visible = useMemo(
    () =>
      templates.filter(
        (t) => t.key !== "support_question" && (category === "Все" || t.category === category),
      ),
    [templates, category],
  );

  if (active) {
    return (
      <div className="px-5 pb-2 safe-top">
        <button
          onClick={() => {
            // Пришли из каталога — просто шаг назад, иначе история копила бы
            // по лишней записи каталога на каждый просмотренный шаблон
            if (preset) navigate(-1);
            else navigate("/requests/new", { replace: true });
          }}
          className="mb-5 flex items-center gap-1.5 text-[14px] text-muted"
        >
          <ArrowLeft size={16} /> К списку
        </button>

        <div className="mb-6">
          <GlassIcon template={active.key} size={76} className="mb-4" />
          <h1 className="mb-2 text-[26px] leading-tight">{active.title}</h1>
          <p className="text-[15px] leading-relaxed text-muted">{active.description}</p>
          <p className="mt-3 text-[13px] text-faint">
            {/* Тестовому входу в браузере сервер в чат не пишет — файл только в заявке */}
            {active.auto_issue ? (
              deliversToChat() ? (
                "Типовая — выдаётся автоматически за секунды · PDF придёт файлом в чат"
              ) : (
                "Типовая — выдаётся автоматически за секунды · PDF — на экране заявки"
              )
            ) : (
              <>
                Обычно занимает {active.sla_days}{" "}
                {plural(active.sla_days, "день", "дня", "дней")}
                {active.produces_document &&
                  (deliversToChat() ? " · документ придёт файлом в чат" : " · документ — на экране заявки")}
              </>
            )}
          </p>
        </div>

        <DynamicForm
          template={active}
          onSubmitted={(created) => {
            // Выданную сразу справку празднует экран заявки после проигрывания шагов
            if (created.status !== "ISSUED") toast.ok("Заявка отправлена");
            // fresh: экран заявки проиграет шаги автовыдачи, а не покажет их разом
            navigate(`/requests/${created.public_no}`, { replace: true, state: { fresh: true } });
          }}
        />
      </div>
    );
  }

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="mb-5 px-1">
        <h1 className="mb-1">Что оформляем</h1>
        <p className="text-[14px] text-muted">
          {deliversToChat()
            ? "Заполняется в приложении, результат приходит в чат"
            : "Заполняется в приложении, результат — на экране заявки"}
        </p>
      </header>

      {categories.length > 2 && (
        <div className="no-scrollbar mb-5 flex gap-2 overflow-x-auto px-1 pb-1">
          {categories.map((c) => (
            <Chip key={c} active={category === c} onClick={() => setCategory(c)}>
              {c}
            </Chip>
          ))}
        </div>
      )}

      {loading ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : (
        <div className="flex flex-col gap-2">
          {visible.map((t) => (
            <button
              key={t.key}
              // Отдельный адрес формы, а не состояние экрана: на нём скрыто
              // нижнее меню (App.tsx), и системная «Назад» ведёт в каталог
              onClick={() => navigate(`/requests/new/${t.key}`, { state: { template: t } })}
              className={cn(
                "flex items-center gap-4 rounded-[20px] border border-hairline-soft",
                "bg-surface p-4 text-left shadow-lift transition-transform active:scale-[0.985]",
              )}
            >
              <GlassIcon template={t.key} size={48} />
              <span className="min-w-0 flex-1">
                <span className="mb-0.5 block text-[16px] leading-snug font-semibold text-ink">
                  {t.short_title}
                  {t.auto_issue && (
                    <span className="ml-2 inline-block rounded-full bg-ok/15 px-2 py-0.5 align-middle text-[11px] font-semibold text-ok">
                      сразу
                    </span>
                  )}
                </span>
                <span className="block truncate text-[13px] text-muted">{t.description}</span>
              </span>
              <ChevronRight size={17} className="shrink-0 text-faint" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
