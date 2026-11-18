"""
The OPD feedback questionnaire: rating questions, the rating scale and the
guest-detail choices.

Ratings are stored on ``FeedbackResponse.ratings`` keyed by ``Question.key``,
so keys must never be renamed once responses exist. Bump
``QUESTIONNAIRE_VERSION`` whenever the wording or the set of questions
changes, so reports can tell old and new responses apart.
"""

from dataclasses import dataclass, field

from django.utils.text import slugify

QUESTIONNAIRE_VERSION = "opd-v1"


@dataclass(frozen=True)
class Question:
    key: str
    text: dict
    short: dict
    hint: dict = field(default_factory=dict)


RATING_QUESTIONS: list[Question] = [
    Question(
        key="information_signage",
        text={
            "en": "Was there enough information to find your way around? "
            "(signages, registration, lab, X-ray, pharmacy)",
            "kn": "ದಾರಿ ಕಂಡುಕೊಳ್ಳಲು ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇತ್ತೇ? (ಸೂಚನಾ ಫಲಕ, ನೋಂದಣಿ, ಪ್ರಯೋಗಾಲಯ, ಕ್ಷ-ಕಿರಣ, ಔಷಧಾಲಯ)",
        },
        short={"en": "Information & signage", "kn": "ಮಾಹಿತಿ ಮತ್ತು ಫಲಕಗಳು"},
    ),
    Question(
        key="registration_wait",
        text={"en": "Waiting time at the registration counter", "kn": "ನೋಂದಣಿ ಕೌಂಟರ್‌ನಲ್ಲಿ ಕಾಯುವ ಸಮಯ"},
        short={"en": "Registration wait", "kn": "ನೋಂದಣಿ ಕಾಯುವಿಕೆ"},
        hint={
            "en": "Poor = over 30 minutes · Excellent = seen immediately",
            "kn": "ಕಳಪೆ = 30 ನಿಮಿಷಕ್ಕಿಂತ ಹೆಚ್ಚು · ಅತ್ಯುತ್ತಮ = ತಕ್ಷಣ",
        },
    ),
    Question(
        key="staff_behaviour",
        text={"en": "Behaviour and attitude of the hospital staff", "kn": "ಆಸ್ಪತ್ರೆ ಸಿಬ್ಬಂದಿಯ ವರ್ತನೆ ಮತ್ತು ನಡವಳಿಕೆ"},
        short={"en": "Staff behaviour", "kn": "ಸಿಬ್ಬಂದಿ ವರ್ತನೆ"},
    ),
    Question(
        key="waiting_area",
        text={
            "en": "Amenities in the waiting area (seating, fans, drinking water, clean toilets)",
            "kn": "ಕಾಯುವ ಸ್ಥಳದ ಸೌಲಭ್ಯಗಳು (ಕುರ್ಚಿ, ಫ್ಯಾನ್, ಕುಡಿಯುವ ನೀರು, ಸ್ವಚ್ಛ ಶೌಚಾಲಯ)",
        },
        short={"en": "Waiting area", "kn": "ಕಾಯುವ ಸ್ಥಳ"},
    ),
    Question(
        key="doctor_communication",
        text={"en": "Attitude and communication of the doctors", "kn": "ವೈದ್ಯರ ನಡವಳಿಕೆ ಮತ್ತು ಸಂವಹನ"},
        short={"en": "Doctors' communication", "kn": "ವೈದ್ಯರ ಸಂವಹನ"},
    ),
    Question(
        key="consultation_time",
        text={
            "en": "Time spent on consultation, examination and counselling",
            "kn": "ಸಮಾಲೋಚನೆ, ಪರೀಕ್ಷೆ ಮತ್ತು ಸಲಹೆಗೆ ನೀಡಿದ ಸಮಯ",
        },
        short={"en": "Consultation time", "kn": "ಸಮಾಲೋಚನೆ ಸಮಯ"},
    ),
    Question(
        key="lab_xray_access",
        text={
            "en": "Availability of lab and X-ray facilities inside the hospital",
            "kn": "ಆಸ್ಪತ್ರೆಯೊಳಗೆ ಪ್ರಯೋಗಾಲಯ ಮತ್ತು ಕ್ಷ-ಕಿರಣ ಸೌಲಭ್ಯಗಳ ಲಭ್ಯತೆ",
        },
        short={"en": "Lab & X-ray access", "kn": "ಪ್ರಯೋಗಾಲಯ ಲಭ್ಯತೆ"},
    ),
    Question(
        key="medicine_counter_speed",
        text={"en": "Promptness at the medicine distribution counter", "kn": "ಔಷಧ ವಿತರಣಾ ಕೌಂಟರ್‌ನಲ್ಲಿ ತ್ವರಿತ ಸೇವೆ"},
        short={"en": "Medicine counter speed", "kn": "ಔಷಧ ಕೌಂಟರ್ ವೇಗ"},
    ),
    Question(
        key="medicine_availability",
        text={
            "en": "Availability of the prescribed medicines at the dispensary",
            "kn": "ಔಷಧಾಲಯದಲ್ಲಿ ಸೂಚಿಸಿದ ಔಷಧಿಗಳ ಲಭ್ಯತೆ",
        },
        short={"en": "Medicines available", "kn": "ಔಷಧಿ ಲಭ್ಯತೆ"},
    ),
    Question(
        key="overall_satisfaction",
        text={"en": "Your overall satisfaction with today's visit", "kn": "ಇಂದಿನ ಭೇಟಿಯ ಬಗ್ಗೆ ನಿಮ್ಮ ಒಟ್ಟಾರೆ ತೃಪ್ತಿ"},
        short={"en": "Overall satisfaction", "kn": "ಒಟ್ಟಾರೆ ತೃಪ್ತಿ"},
    ),
]

