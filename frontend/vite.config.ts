import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 2499,
    strictPort: true,
    proxy: { "/api": process.env.SILLAGE_API_URL || "http://127.0.0.1:2500" },
  },
});
