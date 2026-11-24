import uuid
from unittest import mock

from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig
from django.test import override_settings

from public_forms.checks import check_uhid_lookup
from public_forms.models import FeedbackSubmission
from public_forms.patients import patient_id_in, uhid_config
from public_forms.tests import default_forms, plugin_configs
from public_forms.tests.test_pages import UHID, PageTestBase

UHID_SYSTEM = "https://example.org/uhid"


class PatientQrTests(PageTestBase):
    """A QR code that holds the patient's id in Care: the kiosk gets their UHID."""

    def setUp(self):
        super().setUp()
        self.patient = self.create_patient()
        # As Care is usually set up: one system-wide identifier config named UHID.
        self.uhids = self.identifier_config(None)
        self.identify(self.patient, self.uhids, "123-4567-8901")  # stored however Care's users typed it

    def identifier_config(self, facility, display="UHID", system=UHID_SYSTEM, status="active", **config):
        return PatientIdentifierConfig.objects.create(
            facility=facility,
            status=status,
            config={
                "use": "official",
                "system": system,
                "display": display,
                "unique": True,
                "required": False,
                "regex": "",
                **config,
            },
        )

    def identify(self, patient, config, value):
        return PatientIdentifier.objects.create(patient=patient, config=config, facility=config.facility, value=value)

    def lookup(self, patient, facility=None):
        return self.client.post(self.url("patient", facility=facility), {"patient": str(patient)})

    def assertUhid(self, response, uhid):
        self.assertEqual(response.status_code, 200 if uhid else 404, response.content)
        self.assertEqual(response.json(), {"uhid": uhid})

    def test_the_patients_id_gives_their_uhid(self):
        self.assertUhid(self.lookup(self.patient.external_id), UHID)
        # In capitals, or inside a link to the patient, too.
        self.assertUhid(self.lookup(str(self.patient.external_id).upper()), UHID)
        self.assertUhid(self.lookup(f"https://care.example.org/patient/{self.patient.external_id}"), UHID)
        # Only by POST, which keeps the id out of addresses and logs.
        self.assertEqual(self.client.get(self.url("patient")).status_code, 405)

    def test_the_scope_says_where_the_uhid_config_is(self):
        # Two facilities with their own UHID configs, and the system-wide one (setUp).
        hassan = self.create_facility(user=self.create_user(), name="Hassan hospital")
        default_forms(hassan)  # its kiosk needs forms
        mysuru_uhids = self.identifier_config(self.facility, system="https://mysuru.example.org/uhid")
        hassan_uhids = self.identifier_config(hassan, system="https://hassan.example.org/uhid")
        self.identify(self.patient, mysuru_uhids, "11111111111")
        self.identify(self.patient, hassan_uhids, "22222222222")

        # "system" (the default): the system-wide UHID at every facility; the facilities' own don't count.
        self.assertUhid(self.lookup(self.patient.external_id), UHID)
        self.assertUhid(self.lookup(self.patient.external_id, facility=hassan), UHID)

        # "facility": each facility's own UHID; the system-wide one doesn't count.
        with override_settings(PLUGIN_CONFIGS=plugin_configs(UHID_IDENTIFIER_SCOPE="facility")):
            self.assertUhid(self.lookup(self.patient.external_id), "11111111111")
            self.assertUhid(self.lookup(self.patient.external_id, facility=hassan), "22222222222")
            visitor = self.create_patient()  # a UHID only at Hassan, and system-wide
            self.identify(visitor, hassan_uhids, "33333333333")
            self.identify(visitor, self.uhids, "44444444444")
            self.assertUhid(self.lookup(visitor.external_id), None)
            self.assertUhid(self.lookup(visitor.external_id, facility=hassan), "33333333333")

        # Anything else: no UHID anywhere, and Django's checks say why.
        with override_settings(PLUGIN_CONFIGS=plugin_configs(UHID_IDENTIFIER_SCOPE="hospital")):
            self.assertUhid(self.lookup(self.patient.external_id), None)
            self.assertEqual([w.id for w in check_uhid_lookup(None)], ["public_forms.W007"])
        self.assertEqual(check_uhid_lookup(None), [])

    def test_which_identifier_holds_the_uhid(self):
        # The config named UHID, in any letter case; other identifiers, even
        # unique ones, and inactive configs don't count.
        admit = self.identifier_config(None, display="Admit ID", system="https://example.org/admit")
        self.identifier_config(None, system="https://example.org/old", status="inactive")
        self.identifier_config(self.facility, display="Facility MRN", system="https://example.org/mrn")
        self.assertEqual(uhid_config(self.facility), self.uhids)
        self.uhids.config["display"] = " uhid "
        self.uhids.save()
        self.assertEqual(uhid_config(self.facility), self.uhids)

        # Two of that name in one place: neither is used, until the setting
        # names one by its system.
        twin = self.identifier_config(None, system="https://example.org/twin")
        self.identify(self.patient, twin, "11111111111")
        with self.assertLogs("public_forms.patients", "WARNING"):
            self.assertUhid(self.lookup(self.patient.external_id), None)
        with override_settings(PLUGIN_CONFIGS=plugin_configs(UHID_IDENTIFIER=UHID_SYSTEM)):
            self.assertUhid(self.lookup(self.patient.external_id), UHID)
        with override_settings(PLUGIN_CONFIGS=plugin_configs(UHID_IDENTIFIER="https://example.org/twin")):
            self.assertUhid(self.lookup(self.patient.external_id), "11111111111")
        # Or another name.
        self.identify(self.patient, admit, "22222222222")
        with override_settings(PLUGIN_CONFIGS=plugin_configs(UHID_IDENTIFIER="admit id")):
            self.assertUhid(self.lookup(self.patient.external_id), "22222222222")

    def test_no_uhid_is_not_found(self):
        self.assertUhid(self.lookup(uuid.uuid4()), None)  # no such patient
        self.assertUhid(self.lookup("12345678901"), None)  # not a patient id
        self.assertUhid(self.lookup(""), None)
        self.assertUhid(self.lookup(self.create_patient().external_id), None)  # no UHID
        odd = self.create_patient()
        self.identify(odd, self.uhids, "MYS-0001")  # not in the kiosk's UHID format
        self.assertUhid(self.lookup(odd.external_id), None)
        self.patient.deleted = True
        self.patient.save(update_fields=["deleted"])
        self.assertUhid(self.lookup(self.patient.external_id), None)

    def test_lookups_are_rate_limited(self):
        with (
            mock.patch("public_forms.views.is_ratelimited", return_value=True) as limited,
            self.settings(DISABLE_RATELIMIT=False),
        ):
            response = self.lookup(self.patient.external_id)
        self.assertEqual((response.status_code, response.json()), (429, {"uhid": None}))
        self.assertEqual(limited.call_args.kwargs["group"], "public_forms.qr_lookup")

    def test_patient_id_in_a_code(self):
        patient = uuid.UUID("79e6f401-6e95-42b1-8ce6-01c71c031812")
        self.assertEqual(patient_id_in("79e6f401-6e95-42b1-8ce6-01c71c031812"), patient)
        self.assertEqual(patient_id_in(" 79E6F401-6E95-42B1-8CE6-01C71C031812\r\n"), patient)
        self.assertIsNone(patient_id_in("UHID:123-4567-8901"))
        self.assertIsNone(patient_id_in(None))

    # ── Without JavaScript: a keyboard-mode scanner types the code into the UHID box ──
    def press_uhid(self, code):
        return self.client.post(self.url("form", "opd"), {"nav": "uhid", "step": "uhid", "uhid": code})

    def test_without_javascript_a_scanned_patient_id_identifies_them(self):
        page = self.press_uhid(str(self.patient.external_id))
        self.assertEqual(page.context["current_step"], "screen-1")
        self.assertEqual(page.context["uhid"], UHID)
        self.assertContains(page, 'id="idStripValue">123 4567 8901<')

        unknown = self.press_uhid(str(uuid.uuid4()))
        self.assertEqual(unknown.context["current_step"], "uhid")
        self.assertEqual(unknown.context["errors"], {"uhid": "qr"})
        self.assertEqual(unknown.context["uhid"], "")  # the box is emptied
        self.assertContains(unknown, '<p class="err" id="uhidQrErr" role="alert">')
        self.assertContains(unknown, '<p class="err" id="uhidErr" role="alert" hidden>')

    def test_a_patient_id_submitted_as_the_uhid_is_looked_up(self):
        self.submit(uhid=str(self.patient.external_id), **self.answers(self.opd))
        self.assertEqual(FeedbackSubmission.objects.get().uhid, UHID)
        unknown = self.submit(uhid=str(uuid.uuid4()), **self.answers(self.opd))
        self.assertEqual(unknown.context["errors"]["uhid"], "qr")
        self.assertEqual(unknown.context["current_step"], "uhid")
        self.assertEqual(FeedbackSubmission.objects.count(), 1)

    def test_the_page_knows_where_to_look_up(self):
        self.assertContains(self.client.get(self.url("form", "opd")), f'data-patient-url="{self.url("patient")}"')
