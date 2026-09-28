/** Рабочее место деканата: очередь заявок и выдача документов.
 *
 *  Без этого экрана заявки выглядят формой в никуда. Демонстрация в две
 *  стороны — студент подаёт, сотрудник выдаёт, студенту приходит PDF —
 *  и есть главный аргумент продукта. */

import { AnimatePresence, motion } from "framer-motion";
import { Inbox, Lock, ScanLine, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { RequestCard } from "@/components/cards";
import { DemoDeanButton } from "@/components/demo-dean";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { Card, CardSkeleton, Chip, Divider, Empty } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { CampusRequest, Me, TicketCheck } from "@/shared/types";
import { cn, dateTimeRu, haptic, payloadRows, STATUS_TITLES } from "@/shared/utils";

const FILTERS = [
  { key: "", label: "Все в работе" },
  { key: "SUBMITTED", label: "Новые" },
  { key: "IN_REVIEW", label: "В работе" },
  { key: "SIGNING", label: "На подписи" },
  { key: "READY", label: "Готовы" },
];

export default function Staff({ me, onChange }: { me: Me; onChange: (me: Me) => void }) {
  // Отдельные компоненты, а не ранний return: у стола деканата свои хуки,
  // и при включении роли их число поменялось бы посреди жизни экрана
  return me.staff ? <StaffDesk me={me} /> : <StaffLocked me={me} onChange={onChange} />;
}

/** Не сотрудник: вместо пустой очереди (сервер ответил бы 403) — что это за
 *  раздел и как в него попасть. Демо-профилю — роль в один тап. */
function StaffLocked({ me, onChange }: { me: Me; onChange: (me: Me) => void }) {
  const navigate = useNavigate();
  const demo = !!me.student?.is_demo;

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-4 px-1">
        <h1 className="mb-1">Деканат</h1>
      </header>
      <Card>
        <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-surface-raised text-muted">
          <Lock size={20} />
        </span>
        <p className="mb-1 text-[17px] font-semibold text-ink">Раздел для сотрудников</p>
        <p className="mb-5 text-[14px] leading-relaxed text-muted">
          Здесь очередь заявок: сотрудник принимает заявку, передаёт на подпись и выдаёт
          документ, а студент получает его файлом в чат. Типовые справки выдаются
          автоматически и в очередь не попадают.
        </p>
        {demo ? (
          <>
            <DemoDeanButton onDone={onChange} />
            <p className="mt-3 text-center text-[12px] text-faint">
              Демо: в очереди будут только ваши заявки
            </p>
          </>
        ) : (
          <Button full variant="soft" onClick={() => navigate("/profile")}>
            Ввести служебный код в профиле
          </Button>
        )}
      </Card>
    </div>
  );
}

function StaffDesk({ me }: { me: Me }) {
  const [items, setItems] = useState<CampusRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [active, setActive] = useState<CampusRequest | null>(null);
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.staffQueue(filter || undefined));
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить очередь");
    } finally {
      setLoading(false);
    }
  }, [filter, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-4 px-1">
        <h1 className="mb-1">Деканат</h1>
        <p className="text-[14px] text-muted">
          {me.staff?.full_name} · {me.staff?.department}
        </p>
        {me.student?.is_demo && (
          <p className="mt-1 text-[12px] text-faint">Демо-роль: в очереди только ваши заявки</p>
        )}
      </header>

      <TicketChecker />

      <div className="no-scrollbar mb-5 flex gap-2 overflow-x-auto px-1 pb-1">
        {FILTERS.map((f) => (
          <Chip key={f.key} active={filter === f.key} onClick={() => setFilter(f.key)}>
            {f.label}
          </Chip>
        ))}
      </div>

      {loading ? (
        <>
          <CardSkeleton />
          <div className="h-3" />
          <CardSkeleton />
        </>
      ) : items.length === 0 ? (
        <Empty
          icon={<Inbox size={34} strokeWidth={1.5} />}
          title="Очередь пуста"
          hint="Новые заявки появятся здесь сразу после отправки студентом. Типовые справки выдаются автоматически и в очередь не попадают."
        />
      ) : (
        items.map((r) => (
          <RequestCard key={r.id} request={r} showStudent onClick={() => setActive(r)} />
        ))
      )}

      <StaffSheet
        request={active}
        onClose={() => setActive(null)}
        onUpdated={(updated) => {
          setActive(updated);
          void load();
        }}
      />
    </div>
  );
}

