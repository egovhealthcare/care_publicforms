"""
UI strings for the kiosk, keyed by language code.

Only one language is rendered per request (the server picks it), so adding a
language is a matter of adding it to ``LANGUAGES`` and filling in its strings
here and in ``questionnaire.py``. Missing strings fall back to English.

Strings marked ``# review`` were added for the kiosk build (they are not in
the original design file) and need a native-speaker check.
"""

DEFAULT_LANGUAGE = "en"

# Order defines the order of the language toggle in the header.
LANGUAGES = {
    "en": {"toggle": "EN", "name": "English"},
    "kn": {"toggle": "ಕನ್ನಡ", "name": "Kannada"},
}

LANGUAGE_CHOICES = [(code, meta["name"]) for code, meta in LANGUAGES.items()]

STRINGS = {
    # ── Chrome ──────────────────────────────────────────────────────
    "kicker": {"en": "OPD Feedback", "kn": "OPD Feedback"},
    "nav_home": {"en": "Home", "kn": "ಮುಖಪುಟ"},
    "nav_reset": {"en": "Reset", "kn": "ಮರುಹೊಂದಿಸಿ"},
    "change": {"en": "Change", "kn": "ಬದಲಿಸಿ"},
    "back": {"en": "Back", "kn": "ಹಿಂದೆ"},
    "next": {"en": "Next", "kn": "ಮುಂದೆ"},
    "footer_note": {
        "en": "Confidential · Used only to improve services",
        "kn": "ಗೌಪ್ಯ · ಸೇವೆ ಸುಧಾರಿಸಲು ಮಾತ್ರ ಬಳಕೆ",
    },
    # ── Identify ────────────────────────────────────────────────────
    "hero_title": {"en": "Tell us about your visit today.", "kn": "ಇಂದಿನ ನಿಮ್ಮ ಭೇಟಿಯ ಬಗ್ಗೆ ತಿಳಿಸಿ."},
    "hero_lead": {
        "en": "Ten short questions, about two minutes. Your answers stay confidential "
        "and are used only to improve our services.",
        "kn": "ಹತ್ತು ಸಣ್ಣ ಪ್ರಶ್ನೆಗಳು, ಸುಮಾರು ಎರಡು ನಿಮಿಷ. ನಿಮ್ಮ ಉತ್ತರಗಳು ಗೌಪ್ಯವಾಗಿರುತ್ತವೆ ಮತ್ತು ಸೇವೆ ಸುಧಾರಿಸಲು ಮಾತ್ರ ಬಳಸಲಾಗುತ್ತದೆ.",
    },
    "step_identify": {"en": "Step 1 — Identify yourself", "kn": "ಹಂತ 1 — ನಿಮ್ಮನ್ನು ಗುರುತಿಸಿ"},
    "opt_scan_title": {"en": "Scan the QR on your OP slip", "kn": "ನಿಮ್ಮ ಒಪಿ ಚೀಟಿಯ QR ಸ್ಕ್ಯಾನ್ ಮಾಡಿ"},
    "opt_scan_sub": {"en": "Fastest — nothing to type", "kn": "ಅತಿ ವೇಗ — ಟೈಪ್ ಮಾಡಬೇಕಿಲ್ಲ"},
    "opt_manual_title": {"en": "Enter UHID manually", "kn": "UHID ಕೈಯಿಂದ ನಮೂದಿಸಿ"},
    "opt_manual_sub": {"en": "Printed at the top of your slip", "kn": "ಚೀಟಿಯ ಮೇಲ್ಭಾಗದಲ್ಲಿ ಮುದ್ರಿತವಾಗಿದೆ"},
    "or": {"en": "or", "kn": "ಅಥವಾ"},
    "opt_guest_title": {"en": "Continue as guest", "kn": "ಅತಿಥಿಯಾಗಿ ಮುಂದುವರಿಯಿರಿ"},
    "opt_guest_sub": {"en": "No UHID needed. Stays anonymous.", "kn": "UHID ಬೇಕಿಲ್ಲ. ಅನಾಮಧೇಯವಾಗಿರುತ್ತದೆ."},
    # ── Scan ────────────────────────────────────────────────────────
    "scan_heading": {"en": "Point at the QR code", "kn": "QR ಕೋಡ್‌ನ ಕಡೆಗೆ ಹಿಡಿಯಿರಿ"},
    "scan_camera_unavailable": {
        "en": "The camera isn't available on this device or permission was declined. "
        "You can enter your UHID instead, or continue as a guest.",
        "kn": "ಈ ಸಾಧನದಲ್ಲಿ ಕ್ಯಾಮೆರಾ ಲಭ್ಯವಿಲ್ಲ ಅಥವಾ ಅನುಮತಿ ನಿರಾಕರಿಸಲಾಗಿದೆ. ಬದಲಿಗೆ UHID ನಮೂದಿಸಿ ಅಥವಾ ಅತಿಥಿಯಾಗಿ ಮುಂದುವರಿಯಿರಿ.",
    },
    "scanner_heading": {  # review
        "en": "Hold your QR code under the scanner",
        "kn": "QR ಕೋಡ್ ಅನ್ನು ಸ್ಕ್ಯಾನರ್ ಕೆಳಗೆ ಹಿಡಿಯಿರಿ",
    },
    "scanner_lead": {  # review
        "en": "Hold the QR code on your OP slip under the scanner light. It reads automatically.",
        "kn": "ನಿಮ್ಮ ಒಪಿ ಚೀಟಿಯ QR ಕೋಡ್ ಅನ್ನು ಸ್ಕ್ಯಾನರ್ ಬೆಳಕಿನ ಕೆಳಗೆ ಹಿಡಿಯಿರಿ. ಅದು ತಾನಾಗಿಯೇ ಓದುತ್ತದೆ.",
    },
    "scan_unreadable": {  # review
        "en": "We couldn't read a UHID from that code. Try again or enter it manually.",
        "kn": "ಆ ಕೋಡ್‌ನಿಂದ UHID ಓದಲಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ ಅಥವಾ ಕೈಯಿಂದ ನಮೂದಿಸಿ.",
    },
    "scan_to_manual": {"en": "Enter UHID instead", "kn": "ಬದಲಿಗೆ UHID ನಮೂದಿಸಿ"},
    # ── Manual UHID ─────────────────────────────────────────────────
    "uhid_heading": {"en": "Your UHID", "kn": "ನಿಮ್ಮ UHID"},
    "uhid_lead": {
        "en": "The {n}-digit number printed on your OP slip or hospital card.",
        "kn": "ನಿಮ್ಮ ಒಪಿ ಚೀಟಿ ಅಥವಾ ಆಸ್ಪತ್ರೆ ಕಾರ್ಡ್‌ನಲ್ಲಿ ಮುದ್ರಿತವಾದ {n} ಅಂಕಿಗಳ ಸಂಖ್ಯೆ.",
    },
    "uhid_label": {"en": "UHID, {n} digits", "kn": "UHID, {n} ಅಂಕಿಗಳು"},
    "uhid_error_length": {
        "en": "Enter all {n} digits of your UHID.",
        "kn": "ನಿಮ್ಮ UHID ನ ಎಲ್ಲಾ {n} ಅಂಕಿಗಳನ್ನು ನಮೂದಿಸಿ.",
    },
    "uhid_error_not_found": {  # review
        "en": "We couldn't find a patient with this UHID. Check the number, or continue as a guest.",
        "kn": "ಈ UHID ಹೊಂದಿರುವ ರೋಗಿ ಕಂಡುಬಂದಿಲ್ಲ. ಸಂಖ್ಯೆಯನ್ನು ಪರಿಶೀಲಿಸಿ ಅಥವಾ ಅತಿಥಿಯಾಗಿ ಮುಂದುವರಿಯಿರಿ.",
    },
    "continue": {"en": "Continue", "kn": "ಮುಂದುವರಿಯಿರಿ"},
    "no_uhid": {
        "en": "I don't have a UHID — continue as guest",
        "kn": "ನನಗೆ UHID ಇಲ್ಲ — ಅತಿಥಿಯಾಗಿ ಮುಂದುವರಿಯಿರಿ",
    },
    "keypad_clear": {"en": "Clear", "kn": "ತೆರವುಗೊಳಿಸಿ"},  # review
    "keypad_delete": {"en": "Delete last digit", "kn": "ಕೊನೆಯ ಅಂಕಿ ಅಳಿಸಿ"},  # review
    # ── Guest ───────────────────────────────────────────────────────
    "guest_heading": {"en": "Three quick details", "kn": "ಮೂರು ಸಣ್ಣ ವಿವರಗಳು"},
    "guest_lead": {
        "en": "No name, no number. This only helps us group feedback by department.",
        "kn": "ಹೆಸರು ಇಲ್ಲ, ಸಂಖ್ಯೆ ಇಲ್ಲ. ವಿಭಾಗವಾರು ಪ್ರತಿಕ್ರಿಯೆ ವರ್ಗೀಕರಿಸಲು ಮಾತ್ರ ಇದು ಸಹಾಯ ಮಾಡುತ್ತದೆ.",
    },
    "guest_clinic": {"en": "Clinic visited", "kn": "ಭೇಟಿ ನೀಡಿದ ಚಿಕಿತ್ಸಾಲಯ"},
    "guest_age": {"en": "Age group", "kn": "ವಯೋಮಾನ"},
    "guest_sex": {"en": "Sex", "kn": "ಲಿಂಗ"},
    "guest_start": {"en": "Start the questions", "kn": "ಪ್ರಶ್ನೆಗಳನ್ನು ಪ್ರಾರಂಭಿಸಿ"},
    # ── Rating ──────────────────────────────────────────────────────
    "question_counter": {"en": "Question {n} of {total}", "kn": "ಪ್ರಶ್ನೆ {n} / {total}"},
    # ── Open-ended ──────────────────────────────────────────────────
    "open_kicker": {"en": "In your own words", "kn": "ನಿಮ್ಮ ಮಾತಿನಲ್ಲಿ"},
    "open_heading": {"en": "Last four — all optional.", "kn": "ಕೊನೆಯ ನಾಲ್ಕು — ಎಲ್ಲವೂ ಐಚ್ಛಿಕ."},
    "open_would_return": {
        "en": "Would you come back to this hospital for treatment?",
        "kn": "ಚಿಕಿತ್ಸೆಗಾಗಿ ನೀವು ಈ ಆಸ್ಪತ್ರೆಗೆ ಮತ್ತೆ ಬರುತ್ತೀರಾ?",
    },
    "open_why": {"en": "Why? (optional)", "kn": "ಏಕೆ? (ಐಚ್ಛಿಕ)"},
    "open_improve": {
        "en": "What would you most like to see improved?",
        "kn": "ಯಾವುದನ್ನು ಸುಧಾರಿಸಬೇಕೆಂದು ನೀವು ಬಯಸುತ್ತೀರಿ?",
    },
    "open_chose": {"en": "What made you choose this hospital?", "kn": "ಈ ಆಸ್ಪತ್ರೆಯನ್ನು ಆಯ್ಕೆ ಮಾಡಲು ಕಾರಣವೇನು?"},
    "open_suggest": {"en": "Any other suggestions?", "kn": "ಇನ್ನಾವುದೇ ಸಲಹೆಗಳಿವೆಯೇ?"},
    "yes": {"en": "Yes", "kn": "ಹೌದು"},
    "no": {"en": "No", "kn": "ಇಲ್ಲ"},
    "review_answers": {"en": "Review answers", "kn": "ಉತ್ತರ ಪರಿಶೀಲಿಸಿ"},
    # ── Review ──────────────────────────────────────────────────────
    "review_heading": {"en": "Before you send", "kn": "ಕಳುಹಿಸುವ ಮೊದಲು"},
    "review_lead": {"en": "Tap any line to change it.", "kn": "ಬದಲಾಯಿಸಲು ಯಾವುದೇ ಸಾಲನ್ನು ಒತ್ತಿ."},
    "review_would_return": {"en": "Would return to this hospital", "kn": "ಈ ಆಸ್ಪತ್ರೆಗೆ ಮತ್ತೆ ಬರುತ್ತೇನೆ"},
    "not_answered": {"en": "Not answered", "kn": "ಉತ್ತರಿಸಿಲ್ಲ"},
    "review_note": {
        "en": "Your feedback is stored without your name attached to the ratings. "
        "It is reviewed monthly by the hospital's quality team.",
        "kn": "ನಿಮ್ಮ ಪ್ರತಿಕ್ರಿಯೆಯನ್ನು ಹೆಸರಿಲ್ಲದೆ ಸಂಗ್ರಹಿಸಲಾಗುತ್ತದೆ. ಆಸ್ಪತ್ರೆಯ ಗುಣಮಟ್ಟ ತಂಡ ಪ್ರತಿ ತಿಂಗಳು ಇದನ್ನು ಪರಿಶೀಲಿಸುತ್ತದೆ.",
    },
    "submit": {"en": "Submit feedback", "kn": "ಪ್ರತಿಕ್ರಿಯೆ ಸಲ್ಲಿಸಿ"},
    # ── Done ────────────────────────────────────────────────────────
    "done_title": {"en": "Thank you.", "kn": "ಧನ್ಯವಾದಗಳು."},
    "done_lead": {
        "en": "Your feedback has been recorded. Keep this reference number if you need "
        "to follow up at the May I Help You desk.",
        "kn": "ನಿಮ್ಮ ಪ್ರತಿಕ್ರಿಯೆ ದಾಖಲಾಗಿದೆ. ಮುಂದೆ ವಿಚಾರಿಸಬೇಕಾದರೆ ಈ ಉಲ್ಲೇಖ ಸಂಖ್ಯೆಯನ್ನು ಇಟ್ಟುಕೊಳ್ಳಿ.",
    },
    "reference_number": {"en": "Reference number", "kn": "ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ"},
    "restart": {"en": "Submit another response", "kn": "ಇನ್ನೊಂದು ಪ್ರತಿಕ್ರಿಯೆ ಸಲ್ಲಿಸಿ"},
    # ── Idle warning ────────────────────────────────────────────────
    "idle_title": {"en": "Are you still there?", "kn": "ನೀವು ಇನ್ನೂ ಇದ್ದೀರಾ?"},  # review
    "idle_body": {  # review
        "en": "Tap anywhere to continue. Starting over in {n} seconds.",
        "kn": "ಮುಂದುವರಿಯಲು ಎಲ್ಲಿಯಾದರೂ ಒತ್ತಿ. {n} ಸೆಕೆಂಡುಗಳಲ್ಲಿ ಮತ್ತೆ ಪ್ರಾರಂಭವಾಗುತ್ತದೆ.",
    },
}


def normalize_language(code: str | None, default: str = DEFAULT_LANGUAGE) -> str:
    if code in LANGUAGES:
        return code
    return default if default in LANGUAGES else DEFAULT_LANGUAGE


def localize(value, lang: str) -> str:
    """Pick ``lang`` from a ``{"en": ..., "kn": ...}`` mapping, falling back to English."""
    if isinstance(value, dict):
        return value.get(lang) or value.get(DEFAULT_LANGUAGE) or ""
    return "" if value is None else str(value)


def translate(key: str, lang: str, **params) -> str:
    text = localize(STRINGS.get(key, {"en": key}), lang)
    return text.format(**params) if params else text
