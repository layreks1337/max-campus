/**
 * Обёртка над MAX Bridge.
 *
 * Вне мессенджера объекта window.WebApp нет, поэтому здесь же живёт заглушка:
 * без неё приложение невозможно открыть в обычном браузере, а гонять каждую
 * правку в мессенджер — потерянный день разработки.
 *
 * Заглушка отдаёт dev-токен вида `dev:<id>:<Name>`, который бэкенд принимает
 * при ALLOW_DEV_AUTH=true. Имя — латиницей: токен уезжает в HTTP-заголовок,
 * а заголовки не допускают кириллицу.
 */

export interface MaxUser {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
}

export interface MaxInitDataUnsafe {
  user?: MaxUser;
  chat?: { id: number; type: "DIALOG" | "CHAT" | "CHANNEL" };
  start_param?: string;
}

interface MaxBackButton {
  show: () => void;
  hide: () => void;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
}

interface MaxWebApp {
  initData?: string;
  initDataUnsafe?: MaxInitDataUnsafe;
  ready?: () => void;
  close?: () => void;
  expand?: () => void;
  openLink?: (url: string) => void;
  BackButton?: MaxBackButton;
  colorScheme?: "light" | "dark";
  platform?: string;
  version?: string;
}

declare global {
  interface Window {
    WebApp?: MaxWebApp;
  }
}

const DEV_USER_KEY = "campus.devUser";

/** Диапазон тестовых id: dev-вход бэкенд пускает только сюда, чтобы без подписи
 *  нельзя было представиться настоящим пользователем MAX.
 *  Те же границы — в backend/app/core/config.py, менять вместе. */
export const TEST_USER_ID_MIN = 900_000;
export const TEST_USER_ID_MAX = 999_999;

export const isTestUserId = (id: number): boolean =>
  Number.isInteger(id) && id >= TEST_USER_ID_MIN && id <= TEST_USER_ID_MAX;

/** Есть ли настоящий Bridge. */
export const isInsideMax = (): boolean =>
  typeof window !== "undefined" && !!window.WebApp?.initData;

/** Кем представляемся в режиме разработки. Меняется в профиле. */
export function getDevUser(): { id: number; name: string } {
  try {
    const raw = localStorage.getItem(DEV_USER_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      // id вне тестового диапазона (сохранён до ограничения) бэкенд не пустит —
      // вместо вечного 401 возвращаемся к пользователю по умолчанию
      if (isTestUserId(Number(saved?.id))) {
        return { id: Number(saved.id), name: String(saved.name ?? "Dev") };
      }
    }
  } catch {
    /* поломанный localStorage — не повод падать */
  }
  return { id: 900001, name: "Anna" };
}

export function setDevUser(id: number, name: string): void {
  localStorage.setItem(DEV_USER_KEY, JSON.stringify({ id, name }));
}

/** Значение для заголовка Authorization. */
export function getAuthToken(): string {
  const real = window.WebApp?.initData;
  if (real) return real;
  const dev = getDevUser();
  // Только ASCII: HTTP-заголовки не переносят кириллицу
  const safeName = dev.name.replace(/[^\x20-\x7E]/g, "") || "Dev";
  return `dev:${dev.id}:${safeName}`;
}

/** Сообщить мессенджеру, что интерфейс отрисован (убирает скелетон). */
export function ready(): void {
  try {
    window.WebApp?.ready?.();
    window.WebApp?.expand?.();
  } catch {
    /* вне MAX — норма */
  }
}

/** Системная кнопка «Назад». Своей кнопки в шапке нет — было бы дублирование. */
export function setBackButton(handler: (() => void) | null): () => void {
  const bb = window.WebApp?.BackButton;
  if (!bb) return () => {};

  if (!handler) {
    bb.hide();
    return () => {};
  }
  bb.onClick(handler);
  bb.show();
  return () => {
    bb.offClick(handler);
    bb.hide();
  };
}

/** Закрыть мини-приложение. Вне MAX закрывать нечего — вернёт false. */
export function closeApp(): boolean {
  const app = window.WebApp;
  if (!app?.close) return false;
  try {
    app.close();
    return true;
  } catch {
    return false;
  }
}

export function openExternal(url: string): void {
  if (window.WebApp?.openLink) window.WebApp.openLink(url);
  else window.open(url, "_blank", "noopener");
}

export function getStartParam(): string {
  return window.WebApp?.initDataUnsafe?.start_param ?? "";
}

/** DIALOG — личка, CHAT — групповой чат. Влияет на сценарии старосты. */
export function getChatType(): string {
  return window.WebApp?.initDataUnsafe?.chat?.type ?? "DIALOG";
}
