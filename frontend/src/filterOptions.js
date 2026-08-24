export const ALL_LABEL = "All";

// Shape sent to the backend per docs/front_back_contract.md:
//   topic_taxomony / event_type: { [parentCategory]: [selectedLeaf, ...] }
//   categories / categories_audience: [selectedValue, ...]
// An empty object/array here means "All" - backend.py's SearchRequest and
// postgre_io.search_events (docs/back_db_contract.md) both treat an
// absent/empty field as "no filter", so it's sent through as-is.
export const DEFAULT_FILTERS = {
  topics: {},
  // event_type is only ever stored on an Event at the parent-category
  // level (see tagging.py's _validate_event_type), so unlike topics there's
  // no useful leaf-level filter - just a flat pick of parent categories.
  event_type: [],
  categories: [],
  categories_audience: [],
};
