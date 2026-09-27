/** Каркас приложения: загрузка профиля, навигация, системная кнопка «Назад». */

import {
  Briefcase,
  FileText,
  Home as HomeIcon,
  MessageCircle,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { ExpandingTabs, type TabItem } from "@/components/ui/expanding-tabs";
import { CardSkeleton } from "@/components/ui/primitives";
import { api, ApiException, isSessionExpired, onSessionExpired } from "@/shared/api";
import {
  closeApp,
  getStartParam,
  isInsideMax,
  isLinkSession,
  ready,
  setBackButton,
} from "@/shared/max";
import type { Me } from "@/shared/types";

import Campus from "@/screens/Campus";
import Chat from "@/screens/Chat";
import Grades from "@/screens/Grades";
import Group from "@/screens/Group";
import Home from "@/screens/Home";
import Onboarding from "@/screens/Onboarding";
import People from "@/screens/People";
import Profile from "@/screens/Profile";
import RequestDetail from "@/screens/RequestDetail";
import RequestNew from "@/screens/RequestNew";
import Requests from "@/screens/Requests";
import Schedule from "@/screens/Schedule";
import Staff from "@/screens/Staff";

const STUDENT_TABS: TabItem[] = [
  { key: "/", label: "Главная", icon: HomeIcon },
  { key: "/requests", label: "Заявки", icon: FileText },
  { key: "/people", label: "Люди", icon: Users },
  { key: "/chat", label: "Чат", icon: MessageCircle },
];

const STAFF_TAB: TabItem = { key: "/staff", label: "Деканат", icon: Briefcase };

/** Корневые экраны: на них системная кнопка «Назад» не нужна. */
const ROOTS = new Set(["/", "/requests", "/people", "/chat", "/staff"]);

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  const [expired, setExpired] = useState(isSessionExpired);
  const navigate = useNavigate();
  const location = useLocation();
  const startParamHandled = useRef(false);

  // Любой 401 из api.ts — подпись запуска больше не принимается
  useEffect(() => onSessionExpired(() => setExpired(true)), []);

  const loadMe = useCallback(async () => {
    try {
      setMe(await api.me());
      setFatal(null);
    } catch (e) {
      setFatal(
        e instanceof ApiException
          ? e.message
          : "Сервис недоступен. Проверьте соединение и попробуйте ещё раз.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    ready();
    void loadMe();
  }, [loadMe]);

  // Диплинк из чата: startapp=request_study_certificate, payload кнопки
  // open_app или WebAppStartParam запасной ссылки бота (см. getStartParam).
  // Один раз за запуск: navigate меняется при каждом переходе, и эффект без
  // флага возвращал бы на экран диплинка после любого нажатия, а с заявкой,
  // которой нет, — гонял бы по кругу «заявка → 404 → список → заявка».
  useEffect(() => {
    if (!me?.is_bound || startParamHandled.current) return;
    startParamHandled.current = true;
    const param = getStartParam();
    if (param.startsWith("request_")) {
      navigate(`/requests/new/${param.slice("request_".length)}`);
    } else if (param.startsWith("req_")) {
      // Уведомление о заявке: «Открыть заявку» ведёт в неё саму, а не на главную
      navigate(`/requests/${param.slice("req_".length)}`);
    } else if (param === "events") {
      navigate("/");
    } else if (param.startsWith("event_")) {
      // Карточка события, пересланная в чат: сразу раскрываем её в афише
      navigate("/", { state: { openEvent: Number(param.slice("event_".length)) } });
    } else if (["schedule", "grades", "campus", "group"].includes(param)) {
      navigate(`/${param}`);
    }
  }, [me?.is_bound, navigate]);

  // Системная кнопка «Назад» — своей в шапке нет, это было бы дублированием
  useEffect(() => {
    if (ROOTS.has(location.pathname)) return setBackButton(null);
    return setBackButton(() => navigate(-1));
  }, [location.pathname, navigate]);

  const tabs = useMemo(
    () => (me?.staff ? [...STUDENT_TABS.slice(0, 3), STAFF_TAB] : STUDENT_TABS),
    [me?.staff],
  );

  const activeTab = useMemo(() => {
    const match = tabs.find(
      (t) => t.key !== "/" && location.pathname.startsWith(t.key),
    );
    return match?.key ?? "/";
  }, [location.pathname, tabs]);

  if (expired) return <SessionExpired />;

  if (loading) return <BootSkeleton />;

  if (fatal) {
    return (
      <Centered>
        <p className="mb-2 text-[20px] font-[650]">Не удалось запустить</p>
        <p className="mb-6 max-w-[300px] text-[15px] leading-relaxed text-muted">{fatal}</p>
        <button
          onClick={() => {
            setLoading(true);
            void loadMe();
          }}
          className="h-12 rounded-full bg-ink px-6 font-semibold text-canvas"
        >
          Повторить
        </button>
      </Centered>
    );
  }

  if (!me?.is_bound) {
    return <Onboarding onBound={setMe} demo={me?.features?.demo !== false} />;
  }

  return (
    <div className="min-h-dvh">
      {/* Переход между экранами — CSS-анимация по ключу пути. Стартует не с
          нулевой прозрачности: если вебвью притормозит кадры, экран всё равно
          виден, а не пуст, как было с JS-анимацией онбординга. */}
      <main key={location.pathname} className="screen-in mx-auto w-full max-w-[560px]">
        <Routes location={location}>
          <Route path="/" element={<Home me={me} />} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/requests/new" element={<RequestNew />} />
          <Route path="/requests/new/:key" element={<RequestNew />} />
          <Route path="/requests/:no" element={<RequestDetail />} />
          <Route path="/people" element={<People />} />
          <Route path="/chat" element={<Chat me={me} />} />
          <Route path="/staff" element={<Staff me={me} onChange={setMe} />} />
          <Route path="/profile" element={<Profile me={me} onChange={setMe} />} />
          <Route path="/schedule" element={<Schedule />} />
          <Route path="/grades" element={<Grades />} />
          <Route path="/campus" element={<Campus />} />
          <Route path="/group" element={<Group />} />
          <Route path="*" element={<Home me={me} />} />
        </Routes>
      </main>

      <ExpandingTabs
        tabs={tabs}
        active={activeTab}
        onChange={(key) => navigate(key)}
      />

      {!isInsideMax() && (isLinkSession() ? <LinkBadge /> : <DevBadge />)}
    </div>
  );
}

function BootSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[560px] px-4 pt-10">
      <div className="shimmer mb-6 h-8 w-44 rounded-[16px] bg-surface-raised" />
      <CardSkeleton />
      <div className="h-3" />
      <CardSkeleton />
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-6 text-center">
      {children}
    </div>
  );
}

