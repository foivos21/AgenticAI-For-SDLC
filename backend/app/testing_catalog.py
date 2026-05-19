from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.services.almas.repository import slugify_branch_component


class TestingTaskCatalogEntry(BaseModel):
    slug: str
    issue_key: str
    title: str
    description: str
    expected_touched_paths: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    expected_acceptance_criteria: list[str] = Field(default_factory=list)
    expected_outcome: str
    jira_snapshot_path: str

    @property
    def expected_branch_name(self) -> str:
        return f"feature/{self.issue_key.upper()}-{slugify_branch_component(self.title)}"

    def load_jira_snapshot(self) -> dict:
        path = Path(self.jira_snapshot_path)
        return json.loads(path.read_text(encoding="utf-8"))


def list_testing_tasks() -> list[TestingTaskCatalogEntry]:
    root = Path(__file__).resolve().parents[1] / "data" / "almas"
    return [
        TestingTaskCatalogEntry(
            slug="sdlc_1_seat_preference",
            issue_key="SDLC-1",
            title="Booking flow should honor seat preference",
            description="Validate seat-preference localization, planning, edit generation, and GitHub PR creation.",
            expected_touched_paths=[
                "app/models/booking.py",
                "app/services/booking_service.py",
            ],
            allowed_paths=[
                "app/models/booking.py",
                "app/services/booking_service.py",
                "app/schemas/booking.py",
                "app/api/routes/bookings.py",
            ],
            forbidden_paths=[
                "frontend/src/App.jsx",
            ],
            expected_acceptance_criteria=[
                "Seat preference should be retained from the initial selection to the confirmation stage.",
                "The final booking response must include the confirmed seat preference.",
            ],
            expected_outcome="needs_revision",
            jira_snapshot_path=str(root / "sdlc-1-20260512212613-ce86544c" / "jira_snapshot.json"),
        ),
        TestingTaskCatalogEntry(
            slug="sdlc_2_cancellation_refund",
            issue_key="SDLC-2",
            title="Customer should be able to cancel booking for refund",
            description="Validate cancellation/refund localization and service-layer planning.",
            expected_touched_paths=[
                "app/api/routes/bookings.py",
                "app/models/booking.py",
                "app/services/booking_service.py",
            ],
            allowed_paths=[
                "app/api/routes/bookings.py",
                "app/models/booking.py",
                "app/services/booking_service.py",
                "app/schemas/booking.py",
            ],
            forbidden_paths=[
                "frontend/src/App.jsx",
            ],
            expected_acceptance_criteria=[
                "The booking should be verified before cancellation.",
                "A successful cancellation should update the booking status accordingly.",
                "A clear explanation of the refund outcome should be provided to the customer.",
            ],
            expected_outcome="needs_revision",
            jira_snapshot_path=str(root / "sdlc-2-20260513124717-51cb5bf0" / "jira_snapshot.json"),
        ),
        TestingTaskCatalogEntry(
            slug="sdlc_3_premium_segment",
            issue_key="SDLC-3",
            title="Need better support for premium customer segment",
            description="Validate premium-segment model planning and approval path.",
            expected_touched_paths=[
                "app/models/booking.py",
                "app/models/flight.py",
                "app/models/seat_inventory.py",
            ],
            allowed_paths=[
                "app/models/booking.py",
                "app/models/flight.py",
                "app/models/seat_inventory.py",
                "app/schemas/booking.py",
            ],
            forbidden_paths=[],
            expected_acceptance_criteria=[
                "Premium customer handling should be reflected in booking, flight, and seat inventory behavior.",
            ],
            expected_outcome="approved",
            jira_snapshot_path=str(root / "sdlc-3-20260512205547-d94dbb97" / "jira_snapshot.json"),
        ),
        TestingTaskCatalogEntry(
            slug="sdlc_4_invalid_mapping",
            issue_key="SDLC-4",
            title="Unknown mapped task test",
            description="Validate invalid mapping/error-handling behavior and safe failure modes.",
            expected_touched_paths=[
                "app/config.py",
                "app/main.py",
            ],
            allowed_paths=[
                "app/config.py",
                "app/main.py",
                "app/api/errors.py",
            ],
            forbidden_paths=[
                "app/services/booking_service.py",
            ],
            expected_acceptance_criteria=[
                "System should log mapping failures clearly.",
                "User-facing error messages should be informative regarding the failure.",
                "No application crashes should occur due to invalid mappings.",
            ],
            expected_outcome="needs_revision",
            jira_snapshot_path=str(root / "sdlc-4-20260513124708-65d94c20" / "jira_snapshot.json"),
        ),
    ]


def get_testing_task(task_slug: str) -> TestingTaskCatalogEntry:
    for task in list_testing_tasks():
        if task.slug == task_slug:
            return task
    raise KeyError(task_slug)
