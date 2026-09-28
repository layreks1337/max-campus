/**
 * Обёртка над MAX Bridge.
 *
 * Вне мессенджера скрипт Bridge всё равно создаёт window.WebApp, но с пустым
 * initData, platform = null и без транспорта: вызовы молча теряются. Поэтому
 * «мы в MAX» — это непустой initData (isInsideMax), а не наличие объекта.
 * Здесь же живёт заглушка входа: без неё приложение невозможно открыть
 * в обычном браузере, а гонять каждую правку в мессенджер — потерянный день.
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

/** Ошибка Bridge: промис отклоняется объектом `{ error: { code } }`.
 *  Таймаут библиотеки — `client.<метод>.request_timeout`,
 *  метод, которого нет в клиенте (веб-версия) — `client.unsupported_method.unsupported_method`. */
export interface MaxBridgeError {
  error?: { code?: string };
}

type ImpactStyle = "soft" | "light" | "medium" | "heavy" | "rigid";
type NoticeType = "success" | "warning" | "error";

interface MaxHapticFeedback {
  impactOccurred: (style: ImpactStyle, disableVibrationFallback?: boolean) => Promise<unknown>;
  notificationOccurred: (type: NoticeType, disableVibrationFallback?: boolean) => Promise<unknown>;
  selectionChanged: (disableVibrationFallback?: boolean) => Promise<unknown>;
}

interface MaxWebApp {
  initData?: string | null;
  initDataUnsafe?: MaxInitDataUnsafe;
  ready?: () => void;
  close?: () => void;
  expand?: () => void;
  openLink?: (url: string) => void;
  openMaxLink?: (url: string) => void;
  BackButton?: MaxBackButton;
  HapticFeedback?: MaxHapticFeedback;
  colorScheme?: "light" | "dark";
  /** ios | android | desktop | web; вне MAX — null. В подпись initData не входит. */
  platform?: string | null;
  version?: string | null;
  openCodeReader?: (fileSelect?: boolean) => Promise<{ value?: string }>;
  requestScreenMaxBrightness?: () => Promise<{ maxBrightness?: boolean }>;
  restoreScreenBrightness?: () => Promise<{ maxBrightness?: boolean }>;
  shareMaxContent?: (
    p: { text?: string; link?: string } | { mid: string; chatType: "DIALOG" | "CHAT" },
  ) => Promise<{ status?: "shared" | "cancelled" }>;
  downloadFile?: (url: string, fileName: string) => Promise<{ status?: "downloading" | "cancelled" }>;
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
}

