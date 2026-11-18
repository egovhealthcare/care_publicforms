"""
Read-only staff API (mounted by Care at /api/patient_feedback/).

Access follows Care's facility permissions: a user who can view questionnaire
responses for the facility (``can_read_facility_questionnaire``) can read its
patient feedback.
"""

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

from patient_feedback.models import FeedbackSubmission, PatientType, QuestionType
from patient_feedback.questionnaire import NO_COMMENT, form_for_submission

SUMMARISED_TYPES = (QuestionType.RATING, QuestionType.YES_NO, QuestionType.CHOICE)
LOWEST_ATTRIBUTES = 2  # NQAS "Check" step: root-cause the two lowest-scoring attributes


def health(request):
    return HttpResponse("OK")


class FeedbackSubmissionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="external_id", read_only=True)

    class Meta:
        model = FeedbackSubmission
        fields = ("id", "reference_number", "submitted_at", "form_code", "patient_type", "language", "uhid", "answers")


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
                try:
                    date = parse_date(value)
                except ValueError:  # well formed but not a real date, e.g. 2026-13-01
                    date = None
                if date is None:
                    raise ValidationError({param: "Use YYYY-MM-DD."})
                filters &= Q(**{lookup: date})
        if patient_type := params.get("patient_type"):
            if patient_type not in PatientType.values:
                raise ValidationError({"patient_type": f"One of {', '.join(PatientType.values)}."})
            filters &= Q(patient_type=patient_type)
        if form := params.get("form"):
            filters &= Q(form_code=form)
        return FeedbackSubmission.objects.filter(filters)


class FacilityFeedbackListView(FacilityFeedbackMixin, ListAPIView):
    """
    GET /api/patient_feedback/facility/<facility_id>/responses/

    Filters: patient_type (op | ip), form (code), submitted_after,
    submitted_before (YYYY-MM-DD). Paginated with limit/offset.
    """

    serializer_class = FeedbackSubmissionSerializer

    def get_queryset(self):
        return self.filter_submissions(self.get_facility()).order_by("-submitted_at")


def _summarise(facility, rows) -> list[dict]:
    """
    Aggregate submissions per form. Which answers are ratings, yes/no or
    choices comes from the form as it is now; keys no longer on it are left out.
    """
    blocks = {}
    for form_code, patient_type, uhid, answers in rows:
        if form_code not in blocks:
            form = form_for_submission(facility.external_id, form_code)
            questions = list(form.questions.order_by("order", "id")) if form else []
            blocks[form_code] = {
                "form": form_code,
                "patient_type": patient_type,
                "total": 0,
                "with_uhid": 0,
                "_questions": [q for q in questions if q.type in SUMMARISED_TYPES],
                "_counts": {q.key: {} for q in questions},
            }
        block = blocks[form_code]
        block["total"] += 1
        block["with_uhid"] += bool(uhid)
        for key, value in (answers or {}).items():
            counts = block["_counts"].get(key)
            if counts is None or value is None:
                continue
            bucket = ("yes" if value else "no") if isinstance(value, bool) else str(value)
            counts[bucket] = counts.get(bucket, 0) + 1

    result = []
    for block in blocks.values():
        counts_by_key = block.pop("_counts")
        ratings, others = [], []
        scored_total = scored_count = 0
        for question in block.pop("_questions"):
            counts = counts_by_key[question.key]
            item = {"key": question.key, "type": question.type, "text": question.text}
            if question.type == QuestionType.RATING:
                distribution = {str(v): counts.get(str(v), 0) for v in (5, 4, 3, 2, 1, NO_COMMENT)}
                count = sum(distribution[str(v)] for v in (1, 2, 3, 4, 5))
                total = sum(v * distribution[str(v)] for v in (1, 2, 3, 4, 5))
                scored_total += total
                scored_count += count
                ratings.append(
                    {**item, "average": round(total / count, 2) if count else None, "distribution": distribution}
                )
            else:
                others.append({**item, "counts": counts})
        block["average_rating"] = round(scored_total / scored_count, 2) if scored_count else None
        block["lowest"] = [
            q["key"] for q in sorted((q for q in ratings if q["average"] is not None), key=lambda q: q["average"])
        ][:LOWEST_ATTRIBUTES]
        block["ratings"] = ratings
        block["other_questions"] = others
        result.append(block)
    return result


class FacilityFeedbackSummaryView(FacilityFeedbackMixin, APIView):
    """
    GET /api/patient_feedback/facility/<facility_id>/summary/

    Same filters as the list. One block per form (OP and IP forms ask
    different questions) with the overall score, attribute-wise averages and
    distributions ("No comments" = 0 is not averaged), the two
    lowest-scoring attributes, and counts for yes/no and choice questions.
    """

    def get(self, request, facility_external_id):
        facility = self.get_facility()
        rows = self.filter_submissions(facility).values_list("form_code", "patient_type", "uhid", "answers")
        return Response({"forms": _summarise(facility, rows.iterator())})
