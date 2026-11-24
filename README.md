# care_publicforms

A [Care](https://github.com/ohcnetwork/care) plugin that runs **patient
satisfaction surveys on touch-screen kiosks**. The pages are rendered on the
server, so they need no frontend build and work on the limited browsers in
TVs and signage players, even with JavaScript off.

It ships the two NQAS formats, **OPD feedback** (10 ratings) and **inpatient
feedback** (20 ratings), each with the patient details and four open
questions. Forms and questions can be changed in the admin.

The pages are **public**: no login, session or cookie. The plugin has two
tables, forms and submissions, and doesn't link to Care's tables (a facility
is kept by its id). [docs/architecture.md](docs/architecture.md) describes
the design.

## Features

- **The whole questionnaire is one page, sent once.** `kiosk.js` moves
  between the steps without reloading. Without JavaScript each step posts
  the page and the server shows the next one.
- **Identify by QR, UHID or as a guest:** a QR read by the camera or a USB
  scanner (holding the UHID, or the patient's id in Care, whose UHID at the
  facility is looked up), an on-screen keypad, or no UHID at all.
- **Questions on pages you lay out:** details, rating cards and open
  questions, page by page in any order, each page with its own heading and
  button label if you like (see [Writing a questionnaire](#writing-a-questionnaire)).
- **Several languages:** a header toggle, each text per language, English as
  the fallback. The language a patient picks stays with them until the
  thank-you page; the next patient starts in the screen's language.
- **Safe on a shared screen:**
  - **Idle reset:** after 90 s without a touch the screen starts over,
    with an "Are you still there?" warning for the last 15 s. An untouched
    screen never reloads.
  - **Home** (on every page after the first) and **Reset** (from the
    first rating on) ask before clearing answers. Reset keeps the UHID and
    the details before the ratings.
  - **Back** never shows the previous patient's page or reference number.
  - **Reloading or closing with answers** asks first (the browser's "Leave
    site?"; not on iPhone or iPad). Pull-to-refresh is off in Chromium.
  - **Changing the UHID or switching to guest** keeps every answer and
    returns to the same question.
- **Checked twice:** in the browser and on the server. Text that could carry
  code (`<` `>` `{` `}` `` ` `` `\`) is refused, and submissions are
  rate-limited.
- **Its own admin**, apart from Django's `/admin/`, plus an API and CSV
  export for reports.
- **Care's colours**, one column that scales to TVs, tablets and phones.
- **Accessible:** every control is named in the current language, errors
  are announced, and a TV remote's arrows and OK work.

Without JavaScript the kiosk still works, with these differences: each step
reloads the page (Home and Reset still ask first, on a reloaded page); there
is no QR camera or on-screen keypad (the UHID is typed, so the screen needs a
keyboard or a keyboard-mode scanner); since the page can't see touches, it
starts over 3 minutes after each page loads, with a countdown in the header
for the last minute (not on the first page, which looks like the home screen,
unless something is entered there); and Back after it starts over shows the
browser's "Confirm form resubmission" page rather than the previous answers.

## Installation

The repository and Python package are `care_publicforms`. The Django app
inside is `public_forms`: the plug's `name`, its URL prefix and its `configs`
key.

### Production

Add the plug to Care's [`plug_config.py`](https://github.com/ohcnetwork/care/blob/develop/plug_config.py),
then rebuild the image and run migrations. Care's start scripts collect the
plugin's CSS and JS. Then give each facility its forms (see
[Forms and questions](#forms-and-questions)).

```python
public_forms_plug = Plug(
    name="public_forms",
    package_name="git+https://github.com/egovhealthcare/care_publicforms.git",
    version="@main",
    configs={},  # see Settings
)
plugs = [public_forms_plug]
```

### Local development (Care in Docker)

1. Clone the plugin inside the Care checkout, so it is mounted at
   `/app/care_publicforms`: `cd care && git clone https://github.com/egovhealthcare/care_publicforms.git`
2. In `plug_config.py`, use `package_name="/app/care_publicforms"` and
   `version=""`.
3. In `plugs/manager.py`, install in editable mode
   (`[sys.executable, "-m", "pip", "install", "-e", *packages]`), then
   `make re-build`, `make up` and `make migrate`.
4. Give a facility the default forms:
   `docker compose exec backend python manage.py seed_feedback_forms <facility-id>`.

> [!IMPORTANT]
> Don't commit the `plug_config.py` / `plugs/manager.py` changes to Care.

## Putting a form on a screen

Open the facility's page on the screen and make it the browser's start page:

- `/facility/<facility_id>/public_forms/`: patients choose a form (it opens
  directly if only one is active).
- `/facility/<facility_id>/public_forms/type/<form code>/form/`: the screen
  stays on that form.

The admin shows each form's link. A screen can set options in the URL, e.g.
`…/type/ipd/form/?lang=en&scan=scanner`:

| Parameter | What it does |
| --- | --- |
| `lang=<code>` | The language each new patient starts in. Default: `DEFAULT_LANGUAGE`. |
| `scan=camera` | Read the QR with the camera. Needs HTTPS and a browser with `BarcodeDetector` (Chrome on Android, ChromeOS, macOS); hidden when it can't work. |
| `scan=scanner` | A USB/Bluetooth QR scanner in keyboard mode, on any browser. |
| `scan=off` | No scan option. |
| `keypad=0` / `keypad=1` | The on-screen number pad for the UHID. Keep it on for screens without a system keyboard. |

> [!NOTE]
> The pages are served by the Care **backend**. If care_fe and the backend
> share a domain, route `^/facility/[^/]+/public_forms/` (and the admin's
> path) to the backend.

Kiosk tips:

- Chromium: `chromium --kiosk --disable-pinch --overscroll-history-navigation=0 "https://<care-api-host>/facility/<facility_id>/public_forms/type/opd/form/"`.
- The camera needs HTTPS and the site's camera permission; if permission is
  refused, the scan option is hidden.
- Following NQAS guidance, take exit feedback: put the OPD kiosk near the
  pharmacy and the inpatient kiosk where patients are discharged.
- A QR can hold the UHID: it counts when it has exactly 11 digits once other
  characters are removed (`UHID:123-4567-8901` works).
- Or it can hold the **patient's id in Care** (a UUID, alone or inside a
  link), as Care's patient QR codes do. The kiosk then looks up the patient's
  UHID, and shows and stores only that. The UHID is the patient's identifier
  from the active patient identifier config named **UHID** in Care (its
  display name, or set `UHID_IDENTIFIER` to another name or to its
  *system*). Set `UHID_IDENTIFIER_SCOPE` to say where that config is
  defined: `system` (the default: one system-wide config for every
  facility) or `facility` (each facility's own config, so each kiosk uses
  its facility's UHIDs). A patient without that identifier gets "We
  couldn't read a UHID from that code" and can type the UHID or continue as
  a guest. The value must be
  in the kiosk's UHID format (`UHID_LENGTH` digits once other characters are
  removed).
- Without internet access to Google Fonts, set `LOAD_WEB_FONTS=False` and
  install DM Sans and each language's `font` on the device.

## The admin

Forms and submissions are managed at `https://<care-api-host>/public_forms/admin/`
(the `ADMIN_URL` setting). It is separate from Django's `/admin/` and holds
only **Feedback forms** and **Feedback submissions**.

- **Who can sign in:** Care superusers, and active users given any of this
  app's permissions, with their Care username and password. They don't need
  Django staff access, so the rest of Django's admin stays closed to them.
- **Which facilities:** the permissions below say what a user may do; their
  Care roles say where. Superusers see every facility. Anyone else sees only
  the facilities where they hold a role with the Care permission below, in
  the facility itself or in an area organization above it (a district admin
  sees the district's facilities). Without such a role they see nothing,
  even with the permissions below. Another facility's submission can't be
  opened by its address or exported.
- **Giving access:** in Django's admin, add the permissions to the user or
  their group (**User permissions**, the ones starting `public_forms |`):

  | To | Permissions (Django admin) | At facilities where their Care role has |
  | --- | --- | --- |
  | View and export submissions | `Can view feedback submission` | `can_view_resource_responses` (what the API checks) |
  | View forms | `Can view feedback form` | `can_view_resource_responses` or `can_update_facility` |
  | Edit forms | `Can change feedback form` (and `Can add` / `Can delete` to create or remove forms) | `can_update_facility` |

  On Care 3.0, which has no `can_view_resource_responses`, only superusers
  see submissions.

- **Sign-in limit:** 5 attempts a minute per IP address and per username
  (`ADMIN_LOGIN_RATE_LIMIT`).
- Like the kiosk pages, the admin is served by the Care backend: open it on
  the API host, or route its path there.

## Forms and questions

In the admin, under **Feedback forms**, each form has:

- **Code** (`opd`, `ipd`): stored with every response, used in the URL and
  in reference numbers (`OPD-20261118-4821`, first 12 characters).
- **Patient type** (OP or IP), **title** and **description** per language,
  **active** and **order**.
- **Facility id** (required): the facility that offers the form, the UUID
  in its Care URL. Every facility has its own forms, and uses a code once.
- **Pages:** one JSON list of pages, each with its questions (below). The
  admin checks it on save and names the page or question in every error.

A form that has feedback can't be deleted; switch it off instead.

A new facility has no forms, and its screens say so. Give it the default
OPD and inpatient forms, then edit them in the admin:

```bash
python manage.py seed_feedback_forms <facility-id> [<facility-id> …]
```

It only adds the default forms a facility doesn't have, so it also brings
back a deleted one. Forms used to be shared when they had no facility id;
upgrading to this version (migration `0005`) gives each facility that has
feedback on a shared form its own copy, moves that feedback to it, and then
removes the shared forms. Seed the other facilities afterwards.

Forms used to list their questions with a `step` number each, plus optional
step titles. Migrations `0007` and `0008` turn every form's steps into
pages, in the same order, each step's title and lead becoming its page's
`title` and `description`, so nothing moves on screen.

### Writing a questionnaire

For a step-by-step guide written for non-developers, with every question
type, how pages are formed and common recipes, see
[docs/questionnaire-guide.md](docs/questionnaire-guide.md).

A small but complete questionnaire:

```json
[
  {"title": {"en": "About your visit"},
   "questions": [
     {"key": "clinic", "type": "choice", "required": true,
      "text": {"en": "Which clinic did you visit?"},
      "options": [{"value": "general", "en": "General Medicine"},
                  {"value": "eye", "en": "Eye"}]},
     {"key": "visit_date", "type": "date",
      "text": {"en": "Date of your visit"}}
   ]},

  {"questions": [
     {"key": "doctor", "type": "rating",
      "text": {"en": "How well did the doctor explain things?"},
      "short_text": {"en": "Doctor"}},
     {"key": "cleanliness", "type": "rating",
      "text": {"en": "How clean was the hospital?"},
      "short_text": {"en": "Cleanliness"}}
   ]},

  {"primary_button": {"en": "Check my answers"},
   "questions": [
     {"key": "come_back", "type": "choice", "allow_comment": true,
      "text": {"en": "Would you come back to this hospital?"},
      "options": [{"value": "yes", "en": "Yes"}, {"value": "no", "en": "No"}]},
     {"key": "suggestions", "type": "text",
      "text": {"en": "Any other suggestions?"}}
   ]}
]
```

After the patient identifies, this shows:

1. **Page 1:** one screen headed "About your visit", with the clinic and the
   date. Its button says "Start the questions".
2. **Page 2:** one card per rating.
3. **Page 3:** one screen with *Yes* / *No* buttons, a "Why?" box and a text
   box. Its button says "Check my answers".
4. **The review**, then Submit and a reference number.

Rules:

- **Pages come in list order** (up to 99). On a page, questions keep their
  order in its list. A question is asked on the page it's listed in.
- **A page holds either ratings (a card each) or other questions (one
  screen), not both.**
- **A screen's look depends on its place.** Before the first ratings it is
  compact ("A few quick details"). After them it is larger ("In your own
  words"), and a choice of 2 or 3 options shows as large buttons. A page's
  `title` (and `description`) replaces the default heading.
- **The main button says where it leads:** "Start the questions" before the
  first ratings, "Review answers" before the review, otherwise "Next". A
  page's `primary_button` replaces it, except when the patient came from the
  review to change an answer: then it always says "Review answers". Rating
  pages take no `title`, `description` or `primary_button`; the last card
  of a form that ends with ratings says "Review answers".
- **A screen with nothing for this patient is skipped,** e.g. guest-only
  questions for a patient who gave a UHID.
- **Home appears on every page after the first; Reset from the first
  ratings on.** Reset clears the ratings and the screens after them, and
  keeps the screens before them.
- **Every text is per language:** `"en"` is required, plus
  `"<code>": "…"` for each other language. Missing languages show the
  English.
- **`key` is where answers are stored.** Keep it once feedback has come in;
  a question with a new meaning needs a new key. Each answer is saved with
  its question's wording, so later edits don't change past feedback.
- **Limits per language:** a page's `title` 100 characters, `description`
  300, `primary_button` 40; a question's `text` and `hint` 300, `short_text`
  60, option labels 100; option `value` 64. Answers hold up to 2000
  characters.

A page:

| Field | Default | Meaning |
| --- | --- | --- |
| `questions` | required | The page's questions, in the order asked; at least one |
| `title` | `{}` | The page's heading; empty → the default heading |
| `description` | `{}` | A line under the heading |
| `primary_button` | `{}` | The main button's label; empty → "Start the questions", "Next" or "Review answers" |

A question:

| Field | Default | Meaning |
| --- | --- | --- |
| `key` | required | Lowercase letters, digits and `_`; unique in the form |
| `type` | required | `choice`, `date`, `rating` or `text` |
| `text` | required | The question; English required |
| `short_text` | `{}` | Shorter label on the review |
| `hint` | `{}` | Hint under the question |
| `options` | `[]` | `choice`: `[{"value": "ent", "en": "ENT"}, …]`. `rating`: optionally five labels, Poor → Excellent |
| `required` | `false` | Needs an answer (ratings always do) |
| `audience` | `"all"` | `all`, `guest` (no UHID) or `identified` (gave a UHID) |
| `allow_no_comment` | `true` | Ratings: offer "No comments" |
| `allow_comment` | `false` | Choices: also ask "Why?" |
| `active` | `true` | `false` keeps the question without asking it |

A **yes/no** question is a `choice` with the options `yes` and `no`. A `date`
can't be in the future. A `text` box is one line before the ratings and two
after them; with JavaScript it grows as the patient types, up to eight lines.
Typed answers keep their line breaks (saved as `\n`), and the admin shows
them.

## Viewing feedback

Each submission (`care_publicforms_submission`) has its reference number,
facility id, form, language, UHID (empty for guests), time, and `answers`:
every answered question under its key, with the question as asked.

```json
{
  "clinic": {"question": "Clinic visited", "type": "choice", "value": "ent", "answer": "ENT"},
  "registration_wait": {"question": "Waiting time at the registration counter",
                        "type": "rating", "value": 2, "answer": "10-30 mins"},
  "would_return": {"question": "Would you come back to this hospital for treatment?",
                   "type": "choice", "value": "yes", "answer": "Yes", "comment": "Friendly staff"},
  "improvement": {"question": "What would you most like to see improved?",
                  "type": "text", "value": "Shorter queue at registration"}
}
```

`value` is a rating `0`–`5` (`0` = No comments, left out of averages), a
choice's code, a `YYYY-MM-DD` date or the text typed. `answer` is the label
picked and `comment` the "Why?". Wording is in English; the patient's
language is in the `language` column.

- **Admin → Feedback submissions:** filter by OP/IP, form and language;
  search by reference or UHID; each shows its answers with the questions as
  asked; **Export selected as CSV** (one column per question key, a "Why?"
  in `<key>__comment`). Submissions are read-only.
- **API** (Care login, with permission to view the facility's questionnaire
  responses):
  - `GET /api/public_forms/facility/<facility_id>/responses/`: the
    submissions, paginated.
  - `GET /api/public_forms/facility/<facility_id>/summary/`: per form, the
    overall score, each attribute's average and spread, the two
    lowest-scoring attributes and counts for choice questions.
  - Both take `patient_type` (`op` | `ip`), `form`, and `submitted_after` /
    `submitted_before` (YYYY-MM-DD).
  - `GET /api/public_forms/health` returns `OK`.

## Settings

Set in the plug's `configs={}`, or as environment variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `LANGUAGES` | `["en", "kn"]` | Languages offered, in order (env: `LANGUAGES=en,kn`). Each needs a locale file; one language hides the toggle. The admin shows a text box for each on a form's title and description. |
| `DEFAULT_LANGUAGE` | `"en"` | Starting language; a screen can override it with `?lang=`. |
| `LOCALE_DIRS` | `[]` | Extra folders of locale files, to add or correct a language without changing the plugin. Restart after editing them. |
| `SCAN_MODE` | `"camera"` | `camera`, `scanner` or `off`; a screen can override it with `?scan=`. |
| `SHOW_KEYPAD` | `True` | The on-screen UHID keypad; a screen can override it with `?keypad=`. |
| `UHID_LENGTH` / `UHID_GROUPS` | `11` / `[3, 4, 4]` | UHID digits, and their grouping on screen (must add up to the length). |
| `UHID_IDENTIFIER` | `"UHID"` | For QR codes that hold the patient's id: the patient identifier config in Care that holds the UHID, by its display name or its *system* (any letter case). |
| `UHID_IDENTIFIER_SCOPE` | `"system"` | Where that config is defined in Care: `system` (one system-wide config) or `facility` (each facility's own). Anything else finds no UHID, and `manage.py check` warns. |
| `QR_LOOKUP_RATE_LIMIT` | `"30/m"` | UHID lookups from patient QR codes per IP address (`""` turns it off). |
| `REFERENCE_PREFIX` | `""` | Start of reference numbers; empty uses the form's code. |
| `IDLE_TIMEOUT_SECONDS` | `90` | Seconds without a touch before the screen warns, then starts over. |
| `NO_JS_IDLE_TIMEOUT_SECONDS` | `180` | Without JavaScript: seconds after a page loads before it starts over (the header counts down the last minute; `0` turns it off). |
| `DONE_TIMEOUT_SECONDS` | `20` | How long the thank-you page stays up. |
| `SUBMIT_RATE_LIMIT` | `"60/m"` | Submissions per IP address (django-ratelimit rate; `""` turns it off). A kiosk is one IP, so keep it well above a busy hour. |
| `ADMIN_URL` | `"public_forms/admin"` | Path of the admin; read when Care starts. |
| `ADMIN_LOGIN_RATE_LIMIT` | `"5/m"` | Admin sign-in attempts per IP address and per username (`""` turns it off). |
| `LOAD_WEB_FONTS` | `True` | Load DM Sans and the languages' fonts from Google Fonts. |

**Behind a proxy**, every request seems to come from the proxy, so the rate
limits are shared by all kiosks. Set Django's `RATELIMIT_IP_META_KEY` in Care
to the header the proxy sets (e.g. `HTTP_X_REAL_IP`). Care's
`DISABLE_RATELIMIT` turns off every limit.

## Languages

A language has a **locale file** for the screen text, and its text in each
**form** (titles, questions, options) under the same code. Anything missing
shows in English.

Locale files live in [`src/public_forms/locale/`](src/public_forms/locale),
one per language (`<code>.json`):

```json
{
  "language": {"name": "Kannada", "toggle": "ಕನ್ನಡ", "font": "Noto Sans Kannada", "tall_script": true},
  "strings": {"back": "…", "next": "…", "…": "…"},
  "ratings": {"5": "…", "4": "…", "3": "…", "2": "…", "1": "…", "0": "…"}
}
```

- `name`: for screen readers and the admin. `toggle`: the header button.
- `font`: a Google Fonts family for the script (`null` if DM Sans covers it).
- `tall_script`: `true` for scripts with tall letters and no capitals (most
  Indian scripts): no uppercase labels, more line height.
- `strings`: the screen text, keyed as in `en.json`; keep placeholders such
  as `{n}`. `ratings`: the default rating labels, 5 (Excellent) to 0 (No
  comments).

`manage.py check` warns about unreadable files, untranslated strings,
changed placeholders and unknown keys.

### Adding a language

1. **Locale file:** copy `locale/en.json` to `locale/<code>.json` and
   translate it.
2. **The default forms' text:** add a data migration that adds the language
   to them. It only fills text that is still the default English, so forms
   edited in the admin keep their edits, and `seed_feedback_forms` reuses
   it. `TRANSLATIONS` maps each English text of the default forms (in
   `seed.py`) to the language:

   ```python
   # src/public_forms/migrations/0007_hindi_default_forms.py
   from django.db import migrations

   from public_forms.seed import add_language_to_forms

   LANGUAGE = "hi"
   TRANSLATIONS = {"OPD feedback": "…", "Clinic visited": "…", "ENT": "…"}  # …every English text


   def forwards(apps, schema_editor):
       add_language_to_forms(apps.get_model("public_forms", "FeedbackForm"), LANGUAGE, TRANSLATIONS)


   class Migration(migrations.Migration):
       dependencies = [("public_forms", "0006_form_facility_required")]
       operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
   ```

   Then run `manage.py migrate`. For your own forms, type the text in the
   admin.
3. **Turn it on:** add the code to `LANGUAGES` (e.g. `["en", "hi"]`; the
   list replaces the default) and restart.

The tests check that every bundled locale file is complete and that the
default forms have every text in each of those languages. For a single
deployment, put the locale file in a `LOCALE_DIRS` folder instead. Have a
native speaker check a language before patients use it.

## Development

```
src/public_forms/
├── views.py, pages.py    # the public pages and their URLs
├── api.py, urls.py       # the staff API (/api/public_forms/)
├── admin.py, admin_site.py
├── questions.py          # the questions JSON: fields, defaults, checks
├── questionnaire.py      # a form → its screens; answer parsing
├── steps.py              # navigation without JavaScript (mirrors kiosk.js)
├── services.py           # UHID format, collecting and saving answers
├── text_rules.py         # blocked characters and length limits
├── seed.py, migrations/  # the default forms, adding a language
├── i18n.py, locale/      # languages and their screen text
├── templates/, static/   # pages, kiosk.css, kiosk.js
└── tests/
e2e/                      # Playwright tests
```

**Django tests**, from the Care checkout with the plugin installed:

```bash
python manage.py test public_forms --keepdb
```

They use English and a generated test language, whatever `plug_config.py`
sets. Lint with `ruff check src && ruff format src`.

**Browser tests** run Chromium against a running Care backend. They cover
the patient flows, the shared-screen safeguards, the camera and scanner, the
languages, the idle reset, the flow without JavaScript, and the layout on
five screen shapes:

```bash
cd e2e && npm install
npx playwright install chromium   # once
PF_FACILITY_ID=<facility external id> npx playwright test
```

- `PF_FACILITY_ID` needs the default forms: run `seed_feedback_forms` for it
  first.
- `PF_BASE_URL` sets the backend (default `http://localhost:9000`).
- The tests submit feedback, so use a development database.
- They open pages with `?lang=en`, so any `LANGUAGES` works; the language
  tests use the first language after English and skip when there is none.
- `npx playwright show-report` opens the last run; the layout tests save a
  screenshot of every step per screen shape in `e2e/screenshots/`.
