"""
Read-only staff API (mounted by Care at /api/patient_feedback/).

Access follows Care's facility permissions: a user who can view questionnaire
responses for the facility (``can_read_facility_questionnaire``) can read its
patient feedback.
"""

from uuid import UUID

from care.facility.models import Facility
from care.security.authorization import AuthorizationController
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from patient_feedback.models import FeedbackSubmission, IdentificationMethod, PatientType
from patient_feedback.questionnaire import NO_COMMENT

LOWEST_ATTRIBUTES = 2  # NQAS "Check" step: root-cause the two lowest-scoring attributes


def health(request):
    return HttpResponse("OK")


class FeedbackSubmissionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="external_id", read_only=True)

    class Meta:
        model = FeedbackSubmission
        fields = (
            "id",
            "reference_number",
            "submitted_at",
            "started_at",
            "form_code",
            "form_title",
            "form_external_id",
            "patient_type",
            "kiosk_external_id",
            "kiosk_name",
            "language",
            "identification_method",
            "uhid",
            "patient_external_id",
            "encounter_external_id",
            "answers",
            "ratings",
            "average_rating",
        )


class FacilityFeedbackMixin:
    def get_facility(self):
        facility = get_object_or_404(Facility, external_id=self.kwargs["facility_external_id"])
        if not AuthorizationController.call("can_read_facility_questionnaire", self.request.user, facility):
            raise PermissionDenied("You do not have permission to view feedback for this facility")
        return facility

    def filter_submissions(self, facility):
        params = self.request.query_params
        filters = Q(facility_external_id=facility.external_id)

        date_filters = (("submitted_after", "submitted_at__date__gte"), ("submitted_before", "submitted_at__date__lte"))
        for param, lookup in date_filters:
            if value := params.get(param):
                date = parse_date(value)
                if date is None:
                    raise ValidationError({param: "Use YYYY-MM-DD."})
                filters &= Q(**{lookup: date})
        if patient_type := params.get("patient_type"):
            if patient_type not in PatientType.values:
                raise ValidationError({"patient_type": f"One of {', '.join(PatientType.values)}."})
            filters &= Q(patient_type=patient_type)
        if form := params.get("form"):
            filters &= Q(form_code=form)
        if kiosk := params.get("kiosk"):
            try:
                filters &= Q(kiosk_external_id=UUID(kiosk))
            except ValueError as error:
                raise ValidationError({"kiosk": "Must be a kiosk id (UUID)."}) from error
        if method := params.get("identification_method"):
            if method not in IdentificationMethod.values:
                raise ValidationError({"identification_method": f"One of {', '.join(IdentificationMethod.values)}."})
            filters &= Q(identification_method=method)
        return FeedbackSubmission.objects.filter(filters)


class FacilityFeedbackListView(FacilityFeedbackMixin, ListAPIView):
    """
    GET /api/patient_feedback/facility/<facility_id>/responses/

    Filters: patient_type (op | ip), form (code), submitted_after,
    submitted_before (YYYY-MM-DD), kiosk (uuid), identification_method
    (scan | manual | guest). Paginated with limit/offset.
    """

    serializer_class = FeedbackSubmissionSerializer

    def get_queryset(self):
        return self.filter_submissions(self.get_facility()).order_by("-submitted_at")


def _summarise(rows) -> list[dict]:
    """Aggregate submissions per form; question labels come from the stored answers."""
    forms = {}
    for form_code, form_title, patient_type, method, answers in rows:
        form = forms.setdefault(
            form_code,
            {
                "form": form_code,
                "title": form_title,
                "patient_type": patient_type,
                "total": 0,
                "by_identification": dict.fromkeys(IdentificationMethod.values, 0),
                "_questions": {},
            },
        )
        form["total"] += 1
        form["by_identification"][method] = form["by_identification"].get(method, 0) + 1
        for answer in answers or []:
            if answer.get("type") not in ("rating", "yes_no", "choice"):
                continue
            question = form["_questions"].setdefault(
                answer["key"],
                {
                    "key": answer["key"],
                    "type": answer["type"],
                    "label": answer.get("label") or answer["key"],
                    "counts": {},
                },
            )
            value = answer.get("value")
            if value is None:
                continue
            bucket = str(value).lower() if isinstance(value, bool) else str(value)
            question["counts"][bucket] = question["counts"].get(bucket, 0) + 1

    result = []
    for form in forms.values():
        ratings, others = [], []
        scored_total = scored_count = 0
        for question in form.pop("_questions").values():
            counts = question.pop("counts")
            if question["type"] == "rating":
                distribution = {str(v): counts.get(str(v), 0) for v in (5, 4, 3, 2, 1, NO_COMMENT)}
                scored = {v: distribution[str(v)] for v in (1, 2, 3, 4, 5)}
                count = sum(scored.values())
                total = sum(v * c for v, c in scored.items())
                scored_total += total
                scored_count += count
                ratings.append(
                    {
                        **question,
                        "answered": count + distribution[str(NO_COMMENT)],
                        "average": round(total / count, 2) if count else None,
                        "distribution": distribution,
                    }
                )
            else:
                others.append({**question, "counts": counts})
        form["average_rating"] = round(scored_total / scored_count, 2) if scored_count else None
        form["questions"] = ratings
        form["lowest"] = [
            q["key"] for q in sorted((q for q in ratings if q["average"] is not None), key=lambda q: q["average"])
        ][:LOWEST_ATTRIBUTES]
        form["other_questions"] = others
        result.append(form)
    return result


class FacilityFeedbackSummaryView(FacilityFeedbackMixin, APIView):
    """
    GET /api/patient_feedback/facility/<facility_id>/summary/

    Same filters as the list. Returns one block per form (OP and IP forms ask
    different questions) with the overall score, attribute-wise averages and
    distributions ("No comments" = 0 is not averaged), the two
    lowest-scoring attributes, and counts for yes/no and choice questions.
    """

    def get(self, request, facility_external_id):
        submissions = self.filter_submissions(self.get_facility())
        rows = submissions.values_list("form_code", "form_title", "patient_type", "identification_method", "answers")
        forms = _summarise(rows.iterator())
        return Response({"total": sum(f["total"] for f in forms), "forms": forms})