QUESTION_KEYS = [q.key for q in RATING_QUESTIONS]

# 1–5 are scores; 0 means the patient chose "No comments" (answered, but not
# counted in averages).
NO_COMMENT = 0
SCALE = {
    5: {"en": "Excellent", "kn": "ಅತ್ಯುತ್ತಮ"},
    4: {"en": "Very good", "kn": "ತುಂಬಾ ಚೆನ್ನಾಗಿದೆ"},
    3: {"en": "Good", "kn": "ಚೆನ್ನಾಗಿದೆ"},
    2: {"en": "Fair", "kn": "ಸಾಧಾರಣ"},
    1: {"en": "Poor", "kn": "ಕಳಪೆ"},
    NO_COMMENT: {"en": "No comments", "kn": "ಪ್ರತಿಕ್ರಿಯೆ ಇಲ್ಲ"},
}
SCALE_VALUES = list(SCALE.keys())  # display order: 5 → 1, then 0

AGE_GROUPS = [
    ("under_18", {"en": "Under 18", "kn": "18ಕ್ಕಿಂತ ಕಡಿಮೆ"}),
    ("18_30", {"en": "18–30", "kn": "18–30"}),
    ("31_45", {"en": "31–45", "kn": "31–45"}),
    ("46_60", {"en": "46–60", "kn": "46–60"}),
    ("over_60", {"en": "Over 60", "kn": "60ಕ್ಕಿಂತ ಹೆಚ್ಚು"}),
]

SEXES = [
    ("female", {"en": "Female", "kn": "ಮಹಿಳೆ"}),
    ("male", {"en": "Male", "kn": "ಪುರುಷ"}),
    ("other", {"en": "Other", "kn": "ಇತರೆ"}),
]

# Used when a kiosk has no clinic list of its own.
DEFAULT_CLINICS = [
    {"en": "General Medicine", "kn": "ಸಾಮಾನ್ಯ ಔಷಧ"},
    {"en": "General Surgery", "kn": "ಸಾಮಾನ್ಯ ಶಸ್ತ್ರಚಿಕಿತ್ಸೆ"},
    {"en": "Obstetrics & Gynaecology", "kn": "ಪ್ರಸೂತಿ ಮತ್ತು ಸ್ತ್ರೀರೋಗ"},
    {"en": "Paediatrics", "kn": "ಮಕ್ಕಳ ವಿಭಾಗ"},
    {"en": "Orthopaedics", "kn": "ಮೂಳೆ ವಿಭಾಗ"},
    {"en": "ENT", "kn": "ಕಿವಿ ಮೂಗು ಗಂಟಲು"},
    {"en": "Ophthalmology", "kn": "ಕಣ್ಣಿನ ವಿಭಾಗ"},
    {"en": "Dermatology", "kn": "ಚರ್ಮರೋಗ"},
    {"en": "Dental", "kn": "ದಂತ ವಿಭಾಗ"},
    {"en": "Psychiatry", "kn": "ಮನೋವೈದ್ಯಕೀಯ"},
]


def normalize_clinics(clinics) -> list[tuple[str, dict]]:
    """
    Turn a kiosk's clinic config into ``[(code, labels), ...]``.

    Each entry is ``{"en": "...", "kn": "...", "code": "optional"}``; the code
    defaults to a slug of the English label. Invalid entries are skipped.
    """
    result = []
    seen = set()
    for item in clinics or DEFAULT_CLINICS:
        if isinstance(item, str):
            item = {"en": item}
        if not isinstance(item, dict) or not item.get("en"):
            continue
        code = str(item.get("code") or slugify(item["en"]).replace("-", "_"))[:64]
        if not code or code in seen:
            continue
        seen.add(code)
        result.append((code, {k: v for k, v in item.items() if k != "code"}))
    return result
