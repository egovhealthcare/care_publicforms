"""
Default OPD and inpatient forms, from the NQAS patient satisfaction format
(Appendix A: OPD patient feedback and inpatient feedback).

They are created by a data migration on install and can be edited in the
admin afterwards; ``manage.py seed_feedback_forms`` re-creates any that are
missing. The OPD wording and Kannada come from the kiosk design. Kannada
marked ``# review`` (most of the inpatient form) is a draft that needs a
native speaker's check.
"""

import copy

WAIT_LABELS = [  # Poor → Excellent, as in the NQAS format  # review (kn)
    {"en": "More than 30 mins", "kn": "30 ನಿಮಿಷಕ್ಕಿಂತ ಹೆಚ್ಚು"},
    {"en": "10–30 mins", "kn": "10–30 ನಿಮಿಷ"},
    {"en": "5–10 mins", "kn": "5–10 ನಿಮಿಷ"},
    {"en": "Within 5 mins", "kn": "5 ನಿಮಿಷದೊಳಗೆ"},
    {"en": "Immediate", "kn": "ತಕ್ಷಣ"},
]

AGE_GROUP = {
    "key": "age_group",
    "type": "choice",
    "required": True,
    "audience": "guest",
    "text": {"en": "Age group", "kn": "ವಯೋಮಾನ"},
    "options": [
        {"value": "under_18", "en": "Under 18", "kn": "18ಕ್ಕಿಂತ ಕಡಿಮೆ"},
        {"value": "18_30", "en": "18–30", "kn": "18–30"},
        {"value": "31_45", "en": "31–45", "kn": "31–45"},
        {"value": "46_60", "en": "46–60", "kn": "46–60"},
        {"value": "over_60", "en": "Over 60", "kn": "60ಕ್ಕಿಂತ ಹೆಚ್ಚು"},
    ],
}

SEX = {
    "key": "sex",
    "type": "choice",
    "required": True,
    "audience": "guest",
    "text": {"en": "Sex", "kn": "ಲಿಂಗ"},
    "options": [
        {"value": "female", "en": "Female", "kn": "ಮಹಿಳೆ"},
        {"value": "male", "en": "Male", "kn": "ಪುರುಷ"},
        {"value": "other", "en": "Other", "kn": "ಇತರೆ"},
    ],
}

OPEN_QUESTIONS = [
    {
        "key": "would_return",
        "type": "choice",
        "step": "open",
        "allow_comment": True,
        "options": [
            {"value": "yes", "en": "Yes", "kn": "ಹೌದು"},
            {"value": "no", "en": "No", "kn": "ಇಲ್ಲ"},
        ],
        "text": {
            "en": "Would you come back to this hospital for treatment?",
            "kn": "ಚಿಕಿತ್ಸೆಗಾಗಿ ನೀವು ಈ ಆಸ್ಪತ್ರೆಗೆ ಮತ್ತೆ ಬರುತ್ತೀರಾ?",
        },
        "short_text": {"en": "Would return to this hospital", "kn": "ಈ ಆಸ್ಪತ್ರೆಗೆ ಮತ್ತೆ ಬರುತ್ತೇನೆ"},
    },
    {
        "key": "improvement",
        "type": "text",
        "text": {
            "en": "What would you most like to see improved?",
            "kn": "ಯಾವುದನ್ನು ಸುಧಾರಿಸಬೇಕೆಂದು ನೀವು ಬಯಸುತ್ತೀರಿ?",
        },
    },
    {
        "key": "reason_for_choosing",
        "type": "text",
        "text": {"en": "What made you choose this hospital?", "kn": "ಈ ಆಸ್ಪತ್ರೆಯನ್ನು ಆಯ್ಕೆ ಮಾಡಲು ಕಾರಣವೇನು?"},
    },
    {
        "key": "suggestions",
        "type": "text",
        "text": {"en": "Any other suggestions?", "kn": "ಇನ್ನಾವುದೇ ಸಲಹೆಗಳಿವೆಯೇ?"},
    },
]


def _rating(key, en, kn, short_en, short_kn, **extra):
    return {
        "key": key,
        "type": "rating",
        "text": {"en": en, "kn": kn},
        "short_text": {"en": short_en, "kn": short_kn},
        **extra,
    }


