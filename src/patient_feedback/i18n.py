"""
Screen text for the feedback pages, keyed by language code.

Every page carries its text in all offered languages, so switching language
in the browser is instant. Which languages are offered, and in what order, is
the LANGUAGES setting; it can use any language listed in ``KNOWN_LANGUAGES``.
To add one, add it there and give its strings below (missing strings fall
back to English), then translate the questions in the admin.

Strings marked ``# review`` were added for the kiosk build (they are not in
the original design file) and need a native-speaker check.
"""

# Questions and screen text must exist in English; other languages fall back to it.
BASE_LANGUAGE = "en"

# toggle: the header button; name: for screen readers and the admin;
# font: Google Fonts family loaded for the script (None: Figtree covers it).
KNOWN_LANGUAGES = {
    "en": {"toggle": "EN", "name": "English", "font": None},
    "kn": {"toggle": "ಕನ್ನಡ", "name": "Kannada", "font": "Noto Sans Kannada"},
}


def languages() -> dict:
    """The offered languages (the LANGUAGES setting), in order; English if none is usable."""
    from patient_feedback.settings import plugin_settings

    codes = [code for code in plugin_settings.LANGUAGES or [] if code in KNOWN_LANGUAGES]
    return {code: KNOWN_LANGUAGES[code] for code in dict.fromkeys(codes or [BASE_LANGUAGE])}


def admin_languages() -> dict:
    """Languages with a text box in the admin: English (required) and the offered ones."""
    return {BASE_LANGUAGE: KNOWN_LANGUAGES[BASE_LANGUAGE], **languages()}


