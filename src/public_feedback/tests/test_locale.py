import json
import tempfile
from pathlib import Path

from public_feedback.checks import check_languages
from public_feedback.i18n import default_rating_labels, known_languages, translate
from public_feedback.tests.test_pages import PageTestBase


class LocaleFileTests(PageTestBase):
    """Screen text comes from one JSON file per language (locale/, plus the LOCALE_DIRS setting)."""

    def locale_dir(self, **files):
        """A folder of locale files, e.g. locale_dir(xx={...}); the setting needs it as a path."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for code, content in files.items():
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            (Path(folder.name) / f"{code}.json").write_text(text, encoding="utf-8")
        return folder.name

    def with_locales(self, folder, languages):
        return self.settings(PLUGIN_CONFIGS={"public_feedback": {"LOCALE_DIRS": [folder], "LANGUAGES": languages}})

    def test_built_in_languages(self):
        known = known_languages()
        self.assertEqual(
            known["kn"], {"name": "Kannada", "toggle": "ಕನ್ನಡ", "font": "Noto Sans Kannada", "tall_script": True}
        )
        self.assertEqual(known["en"]["font"], None)
        self.assertEqual(translate("back", "kn"), "ಹಿಂದೆ")
        self.assertEqual(translate("question_counter", "en", n=2, total=10), "Question 2 of 10")
        self.assertEqual(default_rating_labels()[0], {"en": "No comments", "kn": "ಪ್ರತಿಕ್ರಿಯೆ ಇಲ್ಲ"})

    def test_a_language_added_by_a_folder(self):
        folder = self.locale_dir(
            xx={
                "language": {"name": "Example", "toggle": "XX", "font": "Noto Sans Malayalam", "tall_script": True},
                "strings": {"back": "Xback", "question_counter": "Q {n}/{total}"},
                "ratings": {"5": "X5"},
            }
        )
        with self.with_locales(folder, ["en", "xx"]):
            self.assertEqual(translate("back", "xx"), "Xback")
            self.assertEqual(translate("next", "xx"), "Next")  # missing: English
            self.assertEqual(translate("question_counter", "xx", n=1, total=3), "Q 1/3")
            page = self.client.get(self.url("form", "opd", lang="xx"))
            self.assertContains(page, 'data-lang="xx"')
            self.assertContains(page, 'data-set-lang="xx"')
            self.assertContains(page, ">XX</button>")
            self.assertContains(page, "family=Noto%20Sans%20Malayalam")
            self.assertContains(page, """[lang="xx"]{font-family:'Noto Sans Malayalam'""")
            self.assertContains(page, 'html[lang="xx"] .kicker')
            self.assertContains(page, "X5")  # rating label from the file
            ids = [w.id for w in check_languages(None)]
            self.assertIn("public_feedback.W004", ids)  # untranslated strings are listed

    def test_a_folder_can_correct_a_built_in_string(self):
        folder = self.locale_dir(kn={"strings": {"back": "ಹಿಂದಕ್ಕೆ"}})
        with self.with_locales(folder, ["en", "kn"]):
            self.assertEqual(translate("back", "kn"), "ಹಿಂದಕ್ಕೆ")
            self.assertEqual(translate("next", "kn"), "ಮುಂದೆ")  # the rest stays

    def test_a_broken_placeholder_falls_back_to_english(self):
        folder = self.locale_dir(xx={"language": {"name": "X"}, "strings": {"question_counter": "Q {count}"}})
        with self.with_locales(folder, ["en", "xx"]):
            self.assertEqual(translate("question_counter", "xx", n=1, total=2), "Question 1 of 2")
            self.assertEqual(self.client.get(self.url("form", "opd", lang="xx")).status_code, 200)
            self.assertIn("public_feedback.W005", [w.id for w in check_languages(None)])

    def test_an_unreadable_file_is_reported_not_fatal(self):
        folder = self.locale_dir(xx="{ not json")
        with self.with_locales(folder, ["en", "kn", "xx"]):
            self.assertEqual(self.client.get(self.url("form", "opd")).status_code, 200)
            ids = [w.id for w in check_languages(None)]
            self.assertIn("public_feedback.W003", ids)  # can't be read
            self.assertIn("public_feedback.W001", ids)  # so xx isn't offered

    def test_font_and_script_rules_follow_the_files(self):
        page = self.client.get(self.url("form", "opd")).content.decode()
        self.assertIn("""html[lang="kn"] body,[lang="kn"]{font-family:'Noto Sans Kannada'""", page)
        self.assertIn('html[lang="kn"] .kicker', page)  # Kannada is a tall script
        self.assertNotIn('html[lang="en"] .kicker', page)
