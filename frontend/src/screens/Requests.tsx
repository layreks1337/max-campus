/** Список заявок студента. */

import { FileText, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { RequestCard } from "@/components/cards";
import { Button } from "@/components/ui/button";
import { CardSkeleton, Chip, Empty } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { deliversToChat } from "@/shared/max";
import type { CampusRequest } from "@/shared/types";

type Filter = "active" | "all";

export default function Requests() {
  const [items, setItems] = useState<CampusRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("active");
  const navigate = useNavigate();
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.requests(false));
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить заявки");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = filter === "active" ? items.filter((r) => r.is_active) : items;

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-5 flex items-center justify-between gap-3 px-1">
        <h1>Заявки</h1>
        <Button size="sm" onClick={() => navigate("/requests/new")}>
          <Plus size={16} /> Новая
        </Button>
      </header>

      <div className="mb-5 flex gap-2 px-1">
        <Chip active={filter === "active"} onClick={() => setFilter("active")}>
          В работе
        </Chip>
        <Chip active={filter === "all"} onClick={() => setFilter("all")}>
          Все
        </Chip>
      </div>

      {loading ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : visible.length === 0 ? (
        <Empty
          icon={<FileText size={34} strokeWidth={1.5} />}
          title={filter === "active" ? "Активных заявок нет" : "Заявок пока нет"}
          hint={`Справки, заявления на стипендию, общежитие и другие документы оформляются здесь. ${
            deliversToChat() ? "Готовый файл придёт в чат." : "Готовый файл — на экране заявки."
          }`}
          action={
            <Button onClick={() => navigate("/requests/new")}>Оформить заявку</Button>
          }
        />
      ) : (
        visible.map((r) => (
          <RequestCard
            key={r.id}
            request={r}
            onClick={() => navigate(`/requests/${r.public_no}`)}
          />
        ))
      )}
    </div>
  );
}