OPD_FORM = {
    "code": "opd",
    "patient_type": "op",
    "order": 1,
    "title": {"en": "OPD feedback", "kn": "ಒಪಿಡಿ ಅಭಿಪ್ರಾಯ"},  # review (kn)
    "description": {"en": "About today's outpatient visit", "kn": "ಇಂದಿನ ಹೊರರೋಗಿ ಭೇಟಿಯ ಬಗ್ಗೆ"},  # review (kn)
    "questions": [
        {
            "key": "clinic",
            "type": "choice",
            "required": True,
            "text": {"en": "Clinic visited", "kn": "ಭೇಟಿ ನೀಡಿದ ಚಿಕಿತ್ಸಾಲಯ"},
            "options": [
                {"value": "general_medicine", "en": "General Medicine", "kn": "ಸಾಮಾನ್ಯ ಔಷಧ"},
                {"value": "general_surgery", "en": "General Surgery", "kn": "ಸಾಮಾನ್ಯ ಶಸ್ತ್ರಚಿಕಿತ್ಸೆ"},
                {"value": "obstetrics_gynaecology", "en": "Obstetrics & Gynaecology", "kn": "ಪ್ರಸೂತಿ ಮತ್ತು ಸ್ತ್ರೀರೋಗ"},
                {"value": "paediatrics", "en": "Paediatrics", "kn": "ಮಕ್ಕಳ ವಿಭಾಗ"},
                {"value": "orthopaedics", "en": "Orthopaedics", "kn": "ಮೂಳೆ ವಿಭಾಗ"},
                {"value": "ent", "en": "ENT", "kn": "ಕಿವಿ ಮೂಗು ಗಂಟಲು"},
                {"value": "ophthalmology", "en": "Ophthalmology", "kn": "ಕಣ್ಣಿನ ವಿಭಾಗ"},
                {"value": "dermatology", "en": "Dermatology", "kn": "ಚರ್ಮರೋಗ"},
                {"value": "dental", "en": "Dental", "kn": "ದಂತ ವಿಭಾಗ"},
                {"value": "psychiatry", "en": "Psychiatry", "kn": "ಮನೋವೈದ್ಯಕೀಯ"},
            ],
        },
        AGE_GROUP,
        SEX,
        _rating(
            "information_signage",
            "Was there enough information to find your way around? (signages, registration, lab, X-ray, pharmacy)",
            "ದಾರಿ ಕಂಡುಕೊಳ್ಳಲು ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇತ್ತೇ? (ಸೂಚನಾ ಫಲಕ, ನೋಂದಣಿ, ಪ್ರಯೋಗಾಲಯ, ಕ್ಷ-ಕಿರಣ, ಔಷಧಾಲಯ)",
            "Information & signage",
            "ಮಾಹಿತಿ ಮತ್ತು ಫಲಕಗಳು",
        ),
        _rating(
            "registration_wait",
            "Waiting time at the registration counter",
            "ನೋಂದಣಿ ಕೌಂಟರ್‌ನಲ್ಲಿ ಕಾಯುವ ಸಮಯ",
            "Registration wait",
            "ನೋಂದಣಿ ಕಾಯುವಿಕೆ",
            options=WAIT_LABELS,
        ),
        _rating(
            "staff_behaviour",
            "Behaviour and attitude of the hospital staff",
            "ಆಸ್ಪತ್ರೆ ಸಿಬ್ಬಂದಿಯ ವರ್ತನೆ ಮತ್ತು ನಡವಳಿಕೆ",
            "Staff behaviour",
            "ಸಿಬ್ಬಂದಿ ವರ್ತನೆ",
        ),
        _rating(
            "waiting_area",
            "Amenities in the waiting area (seating, fans, drinking water, clean toilets)",
            "ಕಾಯುವ ಸ್ಥಳದ ಸೌಲಭ್ಯಗಳು (ಕುರ್ಚಿ, ಫ್ಯಾನ್, ಕುಡಿಯುವ ನೀರು, ಸ್ವಚ್ಛ ಶೌಚಾಲಯ)",
            "Waiting area",
            "ಕಾಯುವ ಸ್ಥಳ",
        ),
        _rating(
            "doctor_communication",
            "Attitude and communication of the doctors",
            "ವೈದ್ಯರ ನಡವಳಿಕೆ ಮತ್ತು ಸಂವಹನ",
            "Doctors' communication",
            "ವೈದ್ಯರ ಸಂವಹನ",
        ),
        _rating(
            "consultation_time",
            "Time spent on consultation, examination and counselling",
            "ಸಮಾಲೋಚನೆ, ಪರೀಕ್ಷೆ ಮತ್ತು ಸಲಹೆಗೆ ನೀಡಿದ ಸಮಯ",
            "Consultation time",
            "ಸಮಾಲೋಚನೆ ಸಮಯ",
        ),
        _rating(
            "lab_xray_access",
            "Availability of lab and X-ray facilities inside the hospital",
            "ಆಸ್ಪತ್ರೆಯೊಳಗೆ ಪ್ರಯೋಗಾಲಯ ಮತ್ತು ಕ್ಷ-ಕಿರಣ ಸೌಲಭ್ಯಗಳ ಲಭ್ಯತೆ",
            "Lab & X-ray access",
            "ಪ್ರಯೋಗಾಲಯ ಲಭ್ಯತೆ",
        ),
        _rating(
            "medicine_counter_speed",
            "Promptness at the medicine distribution counter",
            "ಔಷಧ ವಿತರಣಾ ಕೌಂಟರ್‌ನಲ್ಲಿ ತ್ವರಿತ ಸೇವೆ",
            "Medicine counter speed",
            "ಔಷಧ ಕೌಂಟರ್ ವೇಗ",
        ),
        _rating(
            "medicine_availability",
            "Availability of the prescribed medicines at the dispensary",
            "ಔಷಧಾಲಯದಲ್ಲಿ ಸೂಚಿಸಿದ ಔಷಧಿಗಳ ಲಭ್ಯತೆ",
            "Medicines available",
            "ಔಷಧಿ ಲಭ್ಯತೆ",
        ),
        _rating(
            "overall_satisfaction",
            "Your overall satisfaction with today's visit",
            "ಇಂದಿನ ಭೇಟಿಯ ಬಗ್ಗೆ ನಿಮ್ಮ ಒಟ್ಟಾರೆ ತೃಪ್ತಿ",
            "Overall satisfaction",
            "ಒಟ್ಟಾರೆ ತೃಪ್ತಿ",
        ),
        *OPEN_QUESTIONS,
    ],
}

