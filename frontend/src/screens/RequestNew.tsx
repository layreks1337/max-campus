/** Выбор шаблона и заполнение формы.
 *
 *  Форма не свёрстана вручную: её рисует DynamicForm по schema_json шаблона.
 *  Поэтому новый тип справки появляется в приложении без правок фронтенда. */

import { ArrowLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { DynamicForm } from "@/components/DynamicForm";
import { GlassIcon } from "@/components/ui/glass-icon";
import { CardSkeleton, Chip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Template } from "@/shared/types";
import { cn, plural } from "@/shared/utils";

export default function RequestNew() {
  const { key } = useParams<{ key: string }>();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [active, setActive] = useState<Template | null>(null);
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
      <div className="px-5 pb-28 safe-top">
        <button
          onClick={() => {
            setActive(null);
            if (key) navigate("/requests/new", { replace: true });
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
            Обычно занимает {active.sla_days}{" "}
            {plural(active.sla_days, "день", "дня", "дней")}
            {active.produces_document && " · документ придёт файлом в чат"}
          </p>
        </div>

        <DynamicForm
          template={active}
          onSubmitted={(no) => {
            toast.ok("Заявка отправлена");
            navigate(`/requests/${no}`, { replace: true });
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
          Заполняется в приложении, результат приходит в чат
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
              onClick={() => setActive(t)}
              className={cn(
                "flex items-center gap-4 rounded-[20px] border border-hairline-soft",
                "bg-surface p-4 text-left shadow-lift transition-transform active:scale-[0.985]",
              )}
            >
              <GlassIcon template={t.key} size={48} />
              <span className="min-w-0 flex-1">
                <span className="mb-0.5 block text-[16px] leading-snug font-semibold text-ink">
                  {t.short_title}
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
