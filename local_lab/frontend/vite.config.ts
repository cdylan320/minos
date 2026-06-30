import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const bindHost = process.env.LAB_BIND_HOST || "0.0.0.0";
const backendPort = process.env.LAB_BACKEND_PORT || "8765";
const frontendPort = Number(process.env.LAB_FRONTEND_PORT || "5173");

export default defineConfig({
  plugins: [react()],
  server: {
    host: bindHost,
    port: frontendPort,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
