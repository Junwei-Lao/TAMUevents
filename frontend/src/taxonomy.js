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

export const EVENT_TYPE_TAXONOMY = {
  "Academic / Research": [
    "Lecture", "Seminar", "Colloquium", "Research Talk", "Guest Speaker",
    "Panel Discussion", "Research Presentation", "Research Showcase",
  ],
  "Conference / Large Academic Event": [
    "Conference", "Symposium", "Summit", "Convention", "Research Conference",
    "Academic Meeting",
  ],
  "Workshop / Training": [
    "Workshop", "Hands-on Workshop", "Training", "Tutorial", "Certification",
    "Skill Development", "Software / Technical Training", "Hackathon / Case Competition",
  ],
  "Career / Professional": [
    "Career Fair", "Job Fair", "Employer Information Session", "Recruiting Event",
    "Networking", "Resume / CV Workshop", "Interview Preparation",
    "Professional Development", "Industry Talk", "Graduate School Preparation",
  ],
  "Student Organization": [
    "Club Meeting", "Organization Meeting", "Student Group Event", "Student Leadership",
    "Organization Recruitment", "Club Social",
  ],
  "Social / Community": [
    "Social", "Mixer", "Networking Social", "Community Gathering", "Party", "Festival",
    "Picnic", "Game Night", "Volunteer Event", "Community Service", "Fundraiser",
    "Religious / Worship Service",
  ],
  "Arts / Entertainment": [
    "Concert", "Musical Performance", "Theater Performance", "Dance Performance",
    "Film Screening", "Art Exhibition", "Gallery Event", "Cultural Performance",
  ],
  "Sports / Recreation": [
    "Sporting Event", "Intramural", "Club Sport", "Fitness Class",
    "Recreational Activity", "Outdoor Activity", "Tournament", "Athletic Competition",
  ],
  "Orientation / Recruitment": [
    "New Student Orientation", "Transfer Orientation", "Graduate Orientation",
    "Welcome Event", "Admissions Event", "Open House", "Prospective Student Event",
    "Recruitment Event",
  ],
  "Health / Wellness": [
    "Health Screening", "Wellness Event", "Fitness Event", "Mental Health Workshop",
    "Health Education", "Medical / Health Consultation",
  ],
  "Ceremony / Tradition": [
    "Ceremony", "Commencement", "Memorial", "University Tradition", "Recognition",
    "Award Ceremony", "Dedication", "Anniversary",
  ],
  "Administrative / Information": [
    "Information Session", "Advising", "Town Hall", "Q&A", "Office Hours",
    "Policy Meeting", "Administrative Meeting",
  ],
  "Exhibition / Showcase": [
    "Research Exhibition", "Student Showcase", "Project Showcase", "Poster Session",
    "Demonstration", "Open Lab",
  ],
  "Other": ["Other", "Unknown"],
};

// Categories / categories_audience have no fixed taxonomy - they're
// discovered pools (postgre_io.py's category_pool / audience_pool tables),
// so real values can only come from the backend. Placeholders until that
// endpoint exists.
export const CATEGORY_OPTIONS = ["A", "B", "C"];
export const AUDIENCE_OPTIONS = ["A", "B", "C"];
