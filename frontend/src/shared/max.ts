/**
 * Обёртка над MAX Bridge.
 *
 * Вне мессенджера объекта window.WebApp нет, поэтому здесь же живёт заглушка:
 * без неё приложение невозможно открыть в обычном браузере, а гонять каждую
 * правку в мессенджер — потерянный день разработки.
 *
 * Заглушка отдаёт dev-токен вида `dev:<id>:<Name>`, который бэкенд принимает
 * при ALLOW_DEV_AUTH=true. Имя — латиницей: токен уезжает в HTTP-заголовок,
 * а заголовки не допускают кириллицу. Если приложение открыли ссылкой из бота,
 * вместо заглушки — подписанный токен настоящего пользователя (см. ниже).
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

/** Случайные id для браузеров начинаются выше фиксированных тестовых
 *  (900001–900999: смоук-тест и быстрые кнопки в профиле). */
const RANDOM_DEV_ID_MIN = 901_000;

/** Имя по умолчанию. Бэкенд считает его заглушкой и называет демо-копию
 *  как шаблонного студента, а не «Dev». */
const DEFAULT_DEV_NAME = "Dev";

let sessionDevUser: { id: number; name: string } | null = null;

/** Кем представляемся в режиме разработки. Меняется в профиле.
 *
 *  Каждому браузеру — свой случайный тестовый id, запомненный в localStorage.
 *  Раньше все открывшие ссылку вне MAX были одним пользователем 900001
 *  и видели заявки друг друга. */
export function getDevUser(): { id: number; name: string } {
  try {
    const raw = localStorage.getItem(DEV_USER_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      // id вне тестового диапазона (сохранён до ограничения) бэкенд не пустит —
      // вместо вечного 401 выдаём новый случайный
      if (isTestUserId(Number(saved?.id))) {
        return { id: Number(saved.id), name: String(saved.name ?? DEFAULT_DEV_NAME) };
      }
    }
  } catch {
    /* поломанный localStorage — не повод падать */
  }
  // Держим в памяти: без localStorage (приватный режим) каждый запрос
  // иначе уходил бы от нового пользователя
  if (!sessionDevUser) {
    const id =
      RANDOM_DEV_ID_MIN + Math.floor(Math.random() * (TEST_USER_ID_MAX - RANDOM_DEV_ID_MIN + 1));
    sessionDevUser = { id, name: DEFAULT_DEV_NAME };
    try {
      setDevUser(id, DEFAULT_DEV_NAME);
    } catch {
      /* останется новым на каждой загрузке страницы — лучше, чем падение */
    }
  }
  return sessionDevUser;
}

export function setDevUser(id: number, name: string): void {
  localStorage.setItem(DEV_USER_KEY, JSON.stringify({ id, name }));
}

/* ── Вход по ссылке из бота ─────────────────────────────────────
   Пока организаторы не привязали мини-приложение к боту, кнопка в чате —
   обычная ссылка, и приложение открывается в браузере без подписи MAX. Бот
   кладёт в неё ?lt=<id>.<срок>.<подпись>: по нему сервер узнаёт настоящего
   пользователя MAX, и справка приходит ему в чат (решение 057).
   Токен живёт в sessionStorage — только эта вкладка — и сразу убирается
   из адресной строки: иначе он уйдёт вместе со скопированной ссылкой
   и останется в записи истории вкладки. */

const LINK_TOKEN_KEY = "campus.linkToken";
/** Тот же формат проверяет сервер; мусор в заголовок не отправляем —
 *  fetch на недопустимых символах падает целиком. */
const LINK_TOKEN_RE = /^[1-9]\d{0,18}\.[1-9]\d{0,11}\.[0-9a-f]{64}$/;

let memoryLinkToken: string | null = null;

/** Забрать токен из адреса. Вызывается один раз до первого запроса (main.tsx). */
export function captureLinkToken(): void {
  let url: URL;
  try {
    url = new URL(window.location.href);
  } catch {
    return;
  }
  const token = url.searchParams.get("lt");
  if (token === null) return;

  url.searchParams.delete("lt");
  try {
    // Фрагмент (#…) сохраняем: в нём Bridge передаёт данные запуска
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  } catch {
    /* без History API токен останется в адресе — вход всё равно работает */
  }

  // Внутри MAX есть настоящая подпись запуска, она главнее ссылки
  if (isInsideMax() || !LINK_TOKEN_RE.test(token)) return;
  memoryLinkToken = token;
  try {
    sessionStorage.setItem(LINK_TOKEN_KEY, token);
  } catch {
    /* приватный режим: токен проживёт до перезагрузки вкладки */
  }
}

function getLinkToken(): string | null {
  if (memoryLinkToken) return memoryLinkToken;
  try {
    const saved = sessionStorage.getItem(LINK_TOKEN_KEY);
    return saved && LINK_TOKEN_RE.test(saved) ? saved : null;
  } catch {
    return null;
  }
}

/** Открыто в браузере по ссылке из бота: пользователь настоящий, но вне MAX. */
export const isLinkSession = (): boolean => !isInsideMax() && getLinkToken() !== null;

/** Значение заголовка Authorization: подпись запуска MAX, ссылка бота или dev-вход. */
export function getAuthHeader(): string {
  const real = window.WebApp?.initData;
  if (real) return `MaxInitData ${real}`;
  const link = getLinkToken();
  if (link) return `MaxLink ${link}`;
  const dev = getDevUser();
  // Только ASCII: HTTP-заголовки не переносят кириллицу
  const safeName = dev.name.replace(/[^\x20-\x7E]/g, "") || "Dev";
  return `MaxInitData dev:${dev.id}:${safeName}`;
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

/** Формат стартового параметра по документации MAX: латиница, цифры, «_» и «-». */
const START_PARAM_RE = /^[A-Za-z0-9_-]{1,512}$/;

/** Стартовый параметр запуска: `req_<номер>`, `event_<id>`, `schedule`…
 *
 *  Внутри MAX он приходит в подписи запуска (`initDataUnsafe.start_param`) —
 *  из диплинка max.ru/<бот>?startapp=… или из payload кнопки open_app. Тот же
 *  параметр MAX кладёт в адрес приложения GET-параметром `WebAppStartParam`;
 *  там же его передаёт запасная кнопка-ссылка бота, открывающая браузер
 *  (решение 058). Параметр только выбирает экран: права проверяет сервер. */
export function getStartParam(): string {
  let param = window.WebApp?.initDataUnsafe?.start_param ?? "";
  if (!param) {
    try {
      param = new URLSearchParams(window.location.search).get("WebAppStartParam") ?? "";
    } catch {
      param = "";
    }
  }
  return START_PARAM_RE.test(param) ? param : "";
}

/** DIALOG — личка, CHAT — групповой чат. Влияет на сценарии старосты. */
export function getChatType(): string {
  return window.WebApp?.initDataUnsafe?.chat?.type ?? "DIALOG";
}
