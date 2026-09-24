import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";
import { ToastProvider } from "@/components/ui/toast";
import "@/index.css";

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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[initialRoute()]}>
      <ToastProvider>
        <App />
      </ToastProvider>
    </MemoryRouter>
  </StrictMode>,
);
