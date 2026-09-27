/** HTTP-клиент. Заголовок авторизации подставляется в одном месте —
 *  размазывать его по экранам нельзя, иначе где-нибудь забудут. */

import { getAuthToken } from "@/shared/max";
import type {
  AskResult,
  BuildingInfo,
  CampusEvent,
  CampusRequest,
  ChatHistory,
  Grades,
  Group,
  Home,
  Intent,
  Match,
  MatchProfile,
  Me,
  Opportunity,
  Poll,
  Template,
  Ticket,
  TicketCheck,
  Today,
  Week,
} from "@/shared/types";

export class ApiException extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Пользователь ещё не привязал студенческий — нужен онбординг. */
  get needsBinding(): boolean {
    return this.code === "BINDING_REQUIRED";
  }

  /** Пофайловые ошибки формы: { имя_поля: "текст ошибки" }. */
  get fieldErrors(): Record<string, string> {
    const raw = this.details;
    if (!raw) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(raw)) {
      if (typeof v === "string") out[k] = v;
    }
    return out;
  }
}

/* ── Протухшая сессия ───────────────────────────────────────────
   401 значит одно: сервер больше не принимает подпись запуска (MAX выдаёт её
   один раз при открытии, срок — час). Каждый экран это не обработает, поэтому
   сигнал общий: App подписывается и показывает полноэкранную заглушку
   «Сессия устарела» вместо сырой ошибки посреди сценария. */

let sessionExpired = false;
const expiredListeners = new Set<() => void>();

export const isSessionExpired = (): boolean => sessionExpired;

/** Подписка на протухание сессии. Возвращает отписку — удобно для useEffect. */
export function onSessionExpired(cb: () => void): () => void {
  expiredListeners.add(cb);
  return () => {
    expiredListeners.delete(cb);
  };
}

function markSessionExpired(): void {
  if (sessionExpired) return;
  sessionExpired = true;
  expiredListeners.forEach((cb) => cb());
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `MaxInitData ${getAuthToken()}`,
    // Бесплатный ngrok иначе может отдать вместо JSON страницу-предупреждение.
    "ngrok-skip-browser-warning": "1",
  };
  let payload: BodyInit | undefined;

  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json; charset=utf-8";
    payload = JSON.stringify(body);
  }

  const resp = await fetch(`/api${path}`, { method, headers, body: payload, signal });

  if (resp.status === 204) return undefined as T;

  const text = await resp.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!resp.ok) {
    if (resp.status === 401) markSessionExpired();
    const err = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })
      ?.error;
    throw new ApiException(
      resp.status,
      err?.code ?? "UNKNOWN",
      err?.message ?? `Ошибка ${resp.status}`,
      err?.details,
    );
  }
  return data as T;
}

const get = <T>(p: string, signal?: AbortSignal) => request<T>("GET", p, undefined, signal);
const post = <T>(p: string, b?: unknown) => request<T>("POST", p, b);
const put = <T>(p: string, b?: unknown) => request<T>("PUT", p, b);
const del = <T>(p: string) => request<T>("DELETE", p);

