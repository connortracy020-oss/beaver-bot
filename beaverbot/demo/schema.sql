-- Beaver Bot demo database (data/demo.db). SAMPLE DATA ONLY.
--
-- Course and program facts come from the public Academic Catalog pages already stored in data/osu.sqlite.
-- Everything else is invented by beaverbot/demo/generate.py with a fixed random seed: sections, CRNs, times,
-- seats, rooms, instructors, students, holds, appointments and balances. Nothing here is OSU's real schedule
-- and nothing comes from a real student's account. See docs/demo-build-plan.md.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);   -- seed, built_at, source counts, schema_version

-- ---- catalog facts (public) -------------------------------------------------------------------
CREATE TABLE courses (
    code            TEXT PRIMARY KEY,        -- "CS 161", "MTH 251Z", "CS 162H"
    subject         TEXT NOT NULL,           -- "CS"
    subject_name    TEXT,                    -- "Computer Science"
    number          TEXT NOT NULL,           -- "161", "251Z"
    level           INTEGER NOT NULL,        -- 0, 100, 200, ... 800 (hundreds digit * 100)
    title           TEXT NOT NULL,           -- "Introduction to Computer Science I" (title case, markers removed)
    credits_text    TEXT NOT NULL,           -- as the catalog prints it: "4", "1-16", "0 or 4"
    credits_min     REAL NOT NULL,
    credits_max     REAL NOT NULL,
    description     TEXT,
    prereq_text     TEXT,                    -- the catalog's "Prerequisite:" line, as written
    coreq_text      TEXT,
    recommended_text TEXT,
    equivalent_text TEXT,
    repeatable_text TEXT,
    ecampus         INTEGER NOT NULL DEFAULT 0,   -- "Available via Ecampus"
    honors          INTEGER NOT NULL DEFAULT 0,
    catalog_url     TEXT NOT NULL,           -- the public subject page this came from
    retrieved_at    TEXT                     -- date the catalog page was retrieved
);
CREATE INDEX courses_subject ON courses(subject, number);

-- Parsed prerequisite rules. A course is ready when every group_no has at least one satisfied row.
CREATE TABLE prerequisites (
    course_code TEXT NOT NULL REFERENCES courses(code),
    kind        TEXT NOT NULL DEFAULT 'prereq',   -- prereq | coreq
    group_no    INTEGER NOT NULL,                 -- AND across groups, OR within a group
    req_code    TEXT,                             -- a course code, or NULL for a non-course rule
    min_grade   TEXT,                             -- "C", "C-", ... or NULL
    concurrent  INTEGER NOT NULL DEFAULT 0,       -- "may be taken concurrently"
    note        TEXT                              -- non-course rule as written, e.g. "Math Placement - ALEKS with a score of 061"
);
CREATE INDEX prerequisites_course ON prerequisites(course_code);

CREATE TABLE course_attributes (
    course_code TEXT NOT NULL REFERENCES courses(code),
    attr_code   TEXT NOT NULL,               -- "CFQL"
    attr_name   TEXT NOT NULL,               -- "Core Ed - Quantitative Literacy & Analysis"
    PRIMARY KEY (course_code, attr_code)
);

CREATE TABLE programs (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,             -- "Computer Science"
    kind          TEXT NOT NULL,             -- major | minor | option | certificate | core
    degree        TEXT,                      -- "BA, BS, HBA, HBS"
    level         TEXT NOT NULL,             -- undergraduate | graduate
    college       TEXT,
    parent_id     INTEGER REFERENCES programs(id),   -- an option's major
    total_credits REAL,
    ecampus       INTEGER NOT NULL DEFAULT 0,
    catalog_url   TEXT                       -- public catalog page; NULL only for the synthetic Core Education program
);

-- One row per requirement line in a program's course list. kind:
--   course  = one specific course (or any one of its alternatives in requirement_courses)
--   choice  = pick `pick_count` courses, or `credits` credits, from requirement_courses
--   credits = free credits described only by `label` (e.g. "Select 16 upper-division CS credits"); no course list
CREATE TABLE program_requirements (
    id          INTEGER PRIMARY KEY,
    program_id  INTEGER NOT NULL REFERENCES programs(id),
    block       TEXT NOT NULL,               -- "Required Core", "Core Education", "Major Requirements"
    seq         INTEGER NOT NULL,            -- order on the catalog page
    kind        TEXT NOT NULL,               -- course | choice | credits
    label       TEXT NOT NULL,               -- "CS 161 Introduction to Computer Science I" or the catalog's own wording
    credits     REAL,
    pick_count  INTEGER,                     -- for kind=choice when it is "choose N courses"
    plan_year   INTEGER,                     -- 1-4 from the catalog's sample plan, when it lists this course
    plan_term   TEXT                         -- Fall | Winter | Spring
);
CREATE INDEX program_requirements_program ON program_requirements(program_id, seq);

