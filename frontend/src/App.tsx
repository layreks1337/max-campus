/** Каркас приложения: загрузка профиля, навигация, системная кнопка «Назад». */

import {
  Briefcase,
  FileText,
  Home as HomeIcon,
  MessageCircle,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { ExpandingTabs, type TabItem } from "@/components/ui/expanding-tabs";
import { CardSkeleton } from "@/components/ui/primitives";
import { api, ApiException } from "@/shared/api";
import { getStartParam, isInsideMax, ready, setBackButton } from "@/shared/max";
import type { Me } from "@/shared/types";

import Chat from "@/screens/Chat";
import Home from "@/screens/Home";
import Onboarding from "@/screens/Onboarding";
import People from "@/screens/People";
import Profile from "@/screens/Profile";
import RequestDetail from "@/screens/RequestDetail";
import RequestNew from "@/screens/RequestNew";
import Requests from "@/screens/Requests";
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
  const navigate = useNavigate();
  const location = useLocation();

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

  // Диплинк из чата: ?start_param=request_study_certificate
  useEffect(() => {
    if (!me?.is_bound) return;
    const param = getStartParam();
    if (param.startsWith("request_")) {
      navigate(`/requests/new/${param.slice("request_".length)}`);
    } else if (param === "events") {
      navigate("/");
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

  if (!me?.is_bound) return <Onboarding onBound={setMe} />;

  return (
    <div className="min-h-dvh bg-canvas">
      {/* Анимации перехода между экранами намеренно нет.
          Контейнер, который стартует с opacity 0 и ждёт кадра анимации, при
          троттлинге вебвью оставляет пользователя перед пустым экраном.
          Отдельные элементы внутри экранов анимируются — этого достаточно. */}
      <main className="mx-auto w-full max-w-[560px]">
        <Routes location={location}>
          <Route path="/" element={<Home me={me} />} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/requests/new" element={<RequestNew />} />
          <Route path="/requests/new/:key" element={<RequestNew />} />
          <Route path="/requests/:no" element={<RequestDetail />} />
          <Route path="/people" element={<People />} />
          <Route path="/chat" element={<Chat me={me} />} />
          <Route path="/staff" element={<Staff me={me} />} />
          <Route path="/profile" element={<Profile me={me} onChange={setMe} />} />
          <Route path="*" element={<Home me={me} />} />
        </Routes>
      </main>

      <ExpandingTabs
        tabs={tabs}
        active={activeTab}
        onChange={(key) => navigate(key)}
      />

      {!isInsideMax() && <DevBadge />}
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

/** Видимая метка, что приложение открыто вне мессенджера.
 *  Без неё легко перепутать dev-режим с настоящим запуском. */
function DevBadge() {
  return (
    <div className="pointer-events-none fixed top-2 left-2 z-[90] rounded-full bg-warn/15 px-2.5 py-1 text-[10px] font-semibold text-warn">
      DEV · вне MAX
    </div>
  );
}
