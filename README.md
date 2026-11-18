# care_patient_feedback

A [Care](https://github.com/ohcnetwork/care) plugin that runs **patient
satisfaction surveys (OPD and inpatient) on touch-screen TV kiosks**. Every
screen is rendered on the server (Django templates), so it needs no frontend
build and works on the limited browsers built into TVs and signage players,
even with JavaScript switched off.

The forms and questions are configurable. It ships with the two NQAS patient
satisfaction formats: **OPD feedback** (10 attributes) and **inpatient
feedback** (20 attributes), each with four open questions and the patient
details from the paper form.

Flow (bilingual, English / Kannada):

```
choose form (OP visit / IP stay)        ← skipped on a kiosk pinned to one form
  → /<form>/ identify: scan QR on OP slip | type UHID | continue as guest
  → a few details (clinic / ward, date of admission, age, sex …)
  → ratings: all on one page, one card at a time (Poor → Excellent, No comments)
  → open questions → review → thank you + reference number
```

Each response is stored as one row in a table **without foreign keys**,
holding a snapshot of every question as it was asked.

## How it works

- **Server-rendered pages, plain HTML forms.** Answers in progress live in
  the Django session; every POST redirects (Post/Redirect/Get). Nothing is
  written to the database until the patient taps *Submit feedback*.
- **All ratings on one page.** The server renders every rating question on
  a single page with only the current card visible. With JavaScript, a tap
  highlights the answer, saves it in the background and slides to the next
  card without reloading; the last answer submits the page. Without
  JavaScript, each answer button posts and the server shows the next card.
- **JavaScript is optional.** `kiosk.js` (ES5, no dependencies) adds the
  in-page question stepping, an idle timer, the instant on-screen keypad and
  camera QR scanning. Everything also works through plain form posts.
- **Configurable forms.** Forms and questions live in the database and are
  edited in the Django admin, with a text box per language. See
  [Forms and questions](#forms-and-questions).
- **Kiosk access is separate from Care logins.** Each kiosk has its own
  secret key. Opening the kiosk link once stores a signed cookie on that
  browser. The key only allows submitting feedback for that kiosk; it is not
  a Care user token. Regenerating the key logs the screen out.
- **care_fe look.** Styled with care_fe's CareUI theme (Figtree, emerald
  primary, neutral greys, care_fe buttons/cards), using hex colours so older
  TV browsers render it.
- **One layout on every screen.** The original single-column kiosk design
  is used everywhere. Sizes are in `rem`, so on TVs the column simply scales
  up to the screen (the smaller of height/60 and width/32). A question fits
  without scrolling on 1920×1080, 960×540 TV browsers, 1080×1920 portrait
  and tablets. The longer comments and review pages scroll, with their main
  button pinned at the bottom.
- **Unattended use.** After 90 s without a touch the kiosk shows *"Are you
  still there?"*, then wipes the answers and returns to the start in the
  kiosk's default language. The server also discards drafts untouched for
  10 minutes, so one patient's answers never carry over to the next.

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

## Setting up a kiosk

1. In Care's Django admin, open **Patient Feedback → Feedback kiosks → Add**.
   Pick the facility, give it a name ("OPD block, ground floor") and save.
2. Copy one of the **Kiosk links** shown on the saved kiosk. Treat them like
   passwords:
   - `…/facility/<facility_id>/patient_feedback/?key=<secret>`: patients
     choose OPD or inpatient feedback;
   - `…/facility/<facility_id>/patient_feedback/<form code>/?key=<secret>`,
     e.g. `…/ipd/?key=…`: the screen is **pinned to that form**, with no
     chooser.
3. Open that link once on the TV. The browser is now authorised and the key
   is removed from the address bar (the form part stays). Set the clean URL
   as the kiosk's start page, e.g.
   `https://<care-api-host>/facility/<facility_id>/patient_feedback/ipd/`.

Every step of a form lives under its code (`/ipd/`, `/ipd/questions/` …).
A screen launched on a form's URL stays on that form: there is no way back
to the chooser, and idle reset and "Submit another response" return to that
form. Launched on the plain URL, the screen returns to the chooser. A kiosk
whose **Forms** list has a single form behaves as pinned too.

A facility can have several kiosks (e.g. one per OPD block, one per ward);
each screen becomes whichever kiosk's key it was opened with.

> [!NOTE]
> The kiosk pages are served by the Care **backend**. If your deployment
> serves care_fe and the backend from the same domain, route
> `/facility/<id>/patient_feedback/` to the backend, since care_fe also uses
> `/facility/...` paths.

Per-kiosk options:

| Field | What it does |
| --- | --- |
| Default language | Language each new patient starts in (`en` / `kn`). |
| Scan mode | `camera`: the browser reads the QR with the TV's camera (needs HTTPS and a browser with `BarcodeDetector`, e.g. Chrome on Android / ChromeOS / macOS). `scanner`: a USB/Bluetooth QR scanner in keyboard mode, which works on any browser. `disabled`: hides the scan option. |
| Show keypad | On-screen number pad for the UHID. Keep it on for TVs without a system keyboard. |
| Forms | Forms offered on this screen, e.g. only the inpatient form on a ward kiosk. Empty offers every active form for the facility. |
| Patient identifier config | The Care patient identifier that holds the UHID. When set, responses record the patient's id and their most recent encounter's id at the facility. |
| Require registered UHID | Reject UHIDs that don't match a patient (needs the identifier above). |

**Last seen** on the kiosk list shows when the screen last loaded a page,
which is handy for spotting a TV that is off or offline.

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

- **Form**: a code stored with every response and used in the kiosk URL
  (`opd`, `ipd`; `done`, `reset` and `language` are reserved), the patient
  type (**OP** or **IP**), a title and description per language, and active
  / order. A form with no facility is offered everywhere; a facility can add
  its own form with the same code (say, with its own clinic list), which
  replaces the shared one on that facility's kiosks.
- **Questions** (inline on the form, or under *Feedback questions* for every
  option). The type decides where a question appears:

  | Type | Screen | Notes |
  | --- | --- | --- |
  | `choice` | A few details | `options`: `[{"value": "ent", "en": "ENT", "kn": "..."}]` |
  | `date` | A few details | e.g. date of admission; future dates are refused |
  | `rating` | Ratings page, one card at a time | Poor → Excellent plus "No comments" (can be turned off). `options` can relabel the five steps, e.g. waiting time "More than 30 mins" … "Immediate". Ratings always need an answer. |
  | `yes_no` | In your own words | `allow_comment` adds a "Why?" box |
  | `text` | In your own words | free text |

  Each question has a stable `key` (stored with answers, so don't rename it
  once answers exist), an order, `required`, active, and an **audience**:
  everyone, guests only, or patients who gave a UHID. The default forms ask
  age and sex only of guests, since UHID patients already have a record.

To change wording, edit the question; stored responses keep the wording they
were answered with. `python manage.py seed_feedback_forms` re-creates either
default form if it was deleted.

## Viewing feedback

Responses go to `FeedbackSubmission` (`patient_feedback_feedbacksubmission`),
which has **no foreign keys**. Facility, kiosk, form, patient and encounter
are kept as plain ids plus names, and `answers` holds every question's
English wording, value and display text as answered. Ratings are also kept
as `{question_key: 0–5}`, where `0` means *No comments* and is left out of
averages.

- **Django admin → Feedback submissions**: filter by OP/IP, form, how the
  patient identified and language; search by reference number, UHID or
  facility; **Export selected as CSV** gives one column per question.
  Submissions are read-only there.
- **API** (Care auth; needs permission to view questionnaire responses for
  the facility):
  - `GET /api/patient_feedback/facility/<facility_id>/responses/`: paginated
    submissions with their answers
  - `GET /api/patient_feedback/facility/<facility_id>/summary/`: one block
    per form with the overall score, attribute-wise averages and
    distributions, the **two lowest-scoring attributes** (the NQAS "Check"
    step) and counts for yes/no and choice questions

  Both accept `patient_type` (`op` | `ip`), `form` (code),
  `submitted_after` / `submitted_before` (YYYY-MM-DD), `kiosk` (kiosk id)
  and `identification_method` (`scan` | `manual` | `guest`).
  `GET /api/patient_feedback/health` returns `OK`.

## Settings

Set in the plug's `configs={}` or as environment variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `UHID_LENGTH` | `11` | Digits in a UHID. |
| `UHID_GROUPS` | `[3, 4, 4]` | Display grouping (`123 4567 8901`); must add up to `UHID_LENGTH`. |
| `REFERENCE_PREFIX` | `""` | Reference numbers look like `OPD-20261118-4821` / `IPD-…` (unique per facility). Empty uses the form's code. |
| `IDLE_TIMEOUT_SECONDS` | `90` | Idle time before the kiosk warns, then resets. |
| `DONE_TIMEOUT_SECONDS` | `20` | How long the thank-you screen stays up. |
| `DRAFT_EXPIRY_SECONDS` | `600` | Server-side limit for an untouched draft. |
| `ENCOUNTER_LOOKBACK_DAYS` | `1` | OP forms: how far back to look for the patient's encounter to record. `0` turns it off. |
| `IP_ENCOUNTER_LOOKBACK_DAYS` | `60` | Same for IP forms (filled at discharge); inpatient encounters are preferred. |
| `LOAD_WEB_FONTS` | `True` | Load Figtree (care_fe's font) / Noto Sans Kannada from Google Fonts. |
| `KIOSK_COOKIE_MAX_AGE_DAYS` | `400` | How long a kiosk browser stays authorised. |

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
├── views.py          # SSR kiosk screens (one class per screen; ratings share one page)
├── pages.py          # kiosk URLs, mounted at /facility/<id>/patient_feedback/
├── urls.py, api.py   # staff API, mounted by Care at /api/patient_feedback/
├── draft.py          # in-progress answers in the session
├── questionnaire.py  # a configured form → screens; answer parsing and labels
├── seed.py           # default OPD / inpatient forms (NQAS format)
├── services.py       # UHID parsing, patient lookup, saving submissions
├── kiosk_auth.py     # kiosk key → signed cookie
├── i18n.py           # UI strings
├── models.py, admin.py, settings.py
├── templates/patient_feedback/   # one template per screen
├── static/patient_feedback/      # kiosk.css, kiosk.js
└── tests/
```

Run the tests from the Care checkout with the plugin installed:

```bash
python manage.py test patient_feedback --keepdb
```

Lint with `ruff check src && ruff format src`.
