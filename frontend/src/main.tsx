import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";
import { ToastProvider } from "@/components/ui/toast";
import "@/index.css";
import { captureLinkToken } from "@/shared/max";
import { installScrollMotion } from "@/shared/scroll-motion";

/* Ссылка из бота (?lt=…): до первого запроса к API забрать токен входа
   и заменить адрес в строке и в истории браузера на чистый. */
captureLinkToken();

/* MemoryRouter, а не BrowserRouter: Bridge мессенджера передаёт данные запуска
   во фрагменте URL (после #), и навигация по адресной строке с ним конфликтует.
   Приложению внешние ссылки на экраны не нужны — диплинки приходят через
   start_param.

   Исключение — параметр ?screen=/chat: он задаёт стартовый экран. Нужен для
   ручной проверки и снятия скриншотов, в мессенджере не используется. */

function initialRoute(): string {
  try {
    const screen = new URLSearchParams(window.location.search).get("screen");
    if (screen && screen.startsWith("/")) return screen;
  } catch {
    /* нестандартное окружение — открываем главную */
  }
  return "/";
}

/* Сохранённую тему применяем до первого рендера. В index.html по умолчанию
   стоит class="dark", а переключатель живёт в профиле — без этой строки
   выбранная светлая тема сбрасывалась при каждом запуске. Ключ — тот же,
   что в Profile.tsx. */
try {
  if (localStorage.getItem("campus.theme") === "light") {
    document.documentElement.classList.remove("dark");
  }
} catch {
  /* нет доступа к localStorage — остаётся тёмная по умолчанию */
}

installScrollMotion();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[initialRoute()]}>
      <ToastProvider>
        <App />
      </ToastProvider>
    </MemoryRouter>
  </StrictMode>,
);
