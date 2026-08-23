// Placeholder option lists for the taxonomy-backed filters. Real values
// live in src/helpers/tagging.py (TOPIC_TAXONOMY / EVENT_TYPE_TAXONOMY) and
// the category_pool / audience_pool tables in postgre_io.py - swap these
// placeholders out once the backend exposes an endpoint to fetch them.
export const ALL_VALUE = "All";

const PLACEHOLDER_OPTIONS = [ALL_VALUE, "A", "B", "C"];

export const FILTER_FIELDS = [
  { key: "topics", label: "Topics", options: PLACEHOLDER_OPTIONS },
  { key: "event_type", label: "Event Type", options: PLACEHOLDER_OPTIONS },
  { key: "categories", label: "Categories", options: PLACEHOLDER_OPTIONS },
  {
    key: "categories_audience",
    label: "Audience",
    options: PLACEHOLDER_OPTIONS,
  },
];

export const DEFAULT_FILTERS = FILTER_FIELDS.reduce((acc, field) => {
  acc[field.key] = ALL_VALUE;
  return acc;
}, {});
