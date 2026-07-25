import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "0.0.0.0", port: 3000 },
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
