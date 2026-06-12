"""Catalog of multi-file feature fixtures for the ALMAS evaluation dataset.

Each :class:`FeatureFixture` describes a missing feature that ALMAS must
implement from scratch.  There is no injection/restore step — the repository
starts in the pre-state (feature absent) and grading is purely test-driven.

Add new entries to :data:`FEATURE_FIXTURES` and a matching grading test file
under ``eval_grading/``.
"""

from __future__ import annotations

from app.eval.bug_catalog import FeatureFixture

FEATURE_FIXTURES: list[FeatureFixture] = [
    FeatureFixture(
        slug="passenger-type-pricing",
        summary="Infant and child passengers are charged the same fare as adults",
        description=(
            "All passengers — regardless of age — are currently billed at the full flight price. "
            "The system must apply age-based pricing so that children and infants receive the "
            "appropriate discount.\n\n"
            "Pricing rules:\n"
            "- Adults (12 years old or over) pay 100 % of the flight price.\n"
            "- Children (aged 2 to 11 inclusive) pay 75 % of the flight price.\n"
            "- Infants (under 2 years old) pay 10 % of the flight price.\n\n"
            "The passenger_type field already exists on each passenger record but is not "
            "validated against the passenger's date_of_birth, and the booking total does not "
            "vary by type.\n\n"
            "Acceptance criteria:\n"
            "- A booking for one adult on a £200.00 flight costs £200.00.\n"
            "- A booking for one child on a £200.00 flight costs £150.00.\n"
            "- A booking for one infant on a £200.00 flight costs £20.00.\n"
            "- A mixed booking with one adult, one child, and one infant on a £200.00 flight "
            "costs £370.00.\n"
            "- Submitting passenger_type 'infant' for a passenger who is 3 years old is "
            "rejected with a validation error.\n"
            "- Submitting passenger_type 'child' for a passenger who is 13 years old is "
            "rejected with a validation error.\n"
            "- Submitting passenger_type 'child' for a passenger who is under 2 years old is "
            "rejected with a validation error.\n"
            "- Submitting passenger_type 'adult' for a passenger who is under 12 years old is "
            "rejected with a validation error.\n"
            "- Unknown passenger_type values (e.g. 'spaceman') are rejected.\n"
            "- When a booking is rescheduled to a different flight, the new booking total "
            "reflects per-type pricing at the new flight's price (not a copy of the old total)."
        ),
        test_file="eval_grading/test_passenger_type_pricing.py",
        expected_touched_files=[
            "backend/app/models/booking_passenger.py",
            "backend/app/schemas/booking.py",
            "backend/app/services/booking_service.py",
        ],
        issue_type="Story",
        priority="High",
        extra_labels=["hard"],
    ),
]


def get_feature(slug: str) -> FeatureFixture:
    for fixture in FEATURE_FIXTURES:
        if fixture.slug == slug:
            return fixture
    available = ", ".join(f.slug for f in FEATURE_FIXTURES)
    raise KeyError(f"Unknown feature fixture '{slug}'. Available: {available}")
