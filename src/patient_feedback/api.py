"""
Read-only staff API (mounted by Care at /api/patient_feedback/).

Access follows Care's facility permissions: a user who can view questionnaire
responses for the facility (``can_read_facility_questionnaire``) can read its
patient feedback.
"""

from uuid import UUID

from care.facility.models import Facility
from care.security.authorization import AuthorizationController
from django.db.models import Avg, Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from patient_feedback.models import FeedbackResponse, IdentificationMethod
from patient_feedback.questionnaire import NO_COMMENT, RATING_QUESTIONS, SCALE


def health(request):
    return HttpResponse("OK")


class FeedbackResponseSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="external_id", read_only=True)
    kiosk = serializers.SerializerMethodField()
    patient = serializers.SerializerMethodField()
    encounter = serializers.SerializerMethodField()

    class Meta:
        model = FeedbackResponse
        fields = (
            "id",
            "reference_number",
            "submitted_at",
            "started_at",
            "kiosk",
            "language",
            "questionnaire_version",
            "identification_method",
            "uhid",
            "patient",
            "encounter",
            "clinic",
            "age_group",
            "sex",
            "ratings",
            "average_rating",
            "would_return",
            "would_return_reason",
            "improvement",
            "reason_for_choosing",
            "suggestions",
        )

    def get_kiosk(self, obj):
        return {"id": str(obj.kiosk.external_id), "name": obj.kiosk.name}

    def get_patient(self, obj):
        return str(obj.patient.external_id) if obj.patient_id else None

    def get_encounter(self, obj):
        return str(obj.encounter.external_id) if obj.encounter_id else None


class FacilityFeedbackMixin:
    def get_facility(self):
        facility = get_object_or_404(Facility, external_id=self.kwargs["facility_external_id"])
        if not AuthorizationController.call("can_read_facility_questionnaire", self.request.user, facility):
            raise PermissionDenied("You do not have permission to view feedback for this facility")
        return facility

    def filter_responses(self, facility):
        params = self.request.query_params
        queryset = FeedbackResponse.objects.filter(facility=facility)

        filters = Q()
        date_filters = (("submitted_after", "submitted_at__date__gte"), ("submitted_before", "submitted_at__date__lte"))
        for param, lookup in date_filters:
            if value := params.get(param):
                date = parse_date(value)
                if date is None:
                    raise ValidationError({param: "Use YYYY-MM-DD."})
                filters &= Q(**{lookup: date})
        if kiosk := params.get("kiosk"):
            try:
                filters &= Q(kiosk__external_id=UUID(kiosk))
            except ValueError as error:
                raise ValidationError({"kiosk": "Must be a kiosk id (UUID)."}) from error
        if method := params.get("identification_method"):
            if method not in IdentificationMethod.values:
                raise ValidationError({"identification_method": f"One of {', '.join(IdentificationMethod.values)}."})
            filters &= Q(identification_method=method)
        return queryset.filter(filters)


class FacilityFeedbackListView(FacilityFeedbackMixin, ListAPIView):
    """
    GET /api/patient_feedback/facility/<facility_id>/responses/

    Filters: submitted_after, submitted_before (YYYY-MM-DD), kiosk (uuid),
    identification_method (scan | manual | guest). Paginated with limit/offset.
    """

    serializer_class = FeedbackResponseSerializer

    def get_queryset(self):
        facility = self.get_facility()
        return self.filter_responses(facility).select_related("kiosk", "patient", "encounter").order_by("-submitted_at")


class FacilityFeedbackSummaryView(FacilityFeedbackMixin, APIView):
    """
    GET /api/patient_feedback/facility/<facility_id>/summary/

    Same filters as the list. Per-question averages ignore "No comments" (0).
    """

    def get(self, request, facility_external_id):
        facility = self.get_facility()
        queryset = self.filter_responses(facility)

        aggregates = {
            "total": Count("id"),
            "average": Avg("average_rating"),
            "would_return_yes": Count("id", filter=Q(would_return=True)),
            "would_return_no": Count("id", filter=Q(would_return=False)),
        }
        for method in IdentificationMethod.values:
            aggregates[f"method_{method}"] = Count("id", filter=Q(identification_method=method))
        for question in RATING_QUESTIONS:
            for value in SCALE:
                aggregates[f"{question.key}__{value}"] = Count("id", filter=Q(**{f"ratings__{question.key}": value}))
        totals = queryset.aggregate(**aggregates)

        questions = []
        for question in RATING_QUESTIONS:
            distribution = {str(value): totals[f"{question.key}__{value}"] for value in SCALE}
            scored = {value: totals[f"{question.key}__{value}"] for value in SCALE if value != NO_COMMENT}
            scored_count = sum(scored.values())
            questions.append(
                {
                    "key": question.key,
                    "label": question.short,
                    "answered": scored_count + distribution[str(NO_COMMENT)],
                    "average": round(sum(v * c for v, c in scored.items()) / scored_count, 2) if scored_count else None,
                    "distribution": distribution,
                }
            )

        return Response(
            {
                "total": totals["total"],
                "average_rating": round(float(totals["average"]), 2) if totals["average"] is not None else None,
                "by_identification": {method: totals[f"method_{method}"] for method in IdentificationMethod.values},
                "would_return": {
                    "yes": totals["would_return_yes"],
                    "no": totals["would_return_no"],
                    "unanswered": totals["total"] - totals["would_return_yes"] - totals["would_return_no"],
                },
                "scale": {str(value): label for value, label in SCALE.items()},
                "questions": questions,
            }
        )
