/** Привязка студенческого. Единственный экран до входа в приложение:
 *  без связи «аккаунт MAX ↔ студент вуза» справку выдавать некому. */


import { CalendarDays, FileText, MessageCircle, Users } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { api, ApiException } from "@/shared/api";
import type { Me } from "@/shared/types";

const FEATURES = [
  { icon: FileText, text: "Справки и заявления без визита в деканат" },
  { icon: CalendarDays, text: "События вуза и запись в один тап" },
  { icon: Users, text: "Знакомства и напарники по учёбе" },
  { icon: MessageCircle, text: "Ассистент, который знает регламенты" },
];

export default function Onboarding({ onBound }: { onBound: (me: Me) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const submit = async () => {
    const clean = code.trim().toUpperCase();
    if (clean.length < 4) {
      setError("Код слишком короткий");
      return;
    }
    setLoading(true);
    setError("");
    try {
      onBound(await api.bind(clean));
    } catch (e) {
      setError(e instanceof ApiException ? e.message : "Не удалось привязать код");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[560px] flex-col px-6 pb-10 safe-top">
      {/* Анимаций появления здесь нет намеренно. Элементы, стартующие с
          opacity: 0 и ждущие кадра анимации, при троттлинге вебвью или
          с включённым «уменьшить движение» остаются невидимыми — и первый
          экран продукта оказывается пустым. Цена анимации слишком высока. */}
      <div className="mt-6">
        <p className="mb-3 text-[13px] font-semibold tracking-wide text-accent uppercase">
          Цифровой кампус
        </p>
        <h1 className="mb-4 text-[40px] leading-[1.02] font-[650]">
          Вузовская рутина —<br />в одном приложении.
        </h1>
        <p className="mb-9 text-[18px] leading-relaxed font-light text-muted">
          Заявка уходит отсюда, а готовая справка возвращается файлом прямо в чат.
        </p>
      </div>

      <div className="mb-10 flex flex-col gap-3.5">
        {FEATURES.map((f) => (
          <div key={f.text} className="flex items-center gap-3.5">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-raised text-ink">
              <f.icon size={18} />
            </span>
            <span className="text-[15px] leading-snug text-ink">{f.text}</span>
          </div>
        ))}
      </div>

      <div className="mt-auto">
        <label className="mb-2 block text-[13px] font-semibold text-muted">
          Код студента
        </label>
        <input
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
            setError("");
          }}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="A7K2-9M"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          className={`mb-2 h-14 w-full rounded-[16px] bg-field px-5 text-center font-mono text-[22px] tracking-[0.18em] text-ink placeholder:text-faint outline-none focus:ring-2 focus:ring-accent ${
            error ? "ring-2 ring-danger" : ""
          }`}
        />
        {error && <p className="mb-2 text-center text-[13px] text-danger">{error}</p>}

        <Button full size="lg" loading={loading} onClick={submit} className="mt-2">
          Войти
        </Button>

        <button
          onClick={() => setHelpOpen(true)}
          className="mt-4 w-full text-center text-[14px] text-muted"
        >
          У меня нет кода
        </button>
      </div>

      <Sheet open={helpOpen} onClose={() => setHelpOpen(false)} title="Где взять код">
        <p className="mb-4 text-[15px] leading-relaxed text-muted">
          Код выдают в деканате вашего института вместе со студенческим билетом. Он одноразовый
          и привязывает этот аккаунт MAX к вашей учётной записи студента.
        </p>
        <p className="mb-5 text-[15px] leading-relaxed text-muted">
          Если код потерялся — подойдите в деканат или напишите старосте, у него есть список.
        </p>
        <div className="rounded-[16px] bg-field p-4">
          <p className="mb-2 text-[13px] font-semibold text-muted">Демонстрационные коды</p>
          <p className="font-mono text-[15px] leading-relaxed text-ink">
            A7K2-9M · B3N8-4P
            <br />
            C5R1-7T · D9W6-2L
          </p>
          <p className="mt-2 text-[12px] text-faint">
            Для проверки решения экспертами хакатона.
          </p>
        </div>
      </Sheet>
    </div>
  );
}