export const api = {
  // ── Профиль ────────────────────────────────────────────────────
  me: () => get<Me>("/me"),
  bind: (code: string) => post<Me>("/binding/claim", { code }),
  bindStaff: (code: string) => post<Me>("/binding/staff", { code }),
  home: () => get<Home>("/home"),

  upload: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ file: string; original_name: string; size: number }>("POST", "/uploads", fd);
  },

  // ── Заявки ─────────────────────────────────────────────────────
  templates: () => get<Template[]>("/requests/templates"),
  template: (key: string) => get<Template>(`/requests/templates/${key}`),
  requests: (onlyActive = false) =>
    get<CampusRequest[]>(`/requests${onlyActive ? "?only_active=true" : ""}`),
  request: (no: string) => get<CampusRequest>(`/requests/${no}`),
  createRequest: (template_key: string, payload: Record<string, unknown>) =>
    post<CampusRequest>("/requests", { template_key, payload }),
  cancelRequest: (no: string) => post<CampusRequest>(`/requests/${no}/cancel`),
  answerInfo: (no: string, comment: string) =>
    post<CampusRequest>(`/requests/${no}/info`, { comment }),

  // ── Деканат ────────────────────────────────────────────────────
  staffQueue: (status?: string) =>
    get<CampusRequest[]>(`/staff/requests${status ? `?status=${status}` : ""}`),
  staffTransition: (no: string, to_status: string, comment = "") =>
    post<CampusRequest>(`/staff/requests/${no}/transition`, { to_status, comment }),
  staffIssue: (no: string) => post<CampusRequest>(`/staff/requests/${no}/issue`),

  // ── События ────────────────────────────────────────────────────
  events: (days = 60) => get<CampusEvent[]>(`/events?days=${days}`),
  registerEvent: (id: number) => post<CampusEvent>(`/events/${id}/register`),
  unregisterEvent: (id: number) => del<CampusEvent>(`/events/${id}/register`),

  // ── Возможности ────────────────────────────────────────────────
  opportunities: (kind?: string) =>
    get<Opportunity[]>(`/opportunities${kind ? `?kind=${kind}` : ""}`),
  setInterest: (id: number, level: "INTERESTED" | "GOING") =>
    post<{ ok: boolean }>(`/opportunities/${id}/interest`, { level }),
  lookingForTeam: (id: number, message: string) =>
    post<Intent>(`/opportunities/${id}/looking-for-team`, { message }),

  // ── Матчинг ────────────────────────────────────────────────────
  deck: () => get<Intent[]>("/match/deck"),
  swipe: (intent_id: number, decision: "LIKE" | "SKIP") =>
    post<{ matched: boolean; match_name?: string; match_username?: string }>("/match/swipe", {
      intent_id,
      decision,
    }),
  matches: () => get<Match[]>("/match/matches"),
  myIntents: () => get<Intent[]>("/match/intents"),
  createIntent: (data: { kind: string; title: string; description: string; tags: string[] }) =>
    post<Intent>("/match/intents", data),
  closeIntent: (id: number) => del<{ ok: boolean }>(`/match/intents/${id}`),
  matchProfile: () => get<MatchProfile>("/match/profile"),
  saveMatchProfile: (p: MatchProfile) => put<MatchProfile>("/match/profile", p),

  // ── Учёба и группа ─────────────────────────────────────────────
  today: () => get<Today>("/today"),
  schedule: (week = 0) => get<Week>(`/schedule?week=${week}`),
  grades: () => get<Grades>("/grades"),
  buildings: () => get<BuildingInfo[]>("/buildings"),
  ticket: (eventId: number) => get<Ticket>(`/events/${eventId}/ticket`),
  checkTicket: (code: string) => post<TicketCheck>("/staff/tickets/check", { code }),
  shareEvent: (eventId: number) =>
    post<{ sent_to_chat: boolean; text: string; link: string }>(`/events/${eventId}/share`),
  group: () => get<Group>("/group"),
  createPoll: (question: string, options: string[], event_id?: number) =>
    post<Poll>("/group/polls", { question, options, event_id }),
  vote: (pollId: number, option_idx: number) =>
    post<Poll>(`/group/polls/${pollId}/vote`, { option_idx }),

  // ── Ассистент ──────────────────────────────────────────────────
  transcribe: async (pcm: ArrayBuffer) => {
    const resp = await fetch("/api/assistant/transcribe", {
      method: "POST",
      headers: {
        Authorization: `MaxInitData ${getAuthToken()}`,
        "Content-Type": "application/octet-stream",
        "ngrok-skip-browser-warning": "1",
      },
      body: pcm,
    });
    if (resp.status === 401) markSessionExpired();
    if (!resp.ok) throw new ApiException(resp.status, "STT_FAILED", "Не удалось распознать речь");
    return (await resp.json()) as { text: string };
  },
  ask: (question: string) => post<AskResult>("/assistant/ask", { question }),
  chatHistory: () => get<ChatHistory>("/assistant/history"),
  clearChat: () => del<{ ok: boolean }>("/assistant/history"),
};
