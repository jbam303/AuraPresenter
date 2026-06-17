import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: true, // Expose to LAN so the phone can connect
    proxy: {
      "/ws": {
        target: "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        phone: "phone.html",
      },
    },
  },
});
