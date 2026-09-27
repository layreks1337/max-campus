/** «Включить роль деканата (демо)»: роль сотрудника, который выдаёт документы,
 *  в один тап — без служебного кода. Только для демо-профиля эксперта
 *  (решение 055): он сам проводит свою заявку до PDF, а очередь деканата
 *  показывает ему только его заявки. */

import { Briefcase } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, ApiException } from "@/shared/api";
import type { Me } from "@/shared/types";

export function DemoDeanButton({ onDone }: { onDone: (me: Me) => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const enable = async () => {
    setBusy(true);
    try {
      onDone(await api.bindDemoStaff());
      toast.ok("Роль деканата включена — вкладка «Деканат» внизу");
    } catch (e) {
      toast.error(e instanceof ApiException ? e.message : "Не удалось включить роль");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button full loading={busy} onClick={enable}>
      <Briefcase size={16} /> Включить роль деканата (демо)
    </Button>
  );
}
