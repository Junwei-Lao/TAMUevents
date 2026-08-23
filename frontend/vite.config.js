import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Dev-only mock of the future FastAPI `POST /api/events/search` endpoint, so
// the UI can be built/tested before the real backend exists. It implements
// the same [start_date, end_date] overlap semantics as
// postgre_io.get_events_in_date_range. Never runs in a production build.
function mockEventsApi() {
  const dataPath = fileURLToPath(
    new URL("./src/mock/sampleEvents.json", import.meta.url)
  );

  return {
    name: "mock-events-api",
    configureServer(server) {
      server.middlewares.use("/api/events/search", (req, res, next) => {
        if (req.method !== "POST") return next();

        let body = "";
        req.on("data", (chunk) => (body += chunk));
        req.on("end", () => {
          try {
            const {
              start_date,
              end_date,
              topics,
              event_type,
              categories,
              categories_audience,
            } = JSON.parse(body || "{}");
            const events = JSON.parse(readFileSync(dataPath, "utf-8"));

            const overlaps = (fieldValues, selected) =>
              !selected || selected.some((v) => (fieldValues || []).includes(v));

            const filtered = events.filter((e) => {
              if (!e.start_date) return false;
              const eventEnd = e.end_date || e.start_date;
              if (!(e.start_date <= end_date && eventEnd >= start_date)) return false;
              if (event_type && e.event_type !== event_type) return false;
              if (!overlaps(e.topics, topics)) return false;
              if (!overlaps(e.categories, categories)) return false;
              if (!overlaps(e.categories_audience, categories_audience)) return false;
              return true;
            });

            res.setHeader("Content-Type", "application/json");
            res.end(JSON.stringify({ events: filtered }));
          } catch (err) {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: String(err) }));
          }
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), mockEventsApi()],
  server: {
    port: 5173,
  },
});