STRINGS = {
    # ── Chrome ──────────────────────────────────────────────────────
    "kicker": {"en": "Patient feedback", "kn": "ರೋಗಿಯ ಅಭಿಪ್ರಾಯ"},  # review
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
    "hero_lead": {  # review (kn, with numbers)
        "en": "{n} short questions, about {m} minutes. Your answers stay confidential "
        "and are used only to improve our services.",
        "kn": "{n} ಸಣ್ಣ ಪ್ರಶ್ನೆಗಳು, ಸುಮಾರು {m} ನಿಮಿಷ. ನಿಮ್ಮ ಉತ್ತರಗಳು ಗೌಪ್ಯವಾಗಿರುತ್ತವೆ ಮತ್ತು ಸೇವೆ ಸುಧಾರಿಸಲು ಮಾತ್ರ ಬಳಸಲಾಗುತ್ತದೆ.",
    },
    "privacy_lead": {
        "en": "Your answers stay confidential and are used only to improve our services.",
        "kn": "ನಿಮ್ಮ ಉತ್ತರಗಳು ಗೌಪ್ಯವಾಗಿರುತ್ತವೆ ಮತ್ತು ಸೇವೆ ಸುಧಾರಿಸಲು ಮಾತ್ರ ಬಳಸಲಾಗುತ್ತದೆ.",
    },
    "step_choose": {  # review
        "en": "Step 1 — What is your feedback about?",
        "kn": "ಹಂತ 1 — ನಿಮ್ಮ ಅಭಿಪ್ರಾಯ ಯಾವುದರ ಬಗ್ಗೆ?",
    },
    "step_identify": {"en": "Step {n} — Identify yourself", "kn": "ಹಂತ {n} — ನಿಮ್ಮನ್ನು ಗುರುತಿಸಿ"},
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
    "continue": {"en": "Continue", "kn": "ಮುಂದುವರಿಯಿರಿ"},
    "no_uhid": {
        "en": "I don't have a UHID — continue as guest",
        "kn": "ನನಗೆ UHID ಇಲ್ಲ — ಅತಿಥಿಯಾಗಿ ಮುಂದುವರಿಯಿರಿ",
    },
    "keypad_clear": {"en": "Clear", "kn": "ತೆರವುಗೊಳಿಸಿ"},  # review
    "keypad_delete": {"en": "Delete last digit", "kn": "ಕೊನೆಯ ಅಂಕಿ ಅಳಿಸಿ"},  # review
    # ── Details ─────────────────────────────────────────────────────
    "details_heading": {"en": "A few quick details", "kn": "ಕೆಲವು ಸಣ್ಣ ವಿವರಗಳು"},  # review
    "details_lead_guest": {
        "en": "No name, no number. This only helps us group feedback by department.",
        "kn": "ಹೆಸರು ಇಲ್ಲ, ಸಂಖ್ಯೆ ಇಲ್ಲ. ವಿಭಾಗವಾರು ಪ್ರತಿಕ್ರಿಯೆ ವರ್ಗೀಕರಿಸಲು ಮಾತ್ರ ಇದು ಸಹಾಯ ಮಾಡುತ್ತದೆ.",
    },
    "details_lead": {
        "en": "This only helps us group feedback by department.",
        "kn": "ವಿಭಾಗವಾರು ಪ್ರತಿಕ್ರಿಯೆ ವರ್ಗೀಕರಿಸಲು ಮಾತ್ರ ಇದು ಸಹಾಯ ಮಾಡುತ್ತದೆ.",
    },
    "start_questions": {"en": "Start the questions", "kn": "ಪ್ರಶ್ನೆಗಳನ್ನು ಪ್ರಾರಂಭಿಸಿ"},
    "required_error": {"en": "This question needs an answer.", "kn": "ಈ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರ ಅಗತ್ಯವಿದೆ."},  # review
    "error_summary": {  # review
        "en": "Please answer the questions marked below.",
        "kn": "ಕೆಳಗೆ ಗುರುತಿಸಿದ ಪ್ರಶ್ನೆಗಳಿಗೆ ಉತ್ತರಿಸಿ.",
    },
    "too_many": {  # review
        "en": "Too many responses from this screen just now. Please wait a minute and try again.",
        "kn": "ಈ ಪರದೆಯಿಂದ ಇದೀಗ ಹೆಚ್ಚು ಪ್ರತಿಕ್ರಿಯೆಗಳು ಬಂದಿವೆ. ಒಂದು ನಿಮಿಷ ಕಾದು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
    "uhid_optional": {  # review; shown only when JavaScript is off
        "en": "UHID (leave empty to stay anonymous)",
        "kn": "UHID (ಅನಾಮಧೇಯವಾಗಿರಲು ಖಾಲಿ ಬಿಡಿ)",
    },
    "optional": {"en": "optional", "kn": "ಐಚ್ಛಿಕ"},
    # ── Rating ──────────────────────────────────────────────────────
    "question_counter": {"en": "Question {n} of {total}", "kn": "ಪ್ರಶ್ನೆ {n} / {total}"},
    # ── Open-ended ──────────────────────────────────────────────────
    "open_kicker": {"en": "In your own words", "kn": "ನಿಮ್ಮ ಮಾತಿನಲ್ಲಿ"},
    "open_heading": {"en": "Last {n} — all optional.", "kn": "ಕೊನೆಯ {n} — ಎಲ್ಲವೂ ಐಚ್ಛಿಕ."},  # review (kn, number)
    "open_heading_required": {"en": "Last {n} questions.", "kn": "ಕೊನೆಯ {n} ಪ್ರಶ್ನೆಗಳು."},  # review
    "open_why": {"en": "Why? (optional)", "kn": "ಏಕೆ? (ಐಚ್ಛಿಕ)"},
    "yes": {"en": "Yes", "kn": "ಹೌದು"},
    "no": {"en": "No", "kn": "ಇಲ್ಲ"},
    "review_answers": {"en": "Review answers", "kn": "ಉತ್ತರ ಪರಿಶೀಲಿಸಿ"},
    # ── Review ──────────────────────────────────────────────────────
    "review_heading": {"en": "Before you send", "kn": "ಕಳುಹಿಸುವ ಮೊದಲು"},
    "review_lead": {"en": "Tap any line to change it.", "kn": "ಬದಲಾಯಿಸಲು ಯಾವುದೇ ಸಾಲನ್ನು ಒತ್ತಿ."},
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


def normalize_language(code: str | None, default: str | None = None) -> str:
    """``code`` if it is offered, else ``default`` if offered, else the first offered language."""
    offered = languages()
    for candidate in (code, default):
        if candidate in offered:
            return candidate
    return next(iter(offered))


def localize(value, lang: str) -> str:
    """Pick ``lang`` from a ``{"en": ..., "kn": ...}`` mapping, falling back to English."""
    if isinstance(value, dict):
        return value.get(lang) or value.get(BASE_LANGUAGE) or ""
    return "" if value is None else str(value)


def translate(key: str, lang: str, **params) -> str:
    text = localize(STRINGS.get(key, {"en": key}), lang)
    return text.format(**params) if params else text
