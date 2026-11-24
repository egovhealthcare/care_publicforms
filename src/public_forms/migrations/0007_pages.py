from django.db import migrations, models

# A form's questionnaire is now a list of pages, each with its questions,
# instead of a list of questions numbered by "step" plus step titles. This
# turns each step into a page, in step order, so nothing moves on screen:
# the questions keep their order (without "step"), and a step's title and
# lead become its page's "title" and "description". A step that somehow held
# both ratings and other questions becomes two pages, the other questions
# first, as the kiosk showed it. 0008 then drops the old fields.
#
# Going back numbers the questions by their page and moves the titles back;
# a page's "primary_button" has no place there and is dropped.
DEFAULT_STEPS = {"choice": 1, "date": 1, "rating": 2, "text": 3}
STEP_NAMES = {"details": 1, "ratings": 2, "open": 3}


def step_of(question) -> int:
    step = question.get("step")
    if isinstance(step, str):
        step = STEP_NAMES.get(step)
    if isinstance(step, bool) or not isinstance(step, int) or step < 1:
        step = DEFAULT_STEPS.get(question.get("type"), 1)
    return step


def pages_from(questions, titles) -> list:
    if not isinstance(questions, list):
        return []
    titles = titles if isinstance(titles, dict) else {}
    by_step = {}
    for question in questions:
        if isinstance(question, dict):
            by_step.setdefault(step_of(question), []).append({k: v for k, v in question.items() if k != "step"})
    pages = []
    for step in sorted(by_step):
        others = [question for question in by_step[step] if question.get("type") != "rating"]
        ratings = [question for question in by_step[step] if question.get("type") == "rating"]
        if others:
            page = {}
            heading = titles.get(str(step))
            if isinstance(heading, dict):
                if heading.get("title"):
                    page["title"] = heading["title"]
                if heading.get("lead"):
                    page["description"] = heading["lead"]
            pages.append({**page, "questions": others})
        if ratings:
            pages.append({"questions": ratings})
    return pages


def questions_from(pages) -> tuple[list, dict]:
    questions, titles = [], {}
    for number, page in enumerate(pages if isinstance(pages, list) else [], start=1):
        if not isinstance(page, dict):
            continue
        for question in page.get("questions") or []:
            if isinstance(question, dict):
                numbered = {}
                for name, value in question.items():
                    numbered[name] = value
                    if name == "type":
                        numbered["step"] = number
                numbered.setdefault("step", number)
                questions.append(numbered)
        heading = {}
        if page.get("title"):
            heading["title"] = page["title"]
        if page.get("description"):
            heading["lead"] = page["description"]
        if heading:
            titles[str(number)] = heading
    return questions, titles


def forwards(apps, schema_editor):
    for form in apps.get_model("public_forms", "FeedbackForm").objects.all():
        form.pages = pages_from(form.questions, form.steps)
        form.save(update_fields=["pages"])


def backwards(apps, schema_editor):
    for form in apps.get_model("public_forms", "FeedbackForm").objects.all():
        form.questions, form.steps = questions_from(form.pages)
        form.save(update_fields=["questions", "steps"])


class Migration(migrations.Migration):
    dependencies = [
        ("public_forms", "0006_form_facility_required"),
    ]

    operations = [
        migrations.AddField(
            model_name="feedbackform",
            name="pages",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="The pages, in the order shown, each with its questions (see below).",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
