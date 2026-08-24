export const ALL_LABEL = "All";

// Shape sent to the backend per docs/front_back_contract.md:
//   topic_taxomony / event_type: { [parentCategory]: [selectedLeaf, ...] }
//   categories / categories_audience: [selectedValue, ...]
// An empty object/array here means "All" - see App.jsx's buildRequestBody,
// which fills in the full taxonomy/pool for whichever fields are empty.
export const DEFAULT_FILTERS = {
  topics: {},
  event_type: {},
  categories: [],
  categories_audience: [],
};
