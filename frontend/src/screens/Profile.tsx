/** Профиль: данные студента, роль сотрудника, переключение темы,
 *  и — вне мессенджера — смена тестового пользователя. */

import { Briefcase, Moon, Sun, UserCog } from "lucide-react";
import { useEffect, useState } from "react";

import { shortFaculty } from "@/components/cards";
import { Button } from "@/components/ui/button";
import { Card, Chip, Divider } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/sheet";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import { getDevUser, isInsideMax, setDevUser } from "@/shared/max";
import type { Me } from "@/shared/types";

const THEME_KEY = "campus.theme";

export default function Profile({
  me,
  onChange,
}: {
  me: Me;
  onChange: (me: Me) => void;
}) {
  const [dark, setDark] = useState(
    () => (localStorage.getItem(THEME_KEY) ?? "dark") === "dark",
  );
  const [staffOpen, setStaffOpen] = useState(false);
  const [devOpen, setDevOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
  }, [dark]);

  const s = me.student;

  return (
    <div className="px-4 pb-28 safe-top">
      <header className="scroll-fade mb-6 flex items-center gap-4 px-1">
        <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-raised text-[24px] font-[650] text-ink">
          {me.photo_url ? (
            <img src={me.photo_url} alt="" className="h-full w-full object-cover" />
          ) : (
            (s?.first_name ?? me.display_name).slice(0, 1).toUpperCase()
          )}
        </div>
        <div className="min-w-0">
          <h1 className="mb-0.5 truncate text-[24px] leading-tight">
            {s?.full_name ?? me.display_name}
          </h1>
          {s && (
            <p className="truncate text-[14px] text-muted">
              {s.group_name} · {shortFaculty(s.faculty)}
            </p>
          )}
        </div>
      </header>

      {s && (
        <Card className="mb-4">
          <Row label="Курс" value={`${s.course}`} />
          <Row label="Форма обучения" value={s.education_form} />
          <Row label="Основа" value={s.funding} />
          <Row label="Зачётная книжка" value={s.record_book_no} mono />
          <Row label="Институт" value={s.faculty} last />
        </Card>
      )}

      {me.staff && (
        <Card className="mb-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
              <Briefcase size={18} />
            </span>
            <div className="min-w-0">
              <p className="text-[15px] font-semibold text-ink">{me.staff.position}</p>
              <p className="truncate text-[13px] text-muted">{me.staff.department}</p>
            </div>
          </div>
        </Card>
      )}

      <Card className="mb-4">
        <button
          onClick={() => setDark((v) => !v)}
          className="flex w-full items-center justify-between gap-4"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-raised text-ink">
              {dark ? <Moon size={17} /> : <Sun size={17} />}
            </span>
            <span className="text-[15px] text-ink">{dark ? "Тёмная тема" : "Светлая тема"}</span>
          </span>
          <span
            className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${
              dark ? "bg-accent" : "bg-surface-raised"
            }`}
          >
            <span
              className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${
                dark ? "left-6" : "left-1"
              }`}
            />
          </span>
        </button>

        {!me.staff && (
          <>
            <Divider className="my-4" />
            <button
              onClick={() => setStaffOpen(true)}
              className="flex w-full items-center gap-3 text-left"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-raised text-muted">
                <UserCog size={17} />
              </span>
              <span className="min-w-0">
                <span className="block text-[15px] text-ink">Я сотрудник вуза</span>
                <span className="block text-[12px] text-faint">Ввести служебный код</span>
              </span>
            </button>
          </>
        )}

        {!isInsideMax() && (
          <>
            <Divider className="my-4" />
            <button
              onClick={() => setDevOpen(true)}
              className="flex w-full items-center gap-3 text-left"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-warn/15 text-warn">
                DEV
              </span>
              <span className="min-w-0">
                <span className="block text-[15px] text-ink">Тестовый пользователь</span>
                <span className="block text-[12px] text-faint">
                  id {getDevUser().id} · только вне MAX
                </span>
              </span>
            </button>
          </>
        )}
      </Card>

      <p className="px-2 pb-4 text-center text-[12px] leading-relaxed text-faint">
        MAX Campus · демонстрационная версия
        <br />
        Данные вуза смоделированы для хакатона
      </p>

      <StaffCodeSheet
        open={staffOpen}
        onClose={() => setStaffOpen(false)}
        onDone={onChange}
      />
      <DevUserSheet open={devOpen} onClose={() => setDevOpen(false)} />
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  last,
}: {
  label: string;
  value: string;
  mono?: boolean;
  last?: boolean;
}) {
  return (
    <div className={last ? "" : "mb-3"}>
      <p className="text-[12px] text-faint">{label}</p>
      <p className={`text-[15px] text-ink ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

function StaffCodeSheet({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (me: Me) => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const submit = async () => {
    setBusy(true);
    try {
      onDone(await api.bindStaff(code.trim().toUpperCase()));
      toast.ok("Роль активирована");
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Код не подошёл");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Служебный доступ">
      <p className="mb-4 text-[15px] leading-relaxed text-muted">
        Код выдаётся сотрудникам деканата. После активации появится раздел с очередью
        заявок и возможностью выдавать документы.
      </p>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="STAFF-001"
        className="mb-4 h-13 w-full rounded-[16px] bg-field px-4 py-3 text-center font-mono text-[17px] tracking-wider text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent"
      />
      <Button full loading={busy} onClick={submit}>
        Активировать
      </Button>
      <div className="mt-4 rounded-[16px] bg-field p-4">
        <p className="mb-1 text-[13px] font-semibold text-muted">Демонстрационные коды</p>
        <p className="font-mono text-[14px] text-ink">
          STAFF-001 — специалист
          <br />
          STAFF-002 — заместитель директора
        </p>
      </div>
    </Sheet>
  );
}

function DevUserSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const current = getDevUser();
  const [id, setId] = useState(String(current.id));
  const [name, setName] = useState(current.name);

  return (
    <Sheet open={open} onClose={onClose} title="Тестовый пользователь">
      <p className="mb-4 text-[15px] leading-relaxed text-muted">
        Приложение открыто вне мессенджера, поэтому подпись запуска не проверяется.
        Здесь можно представиться другим пользователем — удобно, чтобы посмотреть
        приложение глазами студента и сотрудника одновременно.
      </p>
      <p className="mb-2 text-[13px] font-semibold text-muted">ID</p>
      <input
        value={id}
        onChange={(e) => setId(e.target.value.replace(/\D/g, ""))}
        className="mb-4 h-12 w-full rounded-[16px] bg-field px-4 font-mono text-[15px] text-ink outline-none"
      />
      <p className="mb-2 text-[13px] font-semibold text-muted">Имя (латиницей)</p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value.replace(/[^\x20-\x7E]/g, ""))}
        className="mb-5 h-12 w-full rounded-[16px] bg-field px-4 text-[15px] text-ink outline-none"
      />
      <Button
        full
        onClick={() => {
          setDevUser(Number(id) || 900001, name || "Dev");
          window.location.reload();
        }}
      >
        Применить и перезагрузить
      </Button>
      <div className="mt-4 flex flex-wrap gap-2">
        <Chip onClick={() => { setId("900001"); setName("Anna"); }}>900001 студент</Chip>
        <Chip onClick={() => { setId("900002"); setName("Irina"); }}>900002 деканат</Chip>
        <Chip onClick={() => { setId("900003"); setName("Sergey"); }}>900003 подписант</Chip>
      </div>
    </Sheet>
  );
}