CREATE TABLE requirement_courses (
    requirement_id INTEGER NOT NULL REFERENCES program_requirements(id),
    course_code    TEXT NOT NULL,            -- may name a course missing from `courses` (kept as written)
    with_code      TEXT,                     -- "CH 201 & CH 204": the second course that must be taken with it
    PRIMARY KEY (requirement_id, course_code)
);
CREATE INDEX requirement_courses_code ON requirement_courses(course_code);

-- ---- invented schedule ------------------------------------------------------------------------
CREATE TABLE terms (
    code        TEXT PRIMARY KEY,            -- "202702"
    name        TEXT NOT NULL,               -- "Winter 2027"
    season      TEXT NOT NULL,               -- Fall | Winter | Spring | Summer
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    status      TEXT NOT NULL,               -- past | current | registration | future
    view_only   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sections (
    crn           INTEGER PRIMARY KEY,       -- invented 5-digit number
    term_code     TEXT NOT NULL REFERENCES terms(code),
    course_code   TEXT NOT NULL REFERENCES courses(code),
    section       TEXT NOT NULL,             -- "001"; 000-399 Corvallis, 400-499 Ecampus, 500-599 Cascades, 600-699 INTO
    schedule_type TEXT NOT NULL,             -- Lecture | Recitation | Laboratory | Seminar | Studio | Activity | Online | Independent Study
    method        TEXT NOT NULL,             -- In person | Online | Hybrid
    campus        TEXT NOT NULL,             -- Corvallis | Ecampus | Cascades | INTO OSU
    session       TEXT NOT NULL DEFAULT 'Full term',
    credits       REAL NOT NULL,             -- 0 for a linked recitation or lab
    grade_mode    TEXT NOT NULL,             -- "Normal grading (A-F)" | "Pass/No pass"
    instructor    TEXT,                      -- clearly fictional name, or NULL ("Staff")
    seats_total   INTEGER NOT NULL,
    seats_taken   INTEGER NOT NULL,
    wait_cap      INTEGER NOT NULL DEFAULT 0,
    wait_count    INTEGER NOT NULL DEFAULT 0,
    fee           REAL,                      -- course fee in dollars, or NULL
    restrictions  TEXT,                      -- e.g. "Honors College students only", or NULL
    is_primary    INTEGER NOT NULL DEFAULT 1 -- 1 = carries the credits; 0 = linked recitation/lab
);
CREATE INDEX sections_course ON sections(term_code, course_code);

CREATE TABLE meetings (
    id         INTEGER PRIMARY KEY,
    crn        INTEGER NOT NULL REFERENCES sections(crn),
    days       TEXT,                         -- letters from MTWRF, e.g. "MWF", "TR"; NULL = to be announced
    start_min  INTEGER,                      -- minutes after midnight; NULL = to be announced
    end_min    INTEGER,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    building   TEXT,                         -- invented building name, or NULL
    room       TEXT
);
CREATE INDEX meetings_crn ON meetings(crn);

CREATE TABLE linked_sections (               -- a student must pick one linked section with the lecture
    lecture_crn INTEGER NOT NULL REFERENCES sections(crn),
    linked_crn  INTEGER NOT NULL REFERENCES sections(crn),
    PRIMARY KEY (lecture_crn, linked_crn)
);

-- ---- made-up students -------------------------------------------------------------------------
-- Dates that should feel current are stored as offsets from "today" and turned into real dates when served.
CREATE TABLE students (
    id             INTEGER PRIMARY KEY,
    slug           TEXT NOT NULL UNIQUE,     -- "juniper"
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    pronouns       TEXT,
    email          TEXT NOT NULL,            -- always @example.com
    sample_id      TEXT NOT NULL,            -- "SAMPLE-0001": never shaped like a real OSU ID
    program_id     INTEGER NOT NULL REFERENCES programs(id),
    minor_id       INTEGER REFERENCES programs(id),
    standing       TEXT NOT NULL,            -- First-year | Sophomore | Junior | Senior
    campus         TEXT NOT NULL,            -- Corvallis | Ecampus
    is_transfer    INTEGER NOT NULL DEFAULT 0,
    gpa            REAL,
    major_gpa      REAL,
    credits_earned REAL,
    academic_standing TEXT,                  -- "Good standing"
    advisor_name   TEXT NOT NULL,            -- clearly fictional
    advisor_office TEXT NOT NULL,            -- e.g. "College of Engineering advising"
    reg_weekday    INTEGER NOT NULL,         -- 0=Monday: registration opens on the next such weekday
    reg_time       TEXT NOT NULL,            -- "07:00"
    situation      TEXT NOT NULL,            -- one line shown in the student switcher
    blurb          TEXT NOT NULL             -- two or three sentences about what this student shows off
);

CREATE TABLE student_courses (
    id             INTEGER PRIMARY KEY,
    student_id     INTEGER NOT NULL REFERENCES students(id),
    course_code    TEXT NOT NULL,
    title          TEXT NOT NULL,
    term_code      TEXT,                     -- NULL for transfer credit
    status         TEXT NOT NULL,            -- completed | in_progress | planned | transfer
    grade          TEXT,                     -- "A-", "T" for transfer, NULL while in progress
    credits        REAL NOT NULL,
    crn            INTEGER,                  -- the section, for in_progress and planned rows
    linked_crn     INTEGER,                  -- its recitation or lab, when it has one
    transfer_from  TEXT,                     -- "MATH 251 at Sample Community College"
    requirement_id INTEGER REFERENCES program_requirements(id)   -- the requirement it fills in the student's own program
);
CREATE INDEX student_courses_student ON student_courses(student_id);

CREATE TABLE student_holds (
    id           INTEGER PRIMARY KEY,
    student_id   INTEGER NOT NULL REFERENCES students(id),
    type         TEXT NOT NULL,              -- advising | financial | health | records
    title        TEXT NOT NULL,
    reason       TEXT NOT NULL,              -- plain language
    office       TEXT NOT NULL,
    how_to_clear TEXT NOT NULL,
    blocks_registration INTEGER NOT NULL DEFAULT 1,
    placed_offset_days  INTEGER NOT NULL,    -- negative: days before today
    info_url     TEXT                        -- a public OSU page about this kind of hold, when one is stored
);

CREATE TABLE student_tasks (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    title      TEXT NOT NULL,
    detail     TEXT,
    due_offset_days INTEGER,
    status     TEXT NOT NULL,                -- open | done
    kind       TEXT NOT NULL                 -- task | success_plan
);

CREATE TABLE appointments (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    with_name  TEXT NOT NULL,
    with_role  TEXT NOT NULL,                -- "Academic advisor"
    topic      TEXT NOT NULL,
    offset_days INTEGER NOT NULL,            -- negative = past
    start_time TEXT NOT NULL,                -- "14:30"
    minutes    INTEGER NOT NULL,
    mode       TEXT NOT NULL,                -- In person | Zoom | Phone
    location   TEXT,
    status     TEXT NOT NULL                 -- upcoming | past | cancelled
);

CREATE TABLE advisor_slots (                 -- open times a student can book with their advisor
    id          INTEGER PRIMARY KEY,
    student_id  INTEGER NOT NULL REFERENCES students(id),
    offset_days INTEGER NOT NULL,            -- 1..10; weekends are skipped when served
    start_time  TEXT NOT NULL,
    minutes     INTEGER NOT NULL,
    mode        TEXT NOT NULL,
    location    TEXT
);

CREATE TABLE balances (
    student_id       INTEGER PRIMARY KEY REFERENCES students(id),
    term_code        TEXT NOT NULL,
    balance          REAL NOT NULL,
    due_offset_days  INTEGER NOT NULL,       -- negative = past due
    past_due         REAL NOT NULL DEFAULT 0,
    plan_enrolled    INTEGER NOT NULL DEFAULT 0,
    meal_plan        REAL,                   -- dining dollars left, or NULL
    orange_cash      REAL
);

CREATE TABLE transactions (
    id          INTEGER PRIMARY KEY,
    student_id  INTEGER NOT NULL REFERENCES students(id),
    term_code   TEXT NOT NULL,
    offset_days INTEGER NOT NULL,
    description TEXT NOT NULL,
    amount      REAL NOT NULL                -- positive = charge, negative = payment or aid
);

-- ---- plain-language maps ----------------------------------------------------------------------
CREATE TABLE resources (                     -- one entry per BeaverHub tool name, in plain language
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    plain       TEXT NOT NULL,               -- what it is, in one plain sentence
    use_for     TEXT,                        -- "Use this to ..."
    same_as     TEXT,                        -- other names for the same thing, comma separated
    category    TEXT NOT NULL,               -- Academic | Technology | Financial | Wellness | Transportation | Getting Involved | Accessibility
    needs_login INTEGER NOT NULL DEFAULT 0,
    url         TEXT                         -- a public OSU page stored in the crawl, or NULL
);

CREATE TABLE forms (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    purpose  TEXT NOT NULL,                  -- what it's for, plain language
    goes_to  TEXT NOT NULL,                  -- the office that receives it
    when_to_use TEXT,
    url      TEXT NOT NULL,                  -- OSU's copy (public page or PDF found in the crawl)
    kind     TEXT NOT NULL,                  -- PDF | Online form | Page
    fields   TEXT NOT NULL                   -- JSON list of field names the preview fills from the sample student
);
