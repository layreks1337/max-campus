/**
 * Эмулятор клиента MAX для проверки без телефона.
 *
 * Включается параметром адреса ?maxEmu=android|ios|web|desktop и только вне
 * MAX (настоящий initData не подменяется: вход остаётся dev-токеном, сервер
 * ему ничего лишнего не доверяет). Дополнительно:
 *   ?qr=T12-ABCDE — что «увидит» камера; без него появится окно ввода.
 *
 * Как устроено: скрипт Bridge (st.max.ru/js/max-web-app.js) вне MAX создаёт
 * window.WebApp без транспорта. Мы подставляем транспорт, который отвечает так,
 * как ответил бы клиент, через тот же вход, которым пользуется сам MAX, —
 * WebApp.sendEvent(type, json). Поля transport и initDataManager — внутренние
 * у библиотеки; для тестового стенда это допустимо, в рабочем коде — нет.
 *
 * Режим web повторяет поведение web.max.ru (проверено по его коду 28.09.2026):
 * сканер, вибрация и яркость отвечают client.unsupported_method.unsupported_method,
 * shareContent — client.web_app_share.unsupported_method.
 */

import type { MaxPlatform } from "@/shared/max";

type Payload = { requestId?: string; [k: string]: unknown };

interface BridgeInternals {
  transport?: { sendEvent: (type: string, payload: Payload) => void };
  initDataManager?: { rawPlatformData: string | null };
  sendEvent?: (type: string, json: string) => void;
  initData?: string | null;
}

const MOBILE_ONLY = new Set([
  "WebAppOpenCodeReader",
  "WebAppHapticFeedbackImpact",
  "WebAppHapticFeedbackNotification",
  "WebAppHapticFeedbackSelectionChange",
  "WebAppChangeScreenBrightness",
  "WebAppDeviceStorageSaveKey",
  "WebAppDeviceStorageGetKey",
  "WebAppDeviceStorageClear",
]);

/** Метки «вибрация: success», «яркость: максимум» — столбиком в правом верхнем
 *  углу, ниже метки «Эмулятор MAX»: так видно, что и в каком порядке вызвано. */
function flash(text: string): void {
  let box = document.getElementById("max-emu-flash");
  if (!box) {
    box = document.createElement("div");
    box.id = "max-emu-flash";
    box.style.cssText =
      "position:fixed;right:8px;top:36px;z-index:9999;display:flex;flex-direction:column;" +
      "align-items:flex-end;gap:4px;pointer-events:none;max-width:70vw";
    document.body.appendChild(box);
  }
  const el = document.createElement("div");
  el.textContent = text;
  el.setAttribute("data-max-emu", "");
  el.style.cssText =
    "padding:6px 10px;border-radius:10px;background:#222;color:#fff;" +
    "font:12px/1.3 monospace;opacity:.92;word-break:break-all";
  box.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}

export function installMaxEmulator(): void {
  let platform: MaxPlatform | null = null;
  try {
    const p = new URLSearchParams(window.location.search).get("maxEmu");
    if (p === "android" || p === "ios" || p === "web" || p === "desktop") platform = p;
  } catch {
    return;
  }
  const app = window.WebApp as unknown as BridgeInternals | undefined;
  if (!platform || !app || app.initData) return; // настоящий запуск в MAX не трогаем
  if (!app.transport || !app.initDataManager || !app.sendEvent) {
    console.warn("[max-emu] внутреннее устройство Bridge изменилось — эмулятор не включён");
    return;
  }

  const qr = new URLSearchParams(window.location.search).get("qr");
  const reply = (type: string, requestId: string | undefined, data: object) => {
    if (!requestId) return; // событие без ответа (ready, BackButton, closing)
    setTimeout(() => app.sendEvent!(type, JSON.stringify({ requestId, ...data })), 300);
  };

  app.initDataManager.rawPlatformData = platform;
  app.transport.sendEvent = (type, payload) => {
    const { requestId, ...p } = payload;
    console.info("[max-emu] →", type, p);

    if (platform === "web" || platform === "desktop") {
      if (MOBILE_ONLY.has(type) || type === "WebAppShare") {
        flash(`${platform}: ${type} не поддерживается`);
        return reply(type, requestId, {
          error: {
            code:
              type === "WebAppShare"
                ? "client.web_app_share.unsupported_method"
                : "client.unsupported_method.unsupported_method",
          },
        });
      }
    }

    switch (type) {
      case "WebAppOpenCodeReader": {
        const value = qr ?? window.prompt("Эмулятор MAX: что прочитала камера?", "") ?? null;
        flash(value ? `QR: ${value}` : "сканер закрыт");
        return reply(type, requestId, value ? { value } : { error: { code: "client.open_code_reader.cancelled" } });
      }
      case "WebAppHapticFeedbackImpact":
        flash(`вибрация: ${String(p.impactStyle)}`);
        return reply(type, requestId, { status: "impactOccured" });
      case "WebAppHapticFeedbackNotification":
        flash(`вибрация: ${String(p.notificationType)}`);
        return reply(type, requestId, { status: "notificationOccured" });
      case "WebAppHapticFeedbackSelectionChange":
        flash("вибрация: selection");
        return reply(type, requestId, { status: "selectionChanged" });
      case "WebAppChangeScreenBrightness":
        flash(p.maxBrightness ? "яркость: максимум" : "яркость: как была");
        return reply(type, requestId, { maxBrightness: !!p.maxBrightness });
      case "WebAppMaxShare": {
        const ok = window.confirm(`Эмулятор MAX: поделиться в чат?\n\n${String(p.text ?? "")}\n${String(p.link ?? "")}`);
        return reply(type, requestId, { status: ok ? "shared" : "cancelled" });
      }
      case "WebAppDownloadFile":
        window.open(String(p.url), "_blank", "noopener");
        return reply(type, requestId, { status: "downloading" });
      case "WebAppOpenLink":
      case "WebAppOpenMaxLink":
        window.open(String(p.url), "_blank", "noopener");
        return;
      default:
        return reply(type, requestId, {}); // ready, BackButton и прочее — без последствий
    }
  };
  window.__campusMaxEmu = platform;
  console.info(`[max-emu] включён: platform=${platform}`);
}
