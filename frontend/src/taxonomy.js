// Mirrors TOPIC_TAXONOMY / EVENT_TYPE_TAXONOMY in src/helpers/schema.py.
// Keep these two in sync by hand if the backend taxonomy changes.

export const TOPIC_TAXONOMY = {
  "STEM & Technology": [
    "Computer Science", "Artificial Intelligence / Machine Learning", "Data Science",
    "Mathematics / Statistics", "Physics", "Chemistry", "Biology / Life Sciences",
    "Engineering", "Materials Science", "Earth & Space Sciences",
    "Energy & Energy Systems", "Information Technology", "Robotics", "Cybersecurity",
    "Biotechnology", "Nanotechnology", "Other STEM",
  ],
  "Health & Medicine": [
    "Public Health", "Medicine", "Nursing", "Mental Health & Wellness", "Nutrition",
    "Healthcare", "Epidemiology", "Biomedical Science", "Disability / Accessibility",
    "Other Health",
  ],
  "Business & Career": [
    "Business", "Finance", "Accounting", "Marketing", "Entrepreneurship", "Management",
    "Leadership", "Career Development", "Job Search / Recruiting",
    "Professional Development", "Industry / Corporate", "Other Business",
  ],
  "Social Sciences & Politics": [
    "Political Science", "Government / Public Policy", "Sociology", "Psychology",
    "Anthropology", "International Relations", "Social Justice", "Community Studies",
    "Economics", "Other Social Sciences",
  ],
  "Humanities": [
    "History", "Philosophy", "Literature", "English", "Languages", "Linguistics",
    "Religion", "Classics", "Ethics", "Cultural Studies", "Other Humanities",
  ],
  "Arts & Culture": [
    "Visual Arts", "Music", "Theater", "Dance", "Film / Media", "Photography",
    "Creative Writing", "Museums / Exhibitions", "Cultural Heritage",
    "Other Arts & Culture",
  ],
  "Architecture & Design": [
    "Architecture", "Urban Planning", "Landscape Architecture", "Urban Design",
    "Interior Design", "Construction", "Real Estate / Built Environment", "Design",
    "Other Architecture & Design",
  ],
  "Law & Legal Studies": [
    "Law", "Legal Studies", "Criminal Justice", "Human Rights", "Legal Policy",
    "Other Law",
  ],
  "Education": [
    "Teaching", "Pedagogy", "Educational Research", "Academic Success", "Study Skills",
    "Advising", "Student Learning", "Other Education",
  ],
  "Agriculture & Environment": [
    "Agriculture", "Agribusiness", "Animal Science", "Plant Science", "Food Science",
    "Environmental Science", "Ecology", "Sustainability", "Climate", "Natural Resources",
    "Conservation", "Horticulture", "Other Agriculture & Environment",
  ],
  "International & Global Studies": [
    "International Affairs", "Global Studies", "International Development",
    "Cross-cultural Studies", "Global Affairs", "Other International & Global Studies",
  ],
  "Campus & Student Life": [
    "Student Life", "Campus Community", "Student Organizations", "Volunteering",
    "Community Service", "Student Leadership", "Traditions", "Diversity & Inclusion",
    "Residential Life", "Other Campus & Student Life",
  ],
  "Sports & Recreation": [
    "Athletics", "Gymnastics", "Fitness", "Sport Competitions / Tournaments",
    "Sport Science", "Other Sports & Recreation",
  ],
  "General / Interdisciplinary": [
    "Interdisciplinary Research", "General Academic", "General Interest",
  ],
};

// event_type is only ever stored on an Event at the parent-category level
// (tagging.py's _validate_event_type collapses the model's leaf pick to
// its parent), so unlike TOPIC_TAXONOMY there's no leaf-level filtering
// power to expose in the UI - just the parent category names themselves,
// mirroring EVENT_TYPE_TAXONOMY's keys in src/helpers/schema.py.
export const EVENT_TYPE_CATEGORIES = [
  "Academic / Research",
  "Conference / Large Academic Event",
  "Workshop / Training",
  "Career / Professional",
  "Student Organization",
  "Social / Community",
  "Arts / Entertainment",
  "Sports / Recreation",
  "Orientation / Recruitment",
  "Health / Wellness",
  "Ceremony / Tradition",
  "Administrative / Information",
  "Exhibition / Showcase",
  "Other",
];

// Categories / categories_audience have no fixed taxonomy - they're
// discovered pools, mirroring data/category_pool.json and
// data/audience_pool.json (built by postgre_io.initialize_database by
// scanning every event, and stored in Postgres as category_pool /
// audience_pool). Keep these two arrays in sync by hand if those files
// change - there's no endpoint yet to fetch them at runtime.
export const CATEGORY_OPTIONS = [
  "Academic Calendar",
  "Arts & Entertainment",
  "Campus Life",
  "General Interest",
  "International Students",
  "Open Houses & Receptions",
  "Speakers, Forums, Conferences, Training & Workshops",
  "Sports & Athletics",
];

export const AUDIENCE_OPTIONS = [
  "Faculty",
  "Researcher",
  "Residents",
  "Staff",
  "Students",
  "Visitors",
  "Youth (K-12)",
];