/** Сервер перестал принимать подпись запуска (401). Внутри MAX помогает только
 *  новый запуск: подпись выдаётся при открытии, и перезагрузка страницы отдаст
 *  ту же, протухшую. Поэтому там главная кнопка — закрыть. */
function SessionExpired() {
  const inside = isInsideMax();
  // Ссылка из бота действует сутки, и перезагрузка отдаст тот же токен —
  // помогает только новая ссылка из чата
  if (!inside && isLinkSession()) {
    return (
      <Centered>
        <p className="mb-2 text-[20px] font-[650]">Ссылка устарела</p>
        <p className="max-w-[300px] text-[15px] leading-relaxed text-muted">
          Ссылка для входа из чата действует сутки. Напишите боту в MAX /start —
          он пришлёт новую.
        </p>
      </Centered>
    );
  }
  return (
    <Centered>
      <p className="mb-2 text-[20px] font-[650]">Сессия устарела</p>
      <p className="mb-6 max-w-[300px] text-[15px] leading-relaxed text-muted">
        {inside
          ? "Откройте приложение заново — подпись входа из MAX действует один час."
          : "Откройте приложение заново из чата с ботом в MAX."}
      </p>
      {inside && (
        <button
          onClick={() => closeApp()}
          className="mb-3 h-12 rounded-full bg-ink px-6 font-semibold text-canvas"
        >
          Закрыть приложение
        </button>
      )}
      <button
        onClick={() => window.location.reload()}
        className={
          inside
            ? "h-12 rounded-full px-6 font-semibold text-muted"
            : "h-12 rounded-full bg-ink px-6 font-semibold text-canvas"
        }
      >
        Обновить
      </button>
    </Centered>
  );
}

/** Видимая метка, что приложение открыто вне мессенджера.
 *  Без неё легко перепутать dev-режим с настоящим запуском. */
function DevBadge() {
  return (
    <div className="pointer-events-none fixed top-2 left-2 z-[90] rounded-full bg-warn/15 px-2.5 py-1 text-[10px] font-semibold text-warn">
      DEV · вне MAX
    </div>
  );
}

/** Открыто в браузере по ссылке из бота: пользователь настоящий, подписан
 *  сервером, но это не мини-приложение внутри MAX — так и пишем. */
function LinkBadge() {
  return (
    <div className="pointer-events-none fixed top-2 left-2 z-[90] rounded-full bg-ok/15 px-2.5 py-1 text-[10px] font-semibold text-ok">
      Браузер · вход через бота
    </div>
  );
}