# Kannada for the inpatient-only questions below is a draft.  # review (kn)
IPD_FORM = {
    "code": "ipd",
    "patient_type": "ip",
    "order": 2,
    "title": {"en": "Inpatient feedback", "kn": "ಒಳರೋಗಿ ಅಭಿಪ್ರಾಯ"},
    "description": {"en": "About your stay in the ward", "kn": "ವಾರ್ಡ್‌ನಲ್ಲಿನ ನಿಮ್ಮ ವಾಸ್ತವ್ಯದ ಬಗ್ಗೆ"},
    "questions": [
        {
            "key": "ward",
            "type": "choice",
            "required": True,
            "text": {"en": "Ward", "kn": "ವಾರ್ಡ್"},
            "options": [
                {"value": "medicine", "en": "General Medicine", "kn": "ಸಾಮಾನ್ಯ ಔಷಧ"},
                {"value": "surgery", "en": "General Surgery", "kn": "ಸಾಮಾನ್ಯ ಶಸ್ತ್ರಚಿಕಿತ್ಸೆ"},
                {"value": "obstetrics_gynaecology", "en": "Obstetrics & Gynaecology", "kn": "ಪ್ರಸೂತಿ ಮತ್ತು ಸ್ತ್ರೀರೋಗ"},
                {"value": "paediatrics", "en": "Paediatrics", "kn": "ಮಕ್ಕಳ ವಿಭಾಗ"},
                {"value": "orthopaedics", "en": "Orthopaedics", "kn": "ಮೂಳೆ ವಿಭಾಗ"},
                {"value": "icu", "en": "ICU / HDU", "kn": "ತೀವ್ರ ನಿಗಾ ಘಟಕ (ICU / HDU)"},
                {"value": "other", "en": "Other", "kn": "ಇತರೆ"},
            ],
        },
        {
            "key": "date_of_admission",
            "type": "date",
            "required": True,
            "text": {"en": "Date of admission", "kn": "ದಾಖಲಾದ ದಿನಾಂಕ"},
        },
        AGE_GROUP,
        SEX,
        _rating(
            "admission_information",
            "Was there enough information at the registration / admission counter? "
            "(signages, registration, lab, radiology, dispensary)",
            "ನೋಂದಣಿ / ದಾಖಲಾತಿ ಕೌಂಟರ್‌ನಲ್ಲಿ ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇತ್ತೇ? (ಸೂಚನಾ ಫಲಕ, ನೋಂದಣಿ, ಪ್ರಯೋಗಾಲಯ, ರೇಡಿಯಾಲಜಿ, ಔಷಧಾಲಯ)",
            "Information at admission",
            "ದಾಖಲಾತಿಯಲ್ಲಿ ಮಾಹಿತಿ",
        ),
        _rating(
            "admission_wait",
            "Waiting time at the registration / admission counter",
            "ನೋಂದಣಿ / ದಾಖಲಾತಿ ಕೌಂಟರ್‌ನಲ್ಲಿ ಕಾಯುವ ಸಮಯ",
            "Admission wait",
            "ದಾಖಲಾತಿ ಕಾಯುವಿಕೆ",
            options=WAIT_LABELS,
        ),
        _rating(
            "admission_staff_behaviour",
            "Behaviour and attitude of the staff at the registration / admission counter",
            "ನೋಂದಣಿ / ದಾಖಲಾತಿ ಕೌಂಟರ್ ಸಿಬ್ಬಂದಿಯ ವರ್ತನೆ ಮತ್ತು ನಡವಳಿಕೆ",
            "Admission staff behaviour",
            "ದಾಖಲಾತಿ ಸಿಬ್ಬಂದಿ ವರ್ತನೆ",
        ),
        _rating(
            "discharge_process",
            "Your feedback on the discharge process",
            "ಡಿಸ್ಚಾರ್ಜ್ ಪ್ರಕ್ರಿಯೆಯ ಬಗ್ಗೆ ನಿಮ್ಮ ಅಭಿಪ್ರಾಯ",
            "Discharge process",
            "ಡಿಸ್ಚಾರ್ಜ್ ಪ್ರಕ್ರಿಯೆ",
        ),
        _rating("ward_cleanliness", "Cleanliness of the ward", "ವಾರ್ಡ್‌ನ ಸ್ವಚ್ಛತೆ", "Ward cleanliness", "ವಾರ್ಡ್ ಸ್ವಚ್ಛತೆ"),
        _rating(
            "toilet_cleanliness",
            "Cleanliness of bathrooms and toilets",
            "ಸ್ನಾನಗೃಹ ಮತ್ತು ಶೌಚಾಲಯಗಳ ಸ್ವಚ್ಛತೆ",
            "Bathrooms & toilets",
            "ಸ್ನಾನಗೃಹ ಮತ್ತು ಶೌಚಾಲಯ",
        ),
        _rating(
            "linen_cleanliness",
            "Cleanliness of bed sheets, pillow covers, etc.",
            "ಹಾಸಿಗೆ ಹೊದಿಕೆ, ದಿಂಬಿನ ಕವರ್ ಇತ್ಯಾದಿಗಳ ಸ್ವಚ್ಛತೆ",
            "Bed linen",
            "ಹಾಸಿಗೆ ಬಟ್ಟೆಗಳು",
        ),
        _rating(
            "campus_cleanliness",
            "Cleanliness of the surroundings and campus drains",
            "ಸುತ್ತಮುತ್ತಲಿನ ಪ್ರದೇಶ ಮತ್ತು ಆವರಣದ ಚರಂಡಿಗಳ ಸ್ವಚ್ಛತೆ",
            "Campus cleanliness",
            "ಆವರಣದ ಸ್ವಚ್ಛತೆ",
        ),
        _rating(
            "doctor_regularity",
            "Regularity of the doctor's attention",
            "ವೈದ್ಯರು ನಿಯಮಿತವಾಗಿ ಗಮನ ನೀಡಿದರೇ",
            "Doctor's regular attention",
            "ವೈದ್ಯರ ನಿಯಮಿತ ಗಮನ",
        ),
        _rating(
            "doctor_communication",
            "Attitude and communication of the doctors",
            "ವೈದ್ಯರ ನಡವಳಿಕೆ ಮತ್ತು ಸಂವಹನ",
            "Doctors' communication",
            "ವೈದ್ಯರ ಸಂವಹನ",
        ),
        _rating(
            "examination_time",
            "Time spent on examining you and counselling",
            "ನಿಮ್ಮ ಪರೀಕ್ಷೆ ಮತ್ತು ಸಲಹೆಗೆ ನೀಡಿದ ಸಮಯ",
            "Examination time",
            "ಪರೀಕ್ಷೆಯ ಸಮಯ",
        ),
        _rating(
            "nurse_promptness",
            "Promptness of the nurses' response in the ward",
            "ವಾರ್ಡ್‌ನಲ್ಲಿ ದಾದಿಯರ ತ್ವರಿತ ಸ್ಪಂದನೆ",
            "Nurses' response",
            "ದಾದಿಯರ ಸ್ಪಂದನೆ",
        ),
        _rating(
            "nurse_availability",
            "Round-the-clock availability of nurses in the ward",
            "ವಾರ್ಡ್‌ನಲ್ಲಿ ದಿನದ 24 ಗಂಟೆಯೂ ದಾದಿಯರ ಲಭ್ಯತೆ",
            "Nurses available 24×7",
            "ದಾದಿಯರ ಲಭ್ಯತೆ",
        ),
        _rating(
            "nurse_communication",
            "Attitude and communication of the nurses",
            "ದಾದಿಯರ ನಡವಳಿಕೆ ಮತ್ತು ಸಂವಹನ",
            "Nurses' communication",
            "ದಾದಿಯರ ಸಂವಹನ",
        ),
        _rating(
            "ward_attendants",
            "Availability, attitude and promptness of ward attendants",
            "ವಾರ್ಡ್ ಸಹಾಯಕರ ಲಭ್ಯತೆ, ನಡವಳಿಕೆ ಮತ್ತು ತ್ವರಿತತೆ",
            "Ward attendants",
            "ವಾರ್ಡ್ ಸಹಾಯಕರು",
        ),
        _rating(
            "medicine_availability",
            "All prescribed medicines were provided from the hospital supply",
            "ಸೂಚಿಸಿದ ಎಲ್ಲಾ ಔಷಧಿಗಳನ್ನು ಆಸ್ಪತ್ರೆಯಿಂದಲೇ ಒದಗಿಸಲಾಯಿತು",
            "Medicines from hospital",
            "ಆಸ್ಪತ್ರೆಯಿಂದ ಔಷಧಿ",
        ),
        _rating(
            "doctor_knowledge",
            "Your impression of the doctors' knowledge",
            "ವೈದ್ಯರ ಜ್ಞಾನದ ಬಗ್ಗೆ ನಿಮ್ಮ ಅಭಿಪ್ರಾಯ",
            "Doctors' knowledge",
            "ವೈದ್ಯರ ಜ್ಞಾನ",
        ),
        _rating(
            "diagnostics_in_hospital",
            "Diagnostic services were provided within the hospital",
            "ರೋಗನಿರ್ಣಯ ಸೇವೆಗಳನ್ನು ಆಸ್ಪತ್ರೆಯೊಳಗೇ ಒದಗಿಸಲಾಯಿತು",
            "Diagnostics in hospital",
            "ಆಸ್ಪತ್ರೆಯಲ್ಲಿ ರೋಗನಿರ್ಣಯ",
        ),
        _rating(
            "diet",
            "Timeliness and quality of the food supplied",
            "ಆಹಾರ ಸರಬರಾಜಿನ ಸಮಯಪಾಲನೆ ಮತ್ತು ಗುಣಮಟ್ಟ",
            "Food: timing & quality",
            "ಆಹಾರ: ಸಮಯ ಮತ್ತು ಗುಣಮಟ್ಟ",
        ),
        _rating(
            "overall_satisfaction",
            "Your overall satisfaction with your treatment as an inpatient",
            "ಒಳರೋಗಿಯಾಗಿ ಪಡೆದ ಚಿಕಿತ್ಸೆಯ ಬಗ್ಗೆ ನಿಮ್ಮ ಒಟ್ಟಾರೆ ತೃಪ್ತಿ",
            "Overall satisfaction",
            "ಒಟ್ಟಾರೆ ತೃಪ್ತಿ",
        ),
        *OPEN_QUESTIONS,
    ],
}

DEFAULT_FORMS = [OPD_FORM, IPD_FORM]


def create_default_forms(form_model) -> list[str]:
    """
    Create the shared default forms that don't exist yet, with their questions
    as JSON. Takes the model class so the data migration can pass its
    historical model. Returns the codes created.
    """
    created = []
    for definition in DEFAULT_FORMS:
        if form_model.objects.filter(code=definition["code"], facility_external_id__isnull=True).exists():
            continue
        form_model.objects.create(
            code=definition["code"],
            patient_type=definition["patient_type"],
            order=definition["order"],
            title=definition["title"],
            description=definition["description"],
            questions=copy.deepcopy(definition["questions"]),
        )
        created.append(definition["code"])
    return created