declare global {
  interface Window {
    WebApp?: MaxWebApp;
    /** Эмулятор клиента для проверки без телефона (shared/max-emulator.ts). */
    __campusMaxEmu?: MaxPlatform;
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

/** Есть ли кому отвечать на вызовы Bridge: запуск в MAX или эмулятор.
 *  Вне MAX скрипт Bridge тоже создаёт window.WebApp, но без транспорта:
 *  вызовы уходят в никуда, а промисы отклоняются только по таймауту. */
const hasBridge = (): boolean => isInsideMax() || !!window.__campusMaxEmu;

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

/** Внешняя ссылка. Проверка — hasBridge(), а не наличие openLink: скрипт Bridge
 *  создаёт window.WebApp и в обычном браузере (в том числе при входе по ссылке
 *  из бота), но без транспорта openLink молча ничего не делает. */
export function openExternal(url: string): void {
  // Только веб-ссылки: `javascript:` и прочие схемы из данных не открываем
  let href: string;
  try {
    const parsed = new URL(url, window.location.href);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return;
    href = parsed.href;
  } catch {
    return;
  }
  if (hasBridge() && window.WebApp?.openLink) window.WebApp.openLink(href);
  else window.open(href, "_blank", "noopener");
}

/* ── Возможности устройства ─────────────────────────────────────────
 *
 * Поддержка по платформам (документация dev.max.ru/docs/webapps/bridge и код
 * web.max.ru на 28.09.2026):
 *   openCodeReader, HapticFeedback, requestScreenMaxBrightness — только телефоны;
 *     веб-клиент отвечает client.unsupported_method.unsupported_method,
 *     поддержка в десктопном клиенте не описана.
 *   shareMaxContent, downloadFile — телефоны и веб (в вебе — своё окно MAX).
 *
 * Правило: вызываем метод, только если platform его поддерживает, и никогда не
 * бросаем исключений наружу — каждый вызов возвращает понятный результат. */

export type MaxPlatform = "ios" | "android" | "desktop" | "web";

export function maxPlatform(): MaxPlatform | null {
  if (!hasBridge()) return null;
  const p = window.WebApp?.platform;
  return p === "ios" || p === "android" || p === "desktop" || p === "web" ? p : null;
}

/** Платформа встроенного эмулятора клиента (?maxEmu=…) — для метки на экране:
 *  всё, что он показывает, смоделировано. В самом MAX всегда null. */
export const emulatedPlatform = (): MaxPlatform | null =>
  isInsideMax() ? null : (window.__campusMaxEmu ?? null);

/** Мобильный клиент MAX: камера, вибрация, яркость. */
export const isMobileMax = (): boolean => {
  const p = maxPlatform();
  return p === "ios" || p === "android";
};

const bridgeCode = (e: unknown): string =>
  String((e as MaxBridgeError | undefined)?.error?.code ?? "");

/** Сканер QR камерой MAX. Библиотека ждёт ответа клиента до 10 минут,
 *  поэтому вызывающий код не блокирует интерфейс на время сканирования. */
export const canScanQr = (): boolean =>
  isMobileMax() && typeof window.WebApp?.openCodeReader === "function";

export type ScanResult =
  | { kind: "ok"; value: string }
  | { kind: "cancelled" }
  | { kind: "unsupported" }
  | { kind: "error"; code: string };

export async function scanQr(): Promise<ScanResult> {
  const app = window.WebApp;
  if (!canScanQr() || !app?.openCodeReader) return { kind: "unsupported" };
  try {
    // true — камера плюс выбор снимка из галереи: так билет можно проверить
    // и с одного телефона, по скриншоту
    const res = await app.openCodeReader(true);
    const value = String(res?.value ?? "").trim();
    return value ? { kind: "ok", value } : { kind: "cancelled" };
  } catch (e) {
    const code = bridgeCode(e);
    if (code.includes("unsupported")) return { kind: "unsupported" };
    if (code.includes("cancel")) return { kind: "cancelled" };
    return { kind: "error", code };
  }
}

/** Тактильный отклик. В MAX на телефоне — HapticFeedback (работает и на iOS,
 *  где navigator.vibrate нет); в вебе и на десктопе MAX его не поддерживает. */
function vibrate(pattern: number | number[]): void {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* не везде поддерживается */
  }
}

const mobileHaptics = (): MaxHapticFeedback | null =>
  isMobileMax() ? (window.WebApp?.HapticFeedback ?? null) : null;

export const haptics = {
  impact(style: ImpactStyle = "light"): void {
    const hf = mobileHaptics();
    if (hf) void hf.impactOccurred(style).catch(() => {});
    else if (!hasBridge()) vibrate(8);
  },
  notify(type: NoticeType): void {
    const hf = mobileHaptics();
    if (hf) void hf.notificationOccurred(type).catch(() => {});
    else if (!hasBridge()) vibrate(type === "success" ? 12 : type === "warning" ? [10, 60, 10] : [20, 40, 20, 40, 20]);
  },
  selection(): void {
    const hf = mobileHaptics();
    if (hf) void hf.selectionChanged().catch(() => {});
  },
};

/** Максимальная яркость на время показа QR-билета. MAX сам вернёт прежнюю
 *  через 30 секунд, restoreBrightness — чтобы не ждать. */
export async function boostBrightness(): Promise<boolean> {
  const app = window.WebApp;
  if (!isMobileMax() || !app?.requestScreenMaxBrightness) return false;
  try {
    return !!(await app.requestScreenMaxBrightness())?.maxBrightness;
  } catch {
    return false;
  }
}

export function restoreBrightness(): void {
  const app = window.WebApp;
  if (!isMobileMax() || !app?.restoreScreenBrightness) return;
  void app.restoreScreenBrightness().catch(() => {});
}

export type ShareResult = "shared" | "cancelled" | "unavailable" | "error";

/** Окно «Поделиться» самого MAX: пользователь выбирает чат группы, сообщение
 *  уходит от его имени. MAX открывает окно только в ответ на клик, поэтому
 *  вызывать синхронно в обработчике нажатия, до любого await.
 *  Десктопный клиент — не описан в документации: там сразу «unavailable». */
export function shareInMax(p: { text: string; link?: string }): Promise<ShareResult> {
  const app = window.WebApp;
  const platform = maxPlatform();
  if (!app?.shareMaxContent || platform === null || platform === "desktop") {
    return Promise.resolve("unavailable");
  }
  return app
    .shareMaxContent(p)
    .then((r): ShareResult => (r?.status === "shared" ? "shared" : "cancelled"))
    .catch((e): ShareResult => (bridgeCode(e).includes("unsupported") ? "unavailable" : "error"));
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
