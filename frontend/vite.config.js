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
              topic_taxomony,
              event_type,
              categories,
              categories_audience,
            } = JSON.parse(body || "{}");
            const events = JSON.parse(readFileSync(dataPath, "utf-8"));

            // topic_taxomony / event_type arrive as {parent: [leaf, ...]} -
            // flatten to a leaf set for matching, ignoring parent grouping
            // (a leaf label is unambiguous on its own). An empty/absent
            // field means "no filter" - matches backend.py's SearchRequest
            // and postgre_io.search_events (docs/back_db_contract.md).
            const flattenLeaves = (dict) => Object.values(dict || {}).flat();

            const overlapsArray = (fieldValues, selected) =>
              !selected || selected.length === 0 ||
              selected.some((v) => (fieldValues || []).includes(v));

            const overlapsDict = (eventTopics, requestedDict) => {
              const requestedLeaves = flattenLeaves(requestedDict);
              if (requestedLeaves.length === 0) return true;
              const eventLeaves = flattenLeaves(eventTopics);
              return requestedLeaves.some((leaf) => eventLeaves.includes(leaf));
            };

            // event_type is only ever stored at the parent-category level
            // (tagging.py collapses the model's leaf pick to its parent -
            // see _validate_event_type), so only the selected parent keys
            // matter here, mirroring backend.py's
            // `list(payload.event_type.keys())`.
            const matchesEventType = (eventValue, requestedDict) => {
              const requestedParents = Object.keys(requestedDict || {});
              if (requestedParents.length === 0) return true;
              return requestedParents.includes(eventValue);
            };

            const filtered = events.filter((e) => {
              if (!e.start_date) return false;
              const eventEnd = e.end_date || e.start_date;
              if (!(e.start_date <= end_date && eventEnd >= start_date)) return false;
              if (!overlapsDict(e.topics, topic_taxomony)) return false;
              if (!matchesEventType(e.event_type, event_type)) return false;
              if (!overlapsArray(e.categories, categories)) return false;
              if (!overlapsArray(e.categories_audience, categories_audience)) return false;
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
