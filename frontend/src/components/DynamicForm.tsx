/**
 * Форма заявки, собранная из описания полей шаблона.
 *
 * Это ядро движка заявок на стороне клиента: новый тип справки появляется
 * в приложении сам, как только бэкенд отдал его schema_json. Ни одной строчки
 * здесь при этом менять не нужно.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  FileField,
  NumberField,
  SelectField,
  SwitchField,
  TextField,
} from "@/components/ui/fields";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Template, TemplateField } from "@/shared/types";

type Values = Record<string, unknown>;

function initialValues(fields: TemplateField[]): Values {
  const out: Values = {};
  for (const f of fields) {
    if (f.default !== undefined && f.default !== null) out[f.name] = f.default;
    else if (f.type === "bool") out[f.name] = false;
    else if (f.type === "number") out[f.name] = f.min ?? 1;
    else out[f.name] = "";
  }
  return out;
}

export function DynamicForm({
  template,
  onSubmitted,
}: {
  template: Template;
  onSubmitted: (publicNo: string) => void;
}) {
  const toast = useToast();
  const [values, setValues] = useState<Values>(() => initialValues(template.fields));
  const [fileNames, setFileNames] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const set = (name: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const pickFile = async (field: TemplateField, file: File) => {
    const limit = (field.maxSizeMb ?? 10) * 1024 * 1024;
    if (file.size > limit) {
      setErrors((p) => ({ ...p, [field.name]: `Файл больше ${field.maxSizeMb ?? 10} МБ` }));
      return;
    }
    setUploading(field.name);
    try {
      const res = await api.upload(file);
      set(field.name, res.file);
      setFileNames((p) => ({ ...p, [field.name]: res.original_name || file.name }));
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось загрузить файл");
    } finally {
      setUploading(null);
    }
  };

  const submit = async () => {
    setSending(true);
    setErrors({});
    try {
      const created = await api.createRequest(template.key, values);
      onSubmitted(created.public_no);
    } catch (e) {
      if (e instanceof ApiException) {
        const fieldErrors = e.fieldErrors;
        if (Object.keys(fieldErrors).length) {
          setErrors(fieldErrors);
          toast.error("Проверьте выделенные поля");
        } else {
          toast.error(e.message);
        }
      } else {
        toast.error("Не удалось отправить заявку");
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <div>
      {template.fields.map((f) => {
        const error = errors[f.name];
        const common = { label: f.label, hint: f.hint, error, required: f.required };

        switch (f.type) {
          case "select":
            return (
              <SelectField
                key={f.name}
                {...common}
                value={String(values[f.name] ?? "")}
                options={f.options ?? []}
                onChange={(v) => set(f.name, v)}
              />
            );
          case "number":
            return (
              <NumberField
                key={f.name}
                {...common}
                value={Number(values[f.name] ?? f.min ?? 1)}
                min={f.min}
                max={f.max}
                onChange={(v) => set(f.name, v)}
              />
            );
          case "bool":
            return (
              <SwitchField
                key={f.name}
                label={f.label}
                hint={f.hint}
                value={Boolean(values[f.name])}
                onChange={(v) => set(f.name, v)}
              />
            );
          case "file":
            return (
              <FileField
                key={f.name}
                {...common}
                fileName={fileNames[f.name] ?? ""}
                uploading={uploading === f.name}
                onPick={(file) => pickFile(f, file)}
                onClear={() => {
                  set(f.name, "");
                  setFileNames((p) => ({ ...p, [f.name]: "" }));
                }}
              />
            );
          case "date":
            return (
              <TextField
                key={f.name}
                {...common}
                type="date"
                value={String(values[f.name] ?? "")}
                onChange={(v) => set(f.name, v)}
              />
            );
          case "textarea":
            return (
              <TextField
                key={f.name}
                {...common}
                multiline
                maxLength={f.maxLength}
                placeholder={f.placeholder}
                value={String(values[f.name] ?? "")}
                onChange={(v) => set(f.name, v)}
              />
            );
          default:
            return (
              <TextField
                key={f.name}
                {...common}
                maxLength={f.maxLength}
                placeholder={f.placeholder}
                value={String(values[f.name] ?? "")}
                onChange={(v) => set(f.name, v)}
              />
            );
        }
      })}

      <div className="sticky bottom-0 -mx-5 mt-2 bg-gradient-to-t from-canvas via-canvas to-transparent px-5 pt-4 pb-24">
        <Button full size="lg" loading={sending} onClick={submit}>
          Отправить заявку
        </Button>
        <p className="mt-3 text-center text-[12px] text-faint">
          Срок рассмотрения — около {template.sla_days} дн. Статус придёт в чат.
        </p>
      </div>
    </div>
  );
}
