import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Алиас @ обязателен: на него завязаны все импорты вида @/components/ui/...
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    // В разработке фронт живёт отдельно от бэкенда, поэтому проксируем API.
    // В production бэкенд отдаёт собранную статику сам — одно происхождение,
    // прокси не нужен, CORS не нужен.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/verify": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    // Вебвью мессенджера — не место для тяжёлых бандлов
    chunkSizeWarningLimit: 900,
  },
});
