import importlib
import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command

from public_forms.checks import check_languages
from public_forms.i18n import BASE_LANGUAGE, LOCALE_DIR, catalog, default_rating_labels, known_languages, translate
from public_forms.models import FeedbackForm
from public_forms.seed import add_language, add_language_to_forms, language_migrations
from public_forms.tests import TEST_LANGUAGE, plugin_configs
from public_forms.tests.test_pages import PageTestBase

# The languages the plugin ships, whichever they are.
BUILT_IN = sorted(path.stem for path in LOCALE_DIR.glob("*.json"))


def texts(value, path=""):
    """Every per-language object ({"en": ..., "<code>": ...}) in a form's text, as (path, object)."""
    if isinstance(value, dict):
        if isinstance(value.get(BASE_LANGUAGE), str):
            yield path, value
        for key, item in value.items():
            yield from texts(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from texts(item, f"{path}[{index}]")


class LocaleFileTests(PageTestBase):
    """Screen text comes from one JSON file per language (locale/, plus the LOCALE_DIRS setting)."""

    def locale_dir(self, **files):
        """A folder of locale files, e.g. locale_dir(yy={...}); the setting needs it as a path."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for code, content in files.items():
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            (Path(folder.name) / f"{code}.json").write_text(text, encoding="utf-8")
        return folder.name

    def with_locales(self, folder, languages):
        return self.settings(PLUGIN_CONFIGS=plugin_configs(LOCALE_DIRS=[folder], LANGUAGES=languages))

    def test_every_built_in_language_is_complete(self):
        # Each file the plugin ships names its language, translates every
        # string and rating label, and keeps the placeholders.
        with self.settings(PLUGIN_CONFIGS=plugin_configs(LANGUAGES=BUILT_IN, LOCALE_DIRS=[])):
            self.assertEqual(check_languages(None), [])
            for code in BUILT_IN:
                meta = catalog()[code]["language"]
                self.assertTrue(meta.get("name") and meta.get("toggle"), code)
            for value, labels in default_rating_labels().items():
                self.assertEqual(sorted(labels), BUILT_IN, value)
        self.assertEqual(translate("question_counter", BASE_LANGUAGE, n=2, total=10), "Question 2 of 10")

    def test_a_language_added_by_a_folder(self):
        folder = self.locale_dir(
            yy={
                "language": {"name": "Example", "toggle": "YY", "font": "Noto Sans Example", "tall_script": True},
                "strings": {"back": "Yback", "question_counter": "Q {n}/{total}"},
                "ratings": {"5": "Y5"},
            }
        )
        with self.with_locales(folder, ["en", "yy"]):
            self.assertEqual(translate("back", "yy"), "Yback")
            self.assertEqual(translate("next", "yy"), translate("next", BASE_LANGUAGE))  # missing: English
            self.assertEqual(translate("question_counter", "yy", n=1, total=3), "Q 1/3")
            page = self.client.get(self.url("form", "opd", lang="yy"))
            self.assertContains(page, 'data-lang="yy"')
            self.assertContains(page, 'data-set-lang="yy"')
            self.assertContains(page, ">YY</button>")
            self.assertContains(page, "family=Noto%20Sans%20Example")
            self.assertContains(page, """[lang="yy"]{font-family:'DM Sans','Noto Sans Example'""")
            self.assertContains(page, 'html[lang="yy"] .kicker')
            self.assertContains(page, "Y5")  # rating label from the file
            ids = [w.id for w in check_languages(None)]
            self.assertIn("public_forms.W004", ids)  # untranslated strings are listed

    def test_a_folder_can_correct_a_built_in_string(self):
        english = json.loads((LOCALE_DIR / f"{BASE_LANGUAGE}.json").read_text(encoding="utf-8"))["strings"]
        folder = self.locale_dir(**{BASE_LANGUAGE: {"strings": {"back": "Go back"}}})
        with self.with_locales(folder, [BASE_LANGUAGE]):
            self.assertEqual(translate("back", BASE_LANGUAGE), "Go back")
            self.assertEqual(translate("next", BASE_LANGUAGE), english["next"])  # the rest stays

    def test_a_broken_placeholder_falls_back_to_english(self):
        folder = self.locale_dir(yy={"language": {"name": "Y"}, "strings": {"question_counter": "Q {count}"}})
        with self.with_locales(folder, ["en", "yy"]):
            self.assertEqual(translate("question_counter", "yy", n=1, total=2), "Question 1 of 2")
            self.assertEqual(self.client.get(self.url("form", "opd", lang="yy")).status_code, 200)
            self.assertIn("public_forms.W005", [w.id for w in check_languages(None)])

    def test_an_unreadable_file_is_reported_not_fatal(self):
        folder = self.locale_dir(yy="{ not json")
        with self.with_locales(folder, ["en", "yy"]):
            self.assertEqual(self.client.get(self.url("form", "opd")).status_code, 200)
            ids = [w.id for w in check_languages(None)]
            self.assertIn("public_forms.W003", ids)  # can't be read
            self.assertIn("public_forms.W001", ids)  # so yy isn't offered

    def test_font_and_script_rules_follow_the_files(self):
        font = known_languages()[TEST_LANGUAGE]["font"]
        page = self.client.get(self.url("form", "opd")).content.decode()
        # DM Sans first, for English words and digits; the language's font draws its own script.
        rule = f"""html[lang="{TEST_LANGUAGE}"] body,[lang="{TEST_LANGUAGE}"]{{font-family:'DM Sans','{font}'"""
        self.assertIn(rule, page)
        self.assertIn(f'html[lang="{TEST_LANGUAGE}"] .kicker', page)  # a tall script
        self.assertIn(f'html[lang="{TEST_LANGUAGE}"] .hero-title{{font-size:', page)  # long words fit phones
        self.assertNotIn(f'html[lang="{BASE_LANGUAGE}"] .kicker', page)


class FormLanguageTests(PageTestBase):
    """A language's form text comes from its questionnaire migration (seed.add_language_to_forms)."""

    def test_default_forms_are_in_every_built_in_language(self):
        # A language shipped with a locale file needs a questionnaire migration too.
        for form in (self.opd, self.ipd):
            missing = [
                f"{code}: {path}"
                for path, text in texts({"title": form.title, "description": form.description, "q": form.questions})
                for code in BUILT_IN
                if not text.get(code)
            ]
            self.assertEqual(missing[:10], [], f"{form.code}: {len(missing)} text(s) not translated")

    def test_add_language_fills_in_and_never_overwrites(self):
        table = {"Other": "Other (test)", "Yes": "Yes (test)"}
        value = [
            {"en": "Other", TEST_LANGUAGE: "Kept"},
            {"en": "Other"},
            {"en": "Something new"},
            {"value": "x", "options": [{"en": "Yes"}]},
        ]
        self.assertTrue(add_language(value, TEST_LANGUAGE, table))
        self.assertEqual(
            value,
            [
                {"en": "Other", TEST_LANGUAGE: "Kept"},
                {"en": "Other", TEST_LANGUAGE: "Other (test)"},
                {"en": "Something new"},
                {"value": "x", "options": [{"en": "Yes", TEST_LANGUAGE: "Yes (test)"}]},
            ],
        )
        self.assertFalse(add_language(value, TEST_LANGUAGE, table))  # nothing left to add

    def test_a_questionnaire_migration_keeps_admin_edits(self):
        form = FeedbackForm.objects.create(
            facility_external_id=self.facility.external_id,
            code="test",
            patient_type="op",
            title={"en": "Visit feedback"},
            description={"en": "Reworded in the admin"},
            questions=[
                {
                    "key": "clinic",
                    "type": "choice",
                    "text": {"en": "Clinic visited", TEST_LANGUAGE: "Already translated"},
                    "options": [{"value": "ent", "en": "ENT"}, {"value": "new", "en": "Added in the admin"}],
                }
            ],
        )
        table = {
            "Visit feedback": "T title",
            "About your visit": "T description",
            "Clinic visited": "T clinic",
            "ENT": "T ent",
        }
        add_language_to_forms(FeedbackForm, TEST_LANGUAGE, table)
        form.refresh_from_db()
        self.assertEqual(form.title, {"en": "Visit feedback", TEST_LANGUAGE: "T title"})
        self.assertEqual(form.description, {"en": "Reworded in the admin"})  # not the English it knows
        question = form.questions[0]
        self.assertEqual(question["text"], {"en": "Clinic visited", TEST_LANGUAGE: "Already translated"})  # kept
        self.assertEqual([option.get(TEST_LANGUAGE) for option in question["options"]], ["T ent", None])

    def test_old_range_labels_get_hyphens(self):
        # Forms created before 0003 wrote ranges with an en dash. 0003 changes
        # the default labels to a hyphen and leaves reworded ones alone.
        migration = importlib.import_module("public_forms.migrations.0003_hyphens_in_range_labels")
        dash = "\u2013"
        form = FeedbackForm.objects.create(
            facility_external_id=self.facility.external_id,
            code="old",
            patient_type="op",
            title={"en": "Old form"},
            questions=[
                {
                    "key": "wait",
                    "type": "choice",
                    "text": {"en": "Wait"},
                    "options": [
                        {"value": "a", "en": f"10{dash}30 mins", "kn": f"10{dash}30 ನಿಮಿಷ"},
                        {"value": "b", "en": f"5{dash}10 days"},  # reworded in the admin
                    ],
                }
            ],
        )
        migration.use_hyphens(FeedbackForm)
        form.refresh_from_db()
        default, reworded = form.questions[0]["options"]
        self.assertEqual(default, {"value": "a", "en": "10-30 mins", "kn": "10-30 ನಿಮಿಷ"})
        self.assertEqual(reworded, {"value": "b", "en": f"5{dash}10 days"})

    def test_seeding_again_adds_every_language(self):
        # A default form deleted and re-created by the command gets the
        # languages of the questionnaire migrations, like a new install.
        self.ipd.delete()
        call_command("seed_feedback_forms", str(self.facility.external_id), stdout=io.StringIO())
        ipd = FeedbackForm.objects.get(code="ipd", facility_external_id=self.facility.external_id)
        for code, translations in language_migrations():
            self.assertEqual(ipd.title.get(code), translations[ipd.title[BASE_LANGUAGE]], code)
