import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(frontendRoot, "..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repositoryRoot, "");

  return {
    envDir: repositoryRoot,
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      proxy: {
        "/api": {
          target: env.PROOFGATE_BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
