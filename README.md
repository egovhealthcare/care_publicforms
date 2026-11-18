# care_patient_feedback

A [Care](https://github.com/ohcnetwork/care) plugin that runs an **OPD patient
feedback questionnaire on touch-screen TV kiosks**. Every screen is rendered
on the server (Django templates), so it needs no frontend build and works on
the limited browsers built into TVs and signage players, even with JavaScript
switched off.

Flow (bilingual, English / Kannada):

```
start ─┬─ scan QR on OP slip ─┐
       ├─ type UHID ──────────┼─→ 10 rating questions → 4 open questions → review → thank you + reference no.
       └─ guest (clinic, age, sex) ┘
```

Responses are stored in Care's database, linked to the patient (and their
visit) when the UHID matches a patient identifier.

## How it works

- **One URL per screen, plain HTML forms.** Answers in progress live in the
  Django session; every POST redirects (Post/Redirect/Get). Nothing is
  written to the database until the patient taps *Submit feedback*.
- **JavaScript is optional.** `kiosk.js` (ES5, no dependencies) adds an idle
  timer, the instant on-screen keypad, camera QR scanning and a short
  highlight before a rating is submitted. Without it the keypad and ratings
  still work through form posts.
- **Kiosk access is separate from Care logins.** Each kiosk has its own
  secret key. Opening the kiosk link once stores a signed cookie on that
  browser. The key only allows submitting feedback for that kiosk; it is not
  a Care user token. Regenerating the key logs the screen out.
- **care_fe look.** Styled with care_fe's CareUI theme (Figtree, emerald
  primary, neutral greys, care_fe buttons/cards), using hex colours so older
  TV browsers render it.
- **TV layouts.** Sizes are in `rem` and scale to the tighter of the screen's
  width and height: a single column on phones, a centred card on portrait
  TVs (a question screen fits 1080×1920 without scrolling), and a centred
  two-column card on landscape TVs and monitors (every screen fits 16:9,
  16:10 and 4:3, including 960×540 TV browsers).
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
2. Copy the **Kiosk link** shown on the saved kiosk
   (`https://<care-api-host>/facility/<facility_id>/patient_feedback/?key=<secret>`).
   Treat it like a password.
3. Open that link once on the TV. The browser is now authorised and the key
   is removed from the address bar. Bookmark or set as the kiosk start page
   `https://<care-api-host>/facility/<facility_id>/patient_feedback/`.

A facility can have several kiosks (e.g. one per OPD block); each screen
becomes whichever kiosk's key it was opened with.

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
| Patient identifier config | The Care patient identifier that holds the UHID. When set, responses are linked to the patient and to their most recent encounter at the facility. |
| Require registered UHID | Reject UHIDs that don't match a patient (needs the identifier above). |
| Clinics | Clinic list for guests, e.g. `[{"en": "General Medicine", "kn": "ಸಾಮಾನ್ಯ ಔಷಧ"}]`. Empty uses the default list. |

**Last seen** on the kiosk list shows when the screen last loaded a page,
which is handy for spotting a TV that is off or offline.

### Kiosk browser tips

- Chromium kiosk mode: `chromium --kiosk --disable-pinch --overscroll-history-navigation=0 "https://<care-api-host>/facility/<facility_id>/patient_feedback/"`.
- The camera only works over HTTPS. Allow camera access for the site once.
- QR payloads count as a UHID when they contain exactly 11 digits once other
  characters are removed (`UHID:123-4567-8901` works).
- Without internet access to Google Fonts, set `LOAD_WEB_FONTS=False` and
  install *Figtree* and *Noto Sans Kannada* on the device (or ship the fonts
  yourself); otherwise system fonts are used and Kannada may not render.

## Viewing feedback

- **Django admin → Feedback responses**: search by reference number or UHID,
  filter by kiosk, identification method, language and date, and use the
  **Export selected as CSV** action. Responses are read-only there.
- **API** (Care auth; needs permission to view questionnaire responses for
  the facility):
  - `GET /api/patient_feedback/facility/<facility_id>/responses/`: paginated list
  - `GET /api/patient_feedback/facility/<facility_id>/summary/`: totals,
    per-question averages and distributions, "would return" counts

  Both accept `submitted_after`, `submitted_before` (YYYY-MM-DD), `kiosk`
  (kiosk id) and `identification_method` (`scan` | `manual` | `guest`).
  `GET /api/patient_feedback/health` returns `OK`.

Ratings are stored as `{question_key: 0–5}`, where `0` means *No comments*
and is left out of averages.

## Settings

Set in the plug's `configs={}` or as environment variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `UHID_LENGTH` | `11` | Digits in a UHID. |
| `UHID_GROUPS` | `[3, 4, 4]` | Display grouping (`123 4567 8901`); must add up to `UHID_LENGTH`. |
| `REFERENCE_PREFIX` | `"OPD"` | Reference numbers look like `OPD-20261118-4821` (unique per facility). |
| `IDLE_TIMEOUT_SECONDS` | `90` | Idle time before the kiosk warns, then resets. |
| `DONE_TIMEOUT_SECONDS` | `20` | How long the thank-you screen stays up. |
| `DRAFT_EXPIRY_SECONDS` | `600` | Server-side limit for an untouched draft. |
| `ENCOUNTER_LOOKBACK_DAYS` | `1` | How far back to look for the encounter to link. `0` turns linking off. |
| `LOAD_WEB_FONTS` | `True` | Load Figtree (care_fe's font) / Noto Sans Kannada from Google Fonts. |
| `KIOSK_COOKIE_MAX_AGE_DAYS` | `400` | How long a kiosk browser stays authorised. |

## Questions and translations

- Questions, the rating scale and guest choices are in
  [`questionnaire.py`](src/patient_feedback/questionnaire.py). Ratings are
  stored by question key, so never rename a key. Bump
  `QUESTIONNAIRE_VERSION` when wording changes.
- UI strings are in [`i18n.py`](src/patient_feedback/i18n.py). To add a
  language, add it to `LANGUAGES` and add its text next to `en`/`kn` in both
  files. Missing text falls back to English.
- Kannada strings marked `# review` in `i18n.py` were added for the kiosk
  (scanner prompt, keypad, idle warning, error messages). They are not in
  the original design and need a native speaker's check.

## Development

```
src/patient_feedback/
├── views.py          # SSR kiosk screens (one class per screen)
├── pages.py          # kiosk URLs, mounted at /patient_feedback/
├── urls.py, api.py   # staff API, mounted by Care at /api/patient_feedback/
├── draft.py          # in-progress answers in the session
├── services.py       # UHID parsing, patient lookup, saving responses
├── kiosk_auth.py     # kiosk key → signed cookie
├── questionnaire.py  # questions, scale, choices
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
