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

/** Есть ли настоящий Bridge. */
export const isInsideMax = (): boolean =>
  typeof window !== "undefined" && !!window.WebApp?.initData;

/** Кем представляемся в режиме разработки. Меняется в профиле. */
export function getDevUser(): { id: number; name: string } {
  try {
    const raw = localStorage.getItem(DEV_USER_KEY);
    if (raw) return JSON.parse(raw);
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