function StaffSheet({
  request,
  onClose,
  onUpdated,
}: {
  request: CampusRequest | null;
  onClose: () => void;
  onUpdated: (r: CampusRequest) => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [askInfo, setAskInfo] = useState(false);
  const toast = useToast();

  useEffect(() => {
    setComment("");
    setAskInfo(false);
  }, [request?.public_no]);

  if (!request) return null;

  const run = async (action: string, fn: () => Promise<CampusRequest>, okText: string) => {
    setBusy(action);
    try {
      onUpdated(await fn());
      toast.ok(okText);
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось выполнить");
    } finally {
      setBusy(null);
    }
  };

  const transition = (to: string, text: string, c = "") =>
    run(to, () => api.staffTransition(request.public_no, to, c), text);

  const canAccept = request.status === "SUBMITTED";
  const canSign = request.status === "IN_REVIEW";
  const canIssue = ["SIGNING", "READY"].includes(request.status);
  const isOpen = !["ISSUED", "REJECTED", "CANCELLED"].includes(request.status);

  return (
    <Sheet open onClose={onClose} title={request.title}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Chip tone="soft">№{request.public_no}</Chip>
        <Chip tone="accent">{request.status_title}</Chip>
      </div>

      <p className="mb-1 text-[16px] font-semibold text-ink">{request.student_name}</p>
      <p className="mb-5 text-[13px] text-muted">
        {request.student_group} · подана {dateTimeRu(request.created_at)}
      </p>

      {Object.keys(request.payload).length > 0 && (
        <>
          <p className="mb-2 text-[13px] font-semibold text-muted">Данные заявки</p>
          <div className="mb-5 flex flex-col gap-2 rounded-[16px] bg-field p-4">
            {payloadRows(request).map((row) => (
              <div key={row.key} className="flex items-baseline justify-between gap-4">
                <span className="max-w-[55%] text-[13px] text-faint">{row.label}</span>
                <span className="text-right text-[14px] text-ink">{row.value}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="mb-2 text-[13px] font-semibold text-muted">История</p>
      <div className="mb-6 flex flex-col gap-1.5">
        {request.events.map((e, i) => (
          <div key={i} className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="text-ink">{STATUS_TITLES[e.to_status] ?? e.to_status}</span>
            <span className="shrink-0 text-faint">{e.actor_name || "—"}</span>
          </div>
        ))}
      </div>

      {request.document && (
        <div className="mb-5 rounded-[16px] bg-ok/10 p-4">
          <p className="text-[14px] font-semibold text-ok">Документ выдан</p>
          <p className="text-[13px] text-muted">{request.document.file_name}</p>
        </div>
      )}

      {isOpen && (
        <>
          <Divider className="mb-5" />

          {askInfo ? (
            <>
              <p className="mb-2 text-[13px] font-semibold text-muted">
                Что нужно уточнить у студента
              </p>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={3}
                placeholder="Например: приложите справку из соцзащиты"
                className="mb-3 w-full resize-none rounded-[16px] bg-field px-4 py-3 text-[15px] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
              />
              <Button
                full
                loading={busy === "NEEDS_INFO"}
                onClick={() =>
                  comment.trim()
                    ? transition("NEEDS_INFO", "Запрос отправлен студенту", comment.trim())
                    : toast.error("Напишите, что уточнить")
                }
              >
                <Send size={16} /> Запросить уточнение
              </Button>
              <Button variant="ghost" full className="mt-2" onClick={() => setAskInfo(false)}>
                Назад
              </Button>
            </>
          ) : (
            <div className="flex flex-col gap-2">
              {canAccept && (
                <Button
                  full
                  loading={busy === "IN_REVIEW"}
                  onClick={() => transition("IN_REVIEW", "Заявка принята в работу")}
                >
                  Принять в работу
                </Button>
              )}
              {canSign && (
                <Button
                  full
                  loading={busy === "SIGNING"}
                  onClick={() => transition("SIGNING", "Передано на подпись")}
                >
                  Передать на подпись
                </Button>
              )}
              {canIssue && (
                <Button
                  full
                  loading={busy === "issue"}
                  onClick={() =>
                    run(
                      "issue",
                      () => api.staffIssue(request.public_no),
                      "Документ выдан и отправлен студенту",
                    )
                  }
                >
                  Выдать документ
                </Button>
              )}

              <Button variant="outline" full onClick={() => setAskInfo(true)}>
                Запросить уточнение
              </Button>
              <Button
                variant="danger"
                full
                loading={busy === "REJECTED"}
                onClick={() => transition("REJECTED", "Заявка отклонена", comment)}
              >
                Отклонить
              </Button>
            </div>
          )}
        </>
      )}
    </Sheet>
  );
}

/** Проверка билета на входе: код с экрана студента — отметка о проходе. */
function TicketChecker() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<TicketCheck | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const check = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.checkTicket(code));
      setCode("");
      haptic();
    } catch (e) {
      setError(e instanceof ApiException ? e.message : "Не удалось проверить билет");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-5 rounded-[24px] border border-hairline-soft bg-surface p-4 shadow-lift">
      <p className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold text-ink">
        <ScanLine size={18} className="text-accent" /> Проверка билетов
      </p>
      <div className="flex gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && code.length > 3 && void check()}
          placeholder="Код, например T12-ABCDE"
          className="min-w-0 flex-1 rounded-[14px] bg-field px-4 py-3 font-mono text-[15px] text-ink outline-none placeholder:font-sans placeholder:text-faint"
        />
        <Button onClick={check} disabled={code.length < 4} loading={busy}>
          Отметить
        </Button>
      </div>
      <AnimatePresence mode="popLayout">
        {(result || error) && (
          <motion.div
            key={result ? `ok-${result.holder}` : `err-${error}`}
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0 }}
            className={cn(
              "mt-3 rounded-[14px] px-4 py-3 text-[14px] leading-snug",
              error ? "bg-danger/10 text-danger" : result?.already ? "bg-warn/10 text-warn" : "bg-ok/10 text-ok",
            )}
          >
            {error ||
              (result &&
                `${result.already ? "Уже проходил(а): " : "✓ Проход отмечен: "}${result.holder}, ${result.group_name} — ${result.event_title}`)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
