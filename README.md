# care_patient_feedback

A [Care](https://github.com/ohcnetwork/care) plugin that runs **patient
satisfaction surveys (OPD and inpatient) on touch-screen TV kiosks**. The
pages are rendered on the server (Django templates), so it needs no frontend
build and works on the limited browsers built into TVs and signage players,
even with JavaScript switched off.

The forms and questions are configurable. It ships with the two NQAS patient
satisfaction formats: **OPD feedback** (10 attributes) and **inpatient
feedback** (20 attributes), each with four open questions and the patient
details from the paper form.

Flow (bilingual, English / Kannada):

```
choose form (OP visit / IP stay)        ← skipped on a screen pinned to one form
  → /<form>/ identify: scan QR on OP slip | type UHID | continue as guest
  → a few details (clinic / ward, date of admission, age, sex …)
  → ratings, one card at a time (Poor → Excellent, No comments)
  → open questions → review → thank you + reference number
```

The pages are **public**: anyone in the hospital can open them, with no
login, kiosk key, session or cookie. Each response is one row in a table
**without foreign keys**.

## How it works

- **One page per form, posted once.** The whole questionnaire (identify,
  details, every rating, open questions, review) is one server-rendered form
  with every language in it. `kiosk.js` shows one step at a time and
  switches language instantly; the form controls are the only state. Nothing
  reaches the server until the patient taps *Submit feedback*, which posts
  the page once. The server validates it and either saves it and shows the
  thank-you page, or shows the page again at the first step with a problem.
- **JavaScript is optional.** Without it the same page is one long form
  (UHID, details, every rating, open questions, submit). `kiosk.js` (ES5, no
  dependencies) adds the steps, the UHID cells and on-screen keypad, QR
  scanning and the idle timer.
- **Nothing stored until submit.** No session, cookie or draft rows; the
  UHID is stored as entered and is not looked up in Care. Submissions are
  rate-limited per IP (`SUBMIT_RATE_LIMIT`; Care's `DISABLE_RATELIMIT`
  turns it off).
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
- **Unattended use.** Once someone has used the screen, 90 s without a
  touch shows *"Are you still there?"*, then reloads the start page, which
  drops everything entered.

## Installation

### Production

Add the plug to [`plug_config.py`](https://github.com/ohcnetwork/care/blob/develop/plug_config.py) in Care:

```python
patient_feedback_plug = Plug(
    name="patient_feedback",
    package_name="git+https://github.com/ohcnetwork/care_patient_feedback.git",
    version="@main",
    configs={},  # see Settings below
)
plugs = [patient_feedback_plug]
```

Then rebuild the image and run migrations. Care's start scripts run
`collectstatic`, which picks up the plugin's CSS and JS.

### Local development (Care in Docker)

1. Put the plugin inside the Care checkout so it is mounted into the
   container at `/app/care_patient_feedback`:

   ```bash
   cd care
   git clone <this repo> care_patient_feedback
   ```

2. Register it in `plug_config.py`:

   ```python
   patient_feedback_plug = Plug(
       name="patient_feedback",
       package_name="/app/care_patient_feedback",
       version="",  # empty for a local path
       configs={},
   )
   plugs = [patient_feedback_plug]
   ```

3. Install in editable mode by adding `-e` in `plugs/manager.py`
   (`[sys.executable, "-m", "pip", "install", "-e", *packages]`), then
   `make re-build`, `make up` and `make migrate`.

> [!IMPORTANT]
> Don't commit the `plug_config.py` / `plugs/manager.py` changes to Care.

## Putting a form on a screen

There is nothing to register: open the page for the facility on the TV and
set it as the browser's start page.

- `…/facility/<facility_id>/patient_feedback/`: patients choose OPD or
  inpatient feedback (opens the form directly if only one is active);
- `…/facility/<facility_id>/patient_feedback/<form code>/`, e.g. `…/ipd/`:
  the screen is **pinned to that form**, with no chooser. Idle reset and
  the thank-you page return to that form.

The Django admin shows each form's link (**Patient Feedback → Feedback
forms**, open a form). A screen can set its own options in the URL:

| Parameter | What it does |
| --- | --- |
| `lang=kn` | Language each new patient starts in (`en` / `kn`). Default: `DEFAULT_LANGUAGE`. |
| `scan=camera` | The browser reads the QR with the TV's camera (needs HTTPS and a browser with `BarcodeDetector`, e.g. Chrome on Android / ChromeOS / macOS). |
| `scan=scanner` | A USB/Bluetooth QR scanner in keyboard mode, which works on any browser. A scanner also works on the first step in camera mode. |
| `scan=off` | Hides the scan option. |
| `keypad=0` / `keypad=1` | On-screen number pad for the UHID. Keep it on for TVs without a system keyboard. |

For example `…/patient_feedback/ipd/?lang=kn&scan=scanner` pins a ward
screen to the inpatient form, in Kannada, with a USB scanner.

> [!NOTE]
> The pages are served by the Care **backend**. If your deployment serves
> care_fe and the backend from the same domain, route
> `/facility/<id>/patient_feedback/` to the backend, since care_fe also uses
> `/facility/...` paths.

### Kiosk browser tips

- Chromium kiosk mode: `chromium --kiosk --disable-pinch --overscroll-history-navigation=0 "https://<care-api-host>/facility/<facility_id>/patient_feedback/opd/"`.
- The camera only works over HTTPS. Allow camera access for the site once.
- Following the NQAS guidance, take exit feedback: put the OPD kiosk near
  the pharmacy counter and the inpatient kiosk where patients are discharged.
- QR payloads count as a UHID when they contain exactly 11 digits once other
  characters are removed (`UHID:123-4567-8901` works).
- Without internet access to Google Fonts, set `LOAD_WEB_FONTS=False` and
  install *Figtree* and *Noto Sans Kannada* on the device (or ship the fonts
  yourself); otherwise system fonts are used and Kannada may not render.

## Forms and questions

In the Django admin under **Patient Feedback → Feedback forms**:

- **Form**: a code stored with every response and used in the URL (`opd`,
  `ipd`), the patient type (**OP** or **IP**), a title and description per
  language, and active / order. A form with no facility is offered
  everywhere; a facility can add its own form with the same code (say, with
  its own clinic list), which replaces the shared one for that facility.
- **Questions** (inline on the form, or under *Feedback questions* for every
  option). The type decides where a question appears:

  | Type | Step | Notes |
  | --- | --- | --- |
  | `choice` | A few details | `options`: `[{"value": "ent", "en": "ENT", "kn": "..."}]` |
  | `date` | A few details | e.g. date of admission; future dates are refused |
  | `rating` | One card at a time | Poor → Excellent plus "No comments" (can be turned off). `options` can relabel the five steps, e.g. waiting time "More than 30 mins" … "Immediate". Ratings always need an answer. |
  | `yes_no` | In your own words | `allow_comment` adds a "Why?" box |
  | `text` | In your own words | free text |

  Each question has a stable `key` (answers are stored under it), an order,
  `required`, active, and an **audience**: everyone, guests only, or
  patients who gave a UHID. The default forms ask age and sex only of
  guests, since UHID patients already have a record.

Responses store only keys and values; the wording and labels come from the
form. Fixing a typo is fine, but if a question's meaning changes, add a new
question with a new key and switch the old one off, so earlier answers
aren't read against the new wording. `python manage.py seed_feedback_forms`
re-creates either default form if it was deleted.

## Viewing feedback

Responses go to `FeedbackSubmission` (`patient_feedback_feedbacksubmission`),
which has **no foreign keys** and only these columns: `external_id`,
`reference_number`, `facility_external_id`, `form_code`, `patient_type`,
`language`, `uhid` (empty for guests), `answers` and `submitted_at`.

`answers` is a flat `{question_key: value}` object, for example:

```json
{"clinic": "ent", "information_signage": 4, "registration_wait": 0,
 "would_return": true, "would_return__comment": "Friendly staff"}
```

Ratings are `0`–`5` (`0` = *No comments*, left out of averages), choices
their option value, dates `YYYY-MM-DD`, yes/no `true`/`false` (the "Why?"
text under `<key>__comment`) and free text as typed. Unanswered questions
are left out.

- **Django admin → Feedback submissions**: filter by OP/IP, form and
  language; search by reference number or UHID; each submission shows its
  answers with the form's wording. **Export selected as CSV** gives one
  column per answer key. Submissions are read-only there.
- **API** (Care auth; needs permission to view questionnaire responses for
  the facility):
  - `GET /api/patient_feedback/facility/<facility_id>/responses/`: paginated
    submissions, with the fields above
  - `GET /api/patient_feedback/facility/<facility_id>/summary/`: one block
    per form with the overall score, attribute-wise averages and
    distributions, the **two lowest-scoring attributes** (the NQAS "Check"
    step) and counts for yes/no and choice questions

  Both accept `patient_type` (`op` | `ip`), `form` (code) and
  `submitted_after` / `submitted_before` (YYYY-MM-DD).
  `GET /api/patient_feedback/health` returns `OK`.

## Settings

Set in the plug's `configs={}` or as environment variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `DEFAULT_LANGUAGE` | `"en"` | Starting language; a screen can override it with `?lang=`. |
| `SCAN_MODE` | `"camera"` | `camera`, `scanner` or `off`; a screen can override it with `?scan=`. |
| `SHOW_KEYPAD` | `True` | On-screen UHID keypad; a screen can override it with `?keypad=`. |
| `UHID_LENGTH` | `11` | Digits in a UHID. |
| `UHID_GROUPS` | `[3, 4, 4]` | Display grouping (`123 4567 8901`); must add up to `UHID_LENGTH`. |
| `REFERENCE_PREFIX` | `""` | Reference numbers look like `OPD-20261118-4821` / `IPD-…` (unique per facility). Empty uses the form's code. |
| `IDLE_TIMEOUT_SECONDS` | `90` | Idle time before the screen warns, then starts over. |
| `DONE_TIMEOUT_SECONDS` | `20` | How long the thank-you page stays up. |
| `SUBMIT_RATE_LIMIT` | `"60/m"` | Submissions allowed per IP (django-ratelimit rate). A kiosk is one IP, so keep it well above a busy hour. |
| `LOAD_WEB_FONTS` | `True` | Load Figtree (care_fe's font) / Noto Sans Kannada from Google Fonts. |

## Translations

- Question text is edited per language in the admin. Screen text (buttons,
  headings) is in [`i18n.py`](src/patient_feedback/i18n.py). To add a
  language, add it to `LANGUAGES` there; the admin then shows a box for it
  on every question. Missing text falls back to English.
- **Needs a native speaker's check:** Kannada marked `# review` in
  `i18n.py` and [`seed.py`](src/patient_feedback/seed.py). That covers most
  of the inpatient form, the waiting-time labels, the form titles, and the
  kiosk-specific messages (scanner, keypad, idle warning, errors). The OPD
  questions use the Kannada from the original design.

## Development

```
src/patient_feedback/
├── views.py          # the public pages: chooser, questionnaire (GET + one POST), thank you
├── pages.py          # page URLs, mounted at /facility/<id>/patient_feedback/
├── urls.py, api.py   # staff API, mounted by Care at /api/patient_feedback/
├── questionnaire.py  # a configured form → steps; answer parsing and labels
├── services.py       # UHID format, collecting answers, saving submissions
├── seed.py           # default OPD / inpatient forms (NQAS format)
├── i18n.py           # UI strings
├── models.py, admin.py, settings.py
├── templates/patient_feedback/   # form.html + steps/, choose, done, empty
├── static/patient_feedback/      # kiosk.css, kiosk.js
└── tests/
```

Run the tests from the Care checkout with the plugin installed:

```bash
python manage.py test patient_feedback --keepdb
```

Lint with `ruff check src && ruff format src`.
