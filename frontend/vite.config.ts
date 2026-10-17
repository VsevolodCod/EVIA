import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "BI_");
  const target = env.BI_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    base: "/",
    server: {
      proxy: Object.fromEntries(
        ["/health", "/sources", "/agent", "/chats"].map((path) => [path, { target }]),
      ),
    },
    test: {
      environment: "jsdom",
      execArgv: ["--no-experimental-webstorage"],
      setupFiles: ["./src/test-setup.ts"],
      globals: true,
    },
  };
});
