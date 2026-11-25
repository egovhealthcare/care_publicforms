"""
Read-only staff API (mounted by Care at /api/public_forms/).

Access follows Care's facility permissions, as in the admin (access.py): a
user whose Care role at the facility, or in an area above it, can view its
questionnaire responses (on Care 3.0, read the facility) can read its feedback.
"""

from care.facility.models import Facility
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from public_forms.access import reaches, view_feedback
from public_forms.models import FeedbackSubmission, PatientType, QuestionType
from public_forms.questionnaire import NO_COMMENT, question_order

SUMMARISED_TYPES = (QuestionType.RATING, QuestionType.CHOICE)
LOWEST_ATTRIBUTES = 2  # NQAS "Check" step: root-cause the two lowest-scoring attributes


def health(request):
    return HttpResponse("OK")


class FeedbackSubmissionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="external_id", read_only=True)
    # From the linked form.
    form_code = serializers.CharField(source="form.code", read_only=True)
    patient_type = serializers.CharField(source="form.patient_type", read_only=True)

    class Meta:
        model = FeedbackSubmission
        fields = ("id", "reference_number", "submitted_at", "form_code", "patient_type", "language", "uhid", "answers")


class FacilityFeedbackMixin:
    def get_facility(self):
        facility = get_object_or_404(Facility, external_id=self.kwargs["facility_external_id"])
        if not reaches(self.request.user, facility, view_feedback()):
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
            filters &= Q(form__patient_type=patient_type)
        if form := params.get("form"):
            filters &= Q(form__code=form)
        return FeedbackSubmission.objects.filter(filters).select_related("form")


class FacilityFeedbackListView(FacilityFeedbackMixin, ListAPIView):
    """
    GET /api/public_forms/facility/<facility_id>/responses/

    Filters: patient_type (op | ip), form (code), submitted_after,
    submitted_before (YYYY-MM-DD). Paginated with limit/offset.
    """

    serializer_class = FeedbackSubmissionSerializer

    def get_queryset(self):
        return self.filter_submissions(self.get_facility()).order_by("-submitted_at")


def _summarise(facility, rows) -> list[dict]:
    """
    Aggregate submissions per form from the stored answers. Each answer carries
    its type and question, so questions since reworded or removed still count;
    the wording shown is the newest (``rows`` come newest first). Questions are
    listed in the form's current order, others after.
    """
    blocks = {}
    for form_code, patient_type, uhid, answers in rows:
        block = blocks.setdefault(
            form_code,
            {"form": form_code, "patient_type": patient_type, "total": 0, "with_uhid": 0, "_questions": {}},
        )
        block["total"] += 1
        block["with_uhid"] += bool(uhid)
        for key, entry in (answers or {}).items():
            if not isinstance(entry, dict) or entry.get("type") not in SUMMARISED_TYPES:
                continue
            question = block["_questions"].setdefault(
                key, {"key": key, "type": entry["type"], "question": entry.get("question") or key, "counts": {}}
            )
            value = entry.get("value")
            bucket = ("yes" if value else "no") if isinstance(value, bool) else str(value)
            question["counts"][bucket] = question["counts"].get(bucket, 0) + 1
            if entry["type"] == QuestionType.CHOICE and entry.get("answer"):
                question.setdefault("labels", {}).setdefault(bucket, entry["answer"])

    result = []
    for block in blocks.values():
        questions = block.pop("_questions")
        order = {key: index for index, key in enumerate(question_order(facility.external_id, block["form"]))}
        ratings, others = [], []
        scored_total = scored_count = 0
        for key in sorted(questions, key=lambda k: order.get(k, len(order))):
            question = questions[key]
            if question["type"] == QuestionType.RATING:
                counts = question.pop("counts")
                distribution = {str(v): counts.get(str(v), 0) for v in (5, 4, 3, 2, 1, NO_COMMENT)}
                count = sum(distribution[str(v)] for v in (1, 2, 3, 4, 5))
                total = sum(v * distribution[str(v)] for v in (1, 2, 3, 4, 5))
                scored_total += total
                scored_count += count
                ratings.append(
                    {**question, "average": round(total / count, 2) if count else None, "distribution": distribution}
                )
            else:
                others.append(question)
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
    GET /api/public_forms/facility/<facility_id>/summary/

    Same filters as the list. One block per form (OP and IP forms ask
    different questions) with the overall score, attribute-wise averages and
    distributions ("No comments" = 0 is not averaged), the two
    lowest-scoring attributes, and counts for yes/no and choice questions.
    """

    def get(self, request, facility_external_id):
        facility = self.get_facility()
        submissions = self.filter_submissions(facility).order_by("-submitted_at")
        rows = submissions.values_list("form__code", "form__patient_type", "uhid", "answers")
        return Response({"forms": _summarise(facility, rows.iterator())})
