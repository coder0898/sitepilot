import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "0.0.0.0", port: 3000 },
  // testTimeout is raised from Vitest's 5s default: the heaviest render
  // tests (TemplateGates mounts 32 gate rows) sit around 3-4s on an idle
  // machine and cross 5s purely from worker contention when the whole suite
  // runs in parallel. The failures were timeouts, never assertions.
  test: { environment: "jsdom", setupFiles: "./src/test/setup.js", css: true, testTimeout: 20000 },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "supabase-auth",
              test: /node_modules[\\/]@supabase[\\/]/,
              includeDependenciesRecursively: true,
              priority: 20,
            },
            {
              name: "react-vendor",
              test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/,
              includeDependenciesRecursively: true,
              priority: 10,
            },
          ],
        },
      },
    },
  },
});
