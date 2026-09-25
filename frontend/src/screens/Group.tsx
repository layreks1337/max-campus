/** Моя группа: опросы старосты. Староста создаёт опрос — бот пишет всем в чат. */

import { motion } from "framer-motion";
import { Crown, Plus, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PollCard } from "@/components/campus";
import { Button } from "@/components/ui/button";
import { Card, CardSkeleton, Empty } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/sheet";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Group as GroupData, Poll } from "@/shared/types";
import { plural } from "@/shared/utils";

export default function Group() {
  const [data, setData] = useState<GroupData | null>(null);
  const [creating, setCreating] = useState(false);
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      setData(await api.group());
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить группу");
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const replace = (p: Poll) =>
    setData((d) => (d ? { ...d, polls: d.polls.map((x) => (x.id === p.id ? p : x)) } : d));

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-5 px-1">
        <h1 className="mb-1">Группа {data?.group_name ?? ""}</h1>
        {data && (
          <p className="flex items-start gap-1.5 text-[14px] text-muted">
            <Users size={14} className="mt-[3px] shrink-0" />
            {data.members} {plural(data.members, "человек", "человека", "человек")} в приложении
            {data.head_name && ` · староста ${data.head_name}`}
          </p>
        )}
      </header>

      {data?.is_head && (
        <Card className="mb-5">
          <div className="flex items-center gap-4">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-warn/15 text-warn">
              <Crown size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[16px] font-semibold text-ink">Вы староста</p>
              <p className="text-[13px] leading-snug text-muted">
                Опрос уйдёт всей группе сообщением от бота — отвечать можно в один тап.
              </p>
            </div>
          </div>
          <Button full className="mt-4" onClick={() => setCreating(true)}>
            <Plus size={16} /> Новый опрос
          </Button>
        </Card>
      )}

      {!data ? (
        <CardSkeleton />
      ) : data.polls.length === 0 ? (
        <Empty title="Опросов пока нет" hint="Когда староста спросит группу, вопрос появится здесь." />
      ) : (
        data.polls.map((p) => (
          <PollCard key={p.id} poll={p} onChange={replace} onError={(m) => toast.error(m)} />
        ))
      )}

      <NewPoll
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(p) => {
          setData((d) => (d ? { ...d, polls: [p, ...d.polls] } : d));
          setCreating(false);
          toast.ok("Опрос отправлен группе");
        }}
      />
    </div>
  );
}

function NewPoll({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (p: Poll) => void;
}) {
  const [question, setQuestion] = useState("");
  const [options, setOptions] = useState(["Иду", "Не иду"]);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const submit = async () => {
    setBusy(true);
    try {
      onCreated(await api.createPoll(question, options.filter((o) => o.trim())));
      setQuestion("");
      setOptions(["Иду", "Не иду"]);
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось создать опрос");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Опрос для группы">
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Кто идёт на ярмарку объединений?"
        rows={2}
        className="mb-4 w-full resize-none rounded-[16px] bg-field px-4 py-3 text-[16px] text-ink outline-none placeholder:text-faint"
      />
      {options.map((o, i) => (
        <motion.div key={i} layout className="mb-2 flex items-center gap-2">
          <input
            value={o}
            onChange={(e) => setOptions(options.map((x, j) => (j === i ? e.target.value : x)))}
            placeholder={`Вариант ${i + 1}`}
            className="flex-1 rounded-[14px] bg-field px-4 py-3 text-[15px] text-ink outline-none placeholder:text-faint"
          />
          {options.length > 2 && (
            <button
              onClick={() => setOptions(options.filter((_, j) => j !== i))}
              aria-label="Убрать вариант"
              className="flex h-11 w-11 items-center justify-center text-faint"
            >
              <Trash2 size={17} />
            </button>
          )}
        </motion.div>
      ))}
      {options.length < 6 && (
        <button
          onClick={() => setOptions([...options, ""])}
          className="mb-5 flex items-center gap-1.5 px-1 text-[14px] font-semibold text-accent"
        >
          <Plus size={15} /> Добавить вариант
        </button>
      )}
      <Button
        className="w-full"
        onClick={submit}
        disabled={busy || question.trim().length < 3 || options.filter((o) => o.trim()).length < 2}
      >
        Отправить группе
      </Button>
    </Sheet>
  );
}
