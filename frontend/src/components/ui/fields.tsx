/** Поля ввода. В покое рамки нет — только тинт-заливка; рамка появляется
 *  кольцом фокуса. Высота 48px: палец, а не мышь. */

import { Check, ChevronDown, Paperclip, X } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { cn } from "@/shared/utils";

function Label({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <label className="mb-1.5 block text-[13px] font-semibold text-muted">
      {children}
      {required && <span className="ml-1 text-danger">*</span>}
    </label>
  );
}

function Hint({ text, error }: { text?: string | null; error?: string }) {
  if (error) return <p className="mt-1.5 text-[12px] text-danger">{error}</p>;
  if (!text) return null;
  return <p className="mt-1.5 text-[12px] leading-snug text-faint">{text}</p>;
}

const BASE =
  "w-full rounded-[16px] bg-field px-4 text-[15px] text-ink placeholder:text-faint " +
  "outline-none transition-shadow focus:ring-2 focus:ring-accent";

/* ── Текст ─────────────────────────────────────────────────────── */

export function TextField({
  label, value, onChange, placeholder, hint, error, required, multiline, maxLength, type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string | null;
  hint?: string | null;
  error?: string;
  required?: boolean;
  multiline?: boolean;
  maxLength?: number | null;
  type?: string;
}) {
  return (
    <div className="mb-5">
      <Label required={required}>{label}</Label>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? ""}
          maxLength={maxLength ?? undefined}
          rows={4}
          className={cn(BASE, "resize-none py-3 leading-relaxed", error && "ring-2 ring-danger")}
        />
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? ""}
          maxLength={maxLength ?? undefined}
          className={cn(BASE, "h-12", error && "ring-2 ring-danger")}
        />
      )}
      <Hint text={hint} error={error} />
    </div>
  );
}

/* ── Число ─────────────────────────────────────────────────────── */

export function NumberField({
  label, value, onChange, min, max, hint, error, required,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number | null;
  max?: number | null;
  hint?: string | null;
  error?: string;
  required?: boolean;
}) {
  const lo = min ?? 1;
  const hi = max ?? 99;
  const clamp = (n: number) => Math.min(hi, Math.max(lo, n));

  return (
    <div className="mb-5">
      <Label required={required}>{label}</Label>
      <div
        className={cn(
          "flex h-12 items-center justify-between rounded-[16px] bg-field px-2",
          error && "ring-2 ring-danger",
        )}
      >
        <button
          type="button"
          aria-label="Уменьшить"
          onClick={() => onChange(clamp(value - 1))}
          className="h-9 w-9 rounded-full bg-surface text-[18px] font-semibold text-ink"
        >
          −
        </button>
        <span className="text-[16px] font-semibold tabular-nums">{value}</span>
        <button
          type="button"
          aria-label="Увеличить"
          onClick={() => onChange(clamp(value + 1))}
          className="h-9 w-9 rounded-full bg-surface text-[18px] font-semibold text-ink"
        >
          +
        </button>
      </div>
      <Hint text={hint} error={error} />
    </div>
  );
}

/* ── Выбор ─────────────────────────────────────────────────────── */

export function SelectField({
  label, value, options, onChange, hint, error, required,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  hint?: string | null;
  error?: string;
  required?: boolean;
}) {
  const [open, setOpen] = useState(false);

  // До 4 вариантов показываем списком: лишний тап на раскрытие не нужен
  if (options.length <= 4) {
    return (
      <div className="mb-5">
        <Label required={required}>{label}</Label>
        <div className="flex flex-col gap-2">
          {options.map((opt) => {
            const selected = opt === value;
            return (
              <button
                key={opt}
                type="button"
                onClick={() => onChange(opt)}
                className={cn(
                  "flex min-h-12 items-center justify-between gap-3 rounded-[16px] px-4 py-3 text-left",
                  "text-[15px] transition-colors",
                  selected ? "bg-ink text-canvas" : "bg-field text-ink",
                )}
              >
                <span className="leading-snug">{opt}</span>
                {selected && <Check size={17} className="shrink-0" />}
              </button>
            );
          })}
        </div>
        <Hint text={hint} error={error} />
      </div>
    );
  }

  return (
    <div className="mb-5">
      <Label required={required}>{label}</Label>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex h-12 w-full items-center justify-between rounded-[16px] bg-field px-4",
          error && "ring-2 ring-danger",
        )}
      >
        <span className={cn("text-[15px]", value ? "text-ink" : "text-faint")}>
          {value || "Выберите"}
        </span>
        <ChevronDown
          size={18}
          className={cn("text-muted transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-1 rounded-[16px] bg-field p-1">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => {
                onChange(opt);
                setOpen(false);
              }}
              className={cn(
                "rounded-[12px] px-3 py-2.5 text-left text-[15px]",
                opt === value ? "bg-ink text-canvas" : "text-ink",
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      <Hint text={hint} error={error} />
    </div>
  );
}

/* ── Переключатель ─────────────────────────────────────────────── */

export function SwitchField({
  label, value, onChange, hint,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  hint?: string | null;
}) {
  return (
    <div className="mb-5">
      <button
        type="button"
        onClick={() => onChange(!value)}
        className="flex w-full items-center justify-between gap-4 rounded-[16px] bg-field px-4 py-3 text-left"
      >
        <span className="text-[15px] leading-snug text-ink">{label}</span>
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
      <Hint text={hint} />
    </div>
  );
}

/* ── Файл ──────────────────────────────────────────────────────── */

export function FileField({
  label, fileName, onPick, onClear, hint, error, required, uploading,
}: {
  label: string;
  fileName: string;
  onPick: (file: File) => void;
  onClear: () => void;
  hint?: string | null;
  error?: string;
  required?: boolean;
  uploading?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);

  return (
    <div className="mb-5">
      <Label required={required}>{label}</Label>
      <input
        ref={ref}
        type="file"
        accept="image/*,application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = "";
        }}
      />
      {fileName ? (
        <div className="flex items-center gap-3 rounded-[16px] bg-field px-4 py-3">
          <Paperclip size={17} className="shrink-0 text-muted" />
          <span className="flex-1 truncate text-[14px] text-ink">{fileName}</span>
          <button
            type="button"
            onClick={onClear}
            aria-label="Убрать файл"
            className="shrink-0 text-muted"
          >
            <X size={17} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => ref.current?.click()}
          disabled={uploading}
          className={cn(
            "flex min-h-12 w-full items-center justify-center gap-2 rounded-[16px]",
            "border border-dashed border-hairline bg-field px-4 py-3 text-[14px] text-muted",
            error && "border-danger",
          )}
        >
          <Paperclip size={16} />
          {uploading ? "Загружаю…" : "Прикрепить фото или PDF"}
        </button>
      )}
      <Hint text={hint} error={error} />
    </div>
  );
}
