# care_publicforms

**Public forms** is a [Care](https://github.com/ohcnetwork/care) plugin
that runs **patient satisfaction surveys (OPD and inpatient) on touch-screen
TV kiosks**. The
pages are rendered on the server (Django templates), so it needs no frontend
build and works on the limited browsers built into TVs and signage players,
even with JavaScript switched off.

The forms and questions are configurable. It ships with the two NQAS patient
satisfaction formats: **OPD feedback** (10 attributes) and **inpatient
feedback** (20 attributes), each with four open questions and the patient
details from the paper form.

Flow (in each language of the `LANGUAGES` setting):

```
choose form (OP visit / IP stay)        ← skipped on a screen pinned to one form
  → identify: scan QR on OP slip | type UHID | continue as guest
  → a few details (clinic / ward, date of admission; age and sex for guests)
  → ratings, one card at a time (Poor → Excellent, No comments)
  → open questions → review → thank you + reference number
```

The pages are **public**: anyone in the hospital can open them, with no
login, kiosk key, session or cookie. The plugin has **two tables**: forms
(each with its questions as one JSON list) and submissions (one row per
response, each answer saved with its question). The **only relation** is
between them: each submission belongs to its form. **Nothing links to
Care's tables**: facilities are kept by their id.

For how it is built (request flow, the in-browser step machine, languages,
validation) and the database tables, see
[docs/architecture.md](docs/architecture.md).

## How it works

- **One page per form, posted once.** The whole questionnaire (identify,
  details, every rating, open questions, review) is one server-rendered form
  with every language in it. `kiosk.js` shows one step at a time and
  switches language instantly; the form controls are the only state. Nothing
  reaches the server until the patient taps *Submit feedback*, which posts
  the page once. The server validates it and either saves it and shows the
  thank-you page, or shows the page again at the first step with a problem.
- **JavaScript is optional.** Without it the kiosk still goes step by step,
  with the same screens, checks, review and guest option: each step button
  posts the page (every answer so far travels in it) and the server shows the
  next step, still with no session. `kiosk.js` (ES5, no dependencies) makes
  the steps instant (no reload) and adds the UHID cells and on-screen keypad,
  QR scanning, auto-advance on ratings and the idle warning. Without
  JavaScript a UHID is typed in a plain field (or by a keyboard-mode scanner)
  and an idle step starts over after `IDLE_TIMEOUT_SECONDS`.
- **Nothing stored until submit.** No session, cookie or draft rows; the
  UHID is stored as entered and is not looked up in Care. Submissions are
  rate-limited per IP address (`SUBMIT_RATE_LIMIT`; see
  [Behind a proxy](#behind-a-proxy)).
- **Checked twice.** The browser checks each step before moving on (required
  answers, a UHID of the right length, no dates in the future), and the
  server checks the whole page again on submit. If anything is wrong the page
  comes back at the first step with a problem, with every answer kept and
  the problem marked in red.
- **Configurable forms.** Forms and questions live in the database and are
  edited in the Django admin, with a text box per language. See
  [Forms and questions](#forms-and-questions).
- **care_fe look.** Styled with care_fe's CareUI theme (Figtree, emerald
  primary, neutral greys, care_fe buttons/cards), using hex colours so older
  TV browsers render it.
- **One layout on every screen.** The original single-column kiosk design
  is used everywhere. Sizes are in `rem`, so on TVs the column scales up to
  the screen (the smaller of height/60 and width/32). A question fits
  without scrolling on 1920×1080, 960×540 TV browsers, 1080×1920 portrait
  and tablets. The longer comments and review steps scroll, with their main
  button pinned at the bottom.
- **Home and Reset.** From the first rating question on (ratings, open
  questions, review), the header shows *Home*, which drops everything and
  goes back to the chooser (or the start of a pinned form), and *Reset*,
  which clears the ratings and open answers and goes back to the first
  question, keeping the UHID and details.
- **Unattended use.** Once someone has used the screen, 90 s without a
  touch shows *"Are you still there?"*, then reloads the start page in the
  screen's own language, which drops everything entered. The timer runs from
  the moment a page holds a patient's choices (their form, their language,
  or their answers sent back after a failed submit), so nothing is left on
  screen for the next patient; an untouched screen never reloads.
- **Accessible.** Every control has a name in the current language
  (screen readers, TV remotes), errors are announced, ratings are real
  radio groups, and a TV remote's OK button picks the focused answer.

## Installation

The repository and Python package are `care_publicforms`. The Django app
inside is `public_forms`: the plug's `name`, the start of its URLs and its
`configs` key. The tables keep the repository's name:
`care_publicforms_form` and `care_publicforms_submission`.

### Production

Add the plug to [`plug_config.py`](https://github.com/ohcnetwork/care/blob/develop/plug_config.py) in Care:

```python
public_forms_plug = Plug(
    name="public_forms",
    package_name="git+https://github.com/egovhealthcare/care_publicforms.git",
    version="@main",
    configs={},  # see Settings below
)
plugs = [public_forms_plug]
```

Then rebuild the image and run migrations. Care's start scripts run
`collectstatic`, which picks up the plugin's CSS and JS.

### Local development (Care in Docker)

1. Put the plugin inside the Care checkout so it is mounted into the
   container at `/app/care_publicforms`:

   ```bash
   cd care
   git clone https://github.com/egovhealthcare/care_publicforms.git
   ```

2. Register it in `plug_config.py`:

   ```python
   public_forms_plug = Plug(
       name="public_forms",
       package_name="/app/care_publicforms",
       version="",  # empty for a local path
       configs={},
   )
   plugs = [public_forms_plug]
   ```

3. Install in editable mode by adding `-e` in `plugs/manager.py`
   (`[sys.executable, "-m", "pip", "install", "-e", *packages]`), then
   `make re-build`, `make up` and `make migrate`.

> [!IMPORTANT]
> Don't commit the `plug_config.py` / `plugs/manager.py` changes to Care.

## Putting a form on a screen

There is nothing to register: open the page for the facility on the TV and
set it as the browser's start page.

- `…/facility/<facility_id>/public_forms/`: patients choose OPD or
  inpatient feedback (opens the form directly if only one is active);
- `…/facility/<facility_id>/public_forms/type/<form code>/form/`, e.g.
  `…/public_forms/type/ipd/form/`: the screen is **pinned to that form**,
  with no chooser. Idle reset and the thank-you page return to that form.

The Django admin shows each form's link (**Public Forms → Feedback
forms**, open a form). A screen can set its own options in the URL:

| Parameter | What it does |
| --- | --- |
| `lang=<code>` | Language each new patient starts in, one of `LANGUAGES`. Default: `DEFAULT_LANGUAGE`. |
| `scan=camera` | The browser reads the QR with the TV's camera (needs HTTPS and a browser with `BarcodeDetector`, e.g. Chrome on Android / ChromeOS / macOS). The scan option is hidden when that can't work: no camera, camera permission denied, or a browser that can't read QR codes; patients then type their UHID or continue as guests. |
| `scan=scanner` | A USB/Bluetooth QR scanner in keyboard mode, which works on any browser. A scanner also works on the first step in camera mode. |
| `scan=off` | Hides the scan option. |
| `keypad=0` / `keypad=1` | On-screen number pad for the UHID. Keep it on for TVs without a system keyboard. |

For example `…/public_forms/type/ipd/form/?lang=en&scan=scanner` pins a
ward screen to the inpatient form, in English, with a USB scanner.

A language the patient picks with the toggle stays with them for their whole
visit, from the chooser to the thank-you page (it travels as `?language=`).
The idle reset and the thank-you page's return switch back to the screen's
starting language for the next patient.

> [!NOTE]
> The pages are served by the Care **backend**. If your deployment serves
> care_fe and the backend from the same domain, route
> `/facility/<id>/public_forms/…` to the backend (for example the regex
> `^/facility/[^/]+/public_forms/`), since care_fe also
> uses `/facility/...` paths.

### Kiosk browser tips

- Chromium kiosk mode: `chromium --kiosk --disable-pinch --overscroll-history-navigation=0 "https://<care-api-host>/facility/<facility_id>/public_forms/type/opd/form/"`.
- The camera only works over HTTPS. Allow camera access for the site once;
  if it is denied, the scan option disappears until access is allowed again.
- Following the NQAS guidance, take exit feedback: put the OPD kiosk near
  the pharmacy counter and the inpatient kiosk where patients are discharged.
- QR payloads count as a UHID when they contain exactly 11 digits once other
  characters are removed (`UHID:123-4567-8901` works).
- Without internet access to Google Fonts, set `LOAD_WEB_FONTS=False` and
  install *Figtree* and each language's `font` (from its locale file) on the
  device (or ship the fonts yourself); otherwise system fonts are used and
  some scripts may not render.

## Forms and questions

In the Django admin under **Public Forms → Feedback forms**:

- **Form**: a code stored with every response and used in the URL (`opd`,
  `ipd`), the patient type (**OP** or **IP**), a title and description per
  language, and active / order. A form with no **facility id** is offered
  everywhere; a facility can have its own form with the same code (say,
  with its own clinic list), which replaces the shared one for that
  facility. Enter the facility's id (the UUID in its Care URL); the admin
  checks it exists and shows the facility's name.
  Switching that facility form off hides the code there; the shared form
  doesn't come back. Keep codes short: reference numbers use the first 12
  characters (`OPD-20261118-4821`).
- **Questions**: one JSON list on the form, in the order they are asked
  (the admin checks it on save and names the question in every error).
  Fields left out take their default:

  ```json
  [
    {"key": "clinic", "type": "choice", "required": true,
     "text": {"en": "Clinic visited", "<code>": "…"},
     "options": [{"value": "ent", "en": "ENT", "<code>": "…"}]},
    {"key": "registration_wait", "type": "rating",
     "text": {"en": "Waiting time at the registration counter"},
     "short_text": {"en": "Registration wait"},
     "options": [{"en": "More than 30 mins"}, {"en": "10-30 mins"}, {"en": "5-10 mins"},
                 {"en": "Within 5 mins"}, {"en": "Immediate"}]},
    {"key": "would_return", "type": "choice", "step": "open", "allow_comment": true,
     "text": {"en": "Would you come back to this hospital for treatment?"},
     "options": [{"value": "yes", "en": "Yes"}, {"value": "no", "en": "No"}]}
  ]
  ```

  Every text is per language: `"en"` (required) and one entry per other
  language code, e.g. `{"en": "Clinic visited", "<code>": "…"}`. Missing
  languages show the English.

  | Field | Default | Meaning |
  | --- | --- | --- |
  | `key` | required | Stable id the answer is stored under: lowercase letters, digits, `_` |
  | `type` | required | `rating`, `choice`, `date` or `text` (see below) |
  | `text` | required | The question per language; English required |
  | `short_text` | `{}` | Shorter label for the review step |
  | `hint` | `{}` | Hint under the question |
  | `options` | `[]` | Choices, or five rating labels (see below) |
  | `required` | `false` | Needs an answer (ratings always do) |
  | `audience` | `"all"` | `all`, `guest` (no UHID) or `identified` (gave a UHID) |
  | `step` | `"details"` | Choices: `details` ("A few details") or `open` ("In your own words", before the review) |
  | `allow_no_comment` | `true` | Ratings: offer "No comments" |
  | `allow_comment` | `false` | Choices: also ask "Why?" under the answer |
  | `active` | `true` | `false` keeps the question in the form without asking it |

  The type decides where a question appears:

  | Type | Step | Notes |
  | --- | --- | --- |
  | `choice` | A few details, or In your own words with `"step": "open"` | `options`: `[{"value": "ent", "en": "ENT", "<code>": "…"}]`. On the open step, a question with 2 or 3 options shows them as large buttons. A **yes/no** question is a choice with the options `yes` and `no` (see `would_return` above) |
  | `date` | A few details | e.g. date of admission; future dates are refused |
  | `rating` | One card at a time | Poor → Excellent plus "No comments" (can be turned off). `options` can relabel the five steps, e.g. waiting time "More than 30 mins" … "Immediate". Ratings always need an answer. |
  | `text` | In your own words | free text |

  The default forms ask age and sex only of guests, since UHID patients
  already have a record. Their details (clinic or ward, date of admission,
  age, sex) are required; a details question that isn't is marked
  *optional* on screen.

Every submission saves each answer **with its question as asked**, so
editing, reordering or removing questions never changes feedback already
given. Statistics group answers by `key`: fixing a typo keeps them together,
while a question with a new meaning should get a new key.
`python manage.py seed_feedback_forms` re-creates either default form if it
was deleted.

## Viewing feedback

Responses go to the `care_publicforms_submission` table, with only these
columns: `external_id`, `reference_number`, `facility_external_id` (not
linked to Care), `form` (the form answered; its code and OP/IP type come from
there), `language`, `uhid` (empty for guests), `answers` and `submitted_at`.
A form that has feedback can't be deleted; switch it off instead.

`answers` holds every answered question under its key, **with the question
as it was asked**:

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

- `value`: ratings `0` to `5` (`0` = *No comments*, left out of averages),
  the choice's code (`"yes"` / `"no"` for a yes/no question), `YYYY-MM-DD`,
  or text as typed.
- `answer` (ratings and choices only): the label the patient picked.
- `comment` (choices that ask "Why?", when given): the reason.
- `question` and `answer` are in English; the patient's language is in the
  `language` column. Questions not answered are left out.

- **Django admin → Feedback submissions**: filter by OP/IP, form and
  language; search by reference number or UHID; each submission shows its
  answers with the questions as they were asked. **Export selected as CSV**
  gives one column per answer key (the `value`; a "Why?" in
  `<key>__comment`). Submissions are read-only there.
- **API** (Care auth; needs permission to view questionnaire responses for
  the facility):
  - `GET /api/public_forms/facility/<facility_id>/responses/`: paginated
    submissions, with the fields above
  - `GET /api/public_forms/facility/<facility_id>/summary/`: one block
    per form with the overall score, attribute-wise averages and
    distributions, the **two lowest-scoring attributes** (the NQAS "Check"
    step) and counts for yes/no and choice questions

  Both accept `patient_type` (`op` | `ip`), `form` (code) and
  `submitted_after` / `submitted_before` (YYYY-MM-DD).
  `GET /api/public_forms/health` returns `OK`.

## Settings

Set in the plug's `configs={}` or as environment variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `LANGUAGES` | `["en", "kn"]` | Language codes in the header toggle, in order (env: `LANGUAGES=en,<code>`). Each needs a locale file (see [Translations](#translations)); the built-in ones are the files in `locale/`. With one language the toggle is hidden. The admin shows a text box for English and each of these. |
| `LOCALE_DIRS` | `[]` | Extra folders of locale files (`<code>.json`), read after the plugin's own: add a language or correct strings without changing the plugin. Restart after editing them. |
| `DEFAULT_LANGUAGE` | `"en"` | Starting language, one of `LANGUAGES` (otherwise the first); a screen can override it with `?lang=`. |
| `SCAN_MODE` | `"camera"` | `camera`, `scanner` or `off`; a screen can override it with `?scan=`. |
| `SHOW_KEYPAD` | `True` | On-screen UHID keypad; a screen can override it with `?keypad=`. |
| `UHID_LENGTH` | `11` | Digits in a UHID. |
| `UHID_GROUPS` | `[3, 4, 4]` | Display grouping (`123 4567 8901`); must add up to `UHID_LENGTH`. |
| `REFERENCE_PREFIX` | `""` | Reference numbers look like `OPD-20261118-4821` / `IPD-…` (unique per facility). Empty uses the form's code. |
| `IDLE_TIMEOUT_SECONDS` | `90` | Idle time before the screen warns, then starts over. |
| `DONE_TIMEOUT_SECONDS` | `20` | How long the thank-you page stays up. |
| `SUBMIT_RATE_LIMIT` | `"60/m"` | Submissions allowed per IP (django-ratelimit rate). A kiosk is one IP, so keep it well above a busy hour. |
| `LOAD_WEB_FONTS` | `True` | Load Figtree (care_fe's font) and each offered language's `font` from Google Fonts. |

### Behind a proxy

The submit limit counts per IP address using django-ratelimit, like Care's
own login limit. Behind a reverse proxy or load balancer every request comes
from the proxy's address, so set Django's `RATELIMIT_IP_META_KEY` in Care's
settings to the header your proxy sets (for example `HTTP_X_REAL_IP`), or
the kiosks share one limit. Set `SUBMIT_RATE_LIMIT` to `""` to turn the
plugin's limit off; Care's `DISABLE_RATELIMIT` turns off all limits.

## Translations

A language is a code (`en`, or any other) with:

- a **locale file**, `<code>.json`: the screen text (buttons, headings,
  messages, default rating labels);
- the **forms' text** under the same code: titles, questions and options.

English is the base: every text needs it, and anything missing in another
language shows in English.

### Locale files

One per language in [`src/public_forms/locale/`](src/public_forms/locale):

```json
{
  "language": {"name": "<name in English>", "toggle": "<name in the language>", "font": "<Google Fonts family, or null>", "tall_script": true},
  "strings": {"back": "…", "next": "…", "…": "…"},
  "ratings": {"5": "…", "4": "…", "3": "…", "2": "…", "1": "…", "0": "…"}
}
```

| Part | Meaning |
| --- | --- |
| `language.name` | For screen readers and the admin's text boxes |
| `language.toggle` | The header button, in the language itself |
| `language.font` | A Google Fonts family for the script, loaded and applied automatically (`null`: Figtree covers it) |
| `language.tall_script` | `true` for scripts with tall letters and no capitals (e.g. most Indian scripts): small labels aren't uppercased, headings get more line height, and the big headline shrinks on narrow screens so long words fit |
| `strings` | The screen text by key, as in `en.json`. Keep placeholders such as `{n}` exactly |
| `ratings` | Default rating labels: 5 (Excellent) → 1 (Poor), and 0 (No comments) |

`manage.py check` reports unreadable files, untranslated strings,
placeholders that differ from English (those strings show in English rather
than break the page), and unknown keys.

### Adding a language

Three steps, in this order; `<code>` is the language's code (e.g. `hi`).

1. **Add the locale file.** Copy `locale/en.json` to `locale/<code>.json`,
   translate `strings` and `ratings`, and fill in `language` (see
   [Locale files](#locale-files)).

2. **Add the language to the questionnaires in the database.** Each form's
   title, description, questions and options hold their text per language,
   so the new code goes next to `"en"`:

   ```json
   {
     "key": "clinic",
     "text": {"en": "Clinic visited", "<code>": "…"},
     "options": [{"value": "ent", "en": "ENT", "<code>": "…"}]
   }
   ```

   A data migration does this for the default forms. In
   [`migrations/`](src/public_forms/migrations), copy the latest
   language migration (the newest file with `LANGUAGE` and `TRANSLATIONS`)
   to the next number, e.g. `0004_<language>_default_forms.py`, then:

   - set `LANGUAGE` to the code;
   - translate each value in `TRANSLATIONS`, which lists every English
     text of the default forms;
   - set `dependencies` to the latest migration.

   Run `manage.py migrate` (`make migrate` in Care) to write the text into
   the forms. It fills in only text that is still the default English and
   has nothing in the language yet, so forms edited in the admin keep their
   edits. It works on new installs and existing ones alike, and
   `seed_feedback_forms` applies it when it re-creates a default form.

3. **Turn it on in the plugin config.** Add the code to `LANGUAGES` in the
   plug's `configs` in Care's `plug_config.py` (or the `LANGUAGES`
   environment variable) and restart. The list replaces the default, so
   include every language to offer:

   ```python
   configs={"LANGUAGES": ["en", "<code>"]},
   ```

   The header then shows the language's button, and the admin shows a text
   box for it on each form's title and description. For forms you created
   or reworded yourself, type the text there, or add `"<code>": "…"` next
   to `"en"` in their questions JSON.

A code in `LANGUAGES` without a locale file is not offered, and
`manage.py check` warns about it.

The tests check that every locale file in the plugin is complete and that
the default forms have every text in each of those languages.

For one deployment only, without changing the plugin, put the locale file in
a folder listed in `LOCALE_DIRS` and translate the forms in the admin. A
`LOCALE_DIRS` file for a built-in language corrects just the strings it
contains.

Have a native speaker check a language before patients use it; drafts are
marked in the code (`# review` in `seed.py`, "Draft" in a language
migration).

## Development

[docs/architecture.md](docs/architecture.md) describes the design, every
table and JSON column, the API responses, and how to add a language or a
question type.

```
src/public_forms/
├── views.py          # the public pages: chooser, questionnaire (GET + one POST), thank you
├── pages.py          # page URLs under /facility/<id>/public_forms/ (chooser, type/<form>/form/, type/<form>/done/)
├── urls.py, api.py   # staff API, mounted by Care at /api/public_forms/
├── questions.py      # the questions JSON: fields, defaults, validation
├── questionnaire.py  # a configured form → steps; answer parsing and labels
├── services.py       # UHID format, collecting answers, saving submissions
├── steps.py          # the steps on the server (without JavaScript); mirrors kiosk.js
├── seed.py           # default OPD / inpatient forms (NQAS format); adding a language to forms
├── migrations/       # schema, the default forms, and one questionnaire migration per added language
├── i18n.py           # loads the locale files; translate(), languages
├── locale/           # screen text, one JSON file per language (<code>.json)
├── checks.py         # `manage.py check` warnings for the language settings
├── models.py, admin.py, settings.py
├── templates/public_forms/   # form.html + steps/, choose, done, empty
├── static/public_forms/      # kiosk.css, kiosk.js, favicon.ico (Care's icon)
└── tests/            # Django tests (pages, API, admin)
e2e/                  # Playwright tests in a real browser
```

### Django tests

Run them from the Care checkout with the plugin installed:

```bash
python manage.py test public_forms --keepdb
```

They run with English and a test language generated from `en.json`, whatever
`plug_config.py` sets, so adding or removing a language doesn't affect them.
Lint with `ruff check src && ruff format src`.

### Browser tests (Playwright)

[`e2e/`](e2e) drives the pages in Chromium against a running Care backend
with the plugin installed: the patient flows (UHID by keypad and by a
keyboard QR scanner, guest details, editing from the review, Reset, Home,
future dates), the scan option hiding when the camera can't be used, the
language carried to the thank-you page, the idle reset
(with a mocked clock), the step-by-step flow without JavaScript, and the layout on five
screen shapes (1080p and 960×540 TVs, a portrait screen, a tablet, a phone:
no sideways scrolling, nothing clipped, main buttons on screen, unique ids,
named controls), in English and in the second offered language.

```bash
cd e2e
npm install
npx playwright install chromium   # once, if Playwright's Chromium isn't installed
PF_FACILITY_ID=<facility external id> npx playwright test
```

- `PF_BASE_URL` is the backend (default `http://localhost:9000`).
- The tests submit feedback, so use a development database.
- They open every page with `?lang=en`, so any `LANGUAGES` works. The
  language tests use the first language offered after English, whichever it
  is, and skip themselves when only English is offered.
- `npx playwright show-report` opens the last run. The layout test saves a
  full-page screenshot of every step per screen shape in
  `e2e/screenshots/`.
