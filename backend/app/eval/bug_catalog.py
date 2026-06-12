"""Catalog of bug fixtures and feature fixtures for the ALMAS evaluation dataset.

:class:`BugFixture` — single-file, reversible defect
    * ``target_file`` is the one real file the bug lives in.
    * ``correct`` / ``broken`` are an exact search/replace pair. The ``correct``
      text ships in the repo; injecting swaps it for ``broken``, restoring swaps
      it back.
    * ``summary`` / ``description`` become the Jira ticket (symptom + acceptance
      criteria only — never the fix).

:class:`FeatureFixture` — multi-file missing feature
    * No ``correct``/``broken`` pair — the current repo *is* the pre-state.
    * ``test_file`` points to a backend-relative pytest suite that grades a
      correct implementation purely by observable behaviour.
    * ``expected_touched_files`` is documentation for reviewers; it does not
      constrain what ALMAS is allowed to change.

The ``ai_task:<slug>`` label ties every ticket back to its fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DATASET_LABEL = "almas-eval"

# Behavioral test file (relative to the backend/ directory) that grades a fix,
# keyed by the real source file the bug lives in.
_TEST_FILES: dict[str, str] = {
    "backend/app/services/flight_service.py": "eval_grading/test_flight_service_fakes.py",
    "backend/app/services/knowledge_service.py": "eval_grading/test_knowledge_service_fakes.py",
    "backend/app/db/seat_inventory.py": "eval_grading/test_seat_inventory_fakes.py",
    "backend/app/services/booking_service.py": "eval_grading/test_booking_service_fakes.py",
}


@dataclass(frozen=True)
class BugFixture:
    slug: str
    summary: str
    description: str
    target_file: str
    correct: str
    broken: str
    issue_type: str = "Submit a request or incident"
    priority: str | None = None
    extra_labels: list[str] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [f"ai_task:{self.slug}", DATASET_LABEL, *self.extra_labels]

    @property
    def test_file(self) -> str | None:
        """Backend-relative pytest path that grades a fix for this bug."""
        return _TEST_FILES.get(self.target_file)


@dataclass(frozen=True)
class FeatureFixture:
    """A missing-feature eval task that spans multiple files.

    Unlike :class:`BugFixture` there is nothing to inject or restore — the repo
    starts in the pre-state and ALMAS must add the feature from scratch.
    Grading is entirely test-driven via ``test_file``.
    """

    slug: str
    summary: str
    description: str
    test_file: str
    expected_touched_files: list[str] = field(default_factory=list)
    issue_type: str = "Story"
    priority: str | None = None
    extra_labels: list[str] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [f"ai_task:{self.slug}", DATASET_LABEL, *self.extra_labels]


BUG_FIXTURES: list[BugFixture] = [
    BugFixture(
        slug="flight-price-filter-inverted",
        summary="Flight search 'max price' filter returns the most expensive flights",
        description=(
            "Searching flights with a maximum price returns only flights that cost MORE than the "
            "limit, instead of flights at or under it.\n\n"
            "Steps to reproduce:\n"
            "- Call GET /flights/search?max_price=200\n"
            "- Observe that only flights priced above 200 are returned\n\n"
            "Expected behaviour:\n"
            "- The results include only flights whose price is less than or equal to the given "
            "max_price.\n\n"
            "Affected file:\n"
            "- backend/app/services/flight_service.py (search_flights)"
        ),
        target_file="backend/app/services/flight_service.py",
        correct="            statement = statement.where(Flight.price <= max_price)",
        broken="            statement = statement.where(Flight.price >= max_price)",
    ),
    BugFixture(
        slug="flight-origin-case",
        summary="Flight search by origin airport returns no results",
        description=(
            "Searching flights by origin airport always returns an empty list, even for airports "
            "that clearly have flights.\n\n"
            "Steps to reproduce:\n"
            "- Call GET /flights/search?origin=ath\n"
            "- Observe that no flights are returned although ATH has scheduled flights\n\n"
            "Expected behaviour:\n"
            "- The origin filter matches regardless of the casing of the supplied airport code "
            "(airport codes are stored in upper case).\n\n"
            "Affected file:\n"
            "- backend/app/services/flight_service.py (search_flights)"
        ),
        target_file="backend/app/services/flight_service.py",
        correct="            statement = statement.where(Flight.origin_airport == origin.upper())",
        broken="            statement = statement.where(Flight.origin_airport == origin.lower())",
    ),
    BugFixture(
        slug="knowledge-search-prefix-only",
        summary="Knowledge base search misses articles that match in the middle of the text",
        description=(
            "Searching the knowledge base only returns articles whose topic/title/content START "
            "with the query. Matches that occur in the middle of a field are missed.\n\n"
            "Steps to reproduce:\n"
            "- Search for a word that appears mid-sentence in an article's content\n"
            "- Observe that the article is not returned\n\n"
            "Expected behaviour:\n"
            "- Search performs a contains match, returning any article where the query appears "
            "anywhere in the topic, title, or content.\n\n"
            "Affected file:\n"
            "- backend/app/services/knowledge_service.py (search)"
        ),
        target_file="backend/app/services/knowledge_service.py",
        correct='        pattern = f"%{query.strip()}%"',
        broken='        pattern = f"{query.strip()}%"',
    ),
    BugFixture(
        slug="booking-total-wrong-operator",
        summary="Booking total price is calculated incorrectly for multiple passengers",
        description=(
            "When creating a booking, the base total is wrong for more than one passenger. It "
            "adds the passenger count to the fare instead of multiplying.\n\n"
            "Steps to reproduce:\n"
            "- Create a booking for a 200.00 flight with 3 passengers\n"
            "- Observe the base total is 203.00 instead of 600.00\n\n"
            "Expected behaviour:\n"
            "- The base total equals the flight price multiplied by the number of passengers.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (create_booking)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="        total_price = flight.price * passenger_count",
        broken="        total_price = flight.price + passenger_count",
    ),
    BugFixture(
        slug="booking-extras-subtract",
        summary="Adding extras to a booking lowers the total price instead of raising it",
        description=(
            "Adding paid extras to an existing booking reduces the total price instead of "
            "increasing it.\n\n"
            "Steps to reproduce:\n"
            "- Add a paid extra to a booking\n"
            "- Observe the booking total goes down by the extra's price\n\n"
            "Expected behaviour:\n"
            "- Each added extra increases the booking total by the extra's price.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (add_extras)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="            total_extra_price += extra_price",
        broken="            total_extra_price -= extra_price",
    ),
    BugFixture(
        slug="seat-available-count-inflated",
        summary="Available seat count is inflated on flight details",
        description=(
            "The number of available seats reported for a flight is too high. It is computed as "
            "total + booked instead of total - booked.\n\n"
            "Steps to reproduce:\n"
            "- Open any flight's details\n"
            "- Observe that available_seats exceeds the aircraft capacity\n\n"
            "Expected behaviour:\n"
            "- Available seats equal the total seats minus the booked seats.\n\n"
            "Affected file:\n"
            "- backend/app/db/seat_inventory.py (seat_inventory_counts)"
        ),
        target_file="backend/app/db/seat_inventory.py",
        correct='        "available_seats": total - booked,',
        broken='        "available_seats": total + booked,',
    ),
    BugFixture(
        slug="knowledge-get-by-topic-inverted",
        summary="Browsing a knowledge topic returns articles from every other topic",
        description=(
            "Fetching articles for a specific knowledge topic returns all the articles that do "
            "NOT belong to that topic.\n\n"
            "Steps to reproduce:\n"
            "- Request the articles for a topic (e.g. 'baggage')\n"
            "- Observe that the results are from unrelated topics instead\n\n"
            "Expected behaviour:\n"
            "- Only articles whose topic matches the requested topic are returned.\n\n"
            "Affected file:\n"
            "- backend/app/services/knowledge_service.py (get_by_topic)"
        ),
        target_file="backend/app/services/knowledge_service.py",
        correct="                KnowledgeArticle.topic == topic,",
        broken="                KnowledgeArticle.topic != topic,",
    ),
    BugFixture(
        slug="flight-sort-by-price-inverted",
        summary="Sorting flight search by price does not order by price",
        description=(
            "Requesting flight search results sorted by price returns them ordered by departure "
            "time instead, and the default ordering is swapped too.\n\n"
            "Steps to reproduce:\n"
            "- Call GET /flights/search?sort_by=price\n"
            "- Observe the results are not ordered from cheapest to most expensive\n\n"
            "Expected behaviour:\n"
            "- sort_by=price orders results by price; the default orders by departure time.\n\n"
            "Affected file:\n"
            "- backend/app/services/flight_service.py (search_flights)"
        ),
        target_file="backend/app/services/flight_service.py",
        correct='        if sort_by == "price":',
        broken='        if sort_by != "price":',
    ),
    BugFixture(
        slug="flight-destination-case",
        summary="Flight search by destination airport returns no results",
        description=(
            "Searching flights by destination airport always returns an empty list, even for "
            "airports that clearly have flights.\n\n"
            "Steps to reproduce:\n"
            "- Call GET /flights/search?destination=jfk\n"
            "- Observe that no flights are returned although JFK has scheduled flights\n\n"
            "Expected behaviour:\n"
            "- The destination filter matches regardless of the casing of the supplied airport "
            "code (airport codes are stored in upper case).\n\n"
            "Affected file:\n"
            "- backend/app/services/flight_service.py (search_flights)"
        ),
        target_file="backend/app/services/flight_service.py",
        correct="            statement = statement.where(Flight.destination_airport == destination.upper())",
        broken="            statement = statement.where(Flight.destination_airport == destination.lower())",
    ),
    BugFixture(
        slug="booking-create-extras-subtract",
        summary="Paid extras lower the total when included while creating a booking",
        description=(
            "When a new booking is created with paid extras, each extra reduces the total price "
            "instead of adding to it.\n\n"
            "Steps to reproduce:\n"
            "- Create a booking and include a paid extra (e.g. extra baggage)\n"
            "- Observe the booking total is lower than the base fare\n\n"
            "Expected behaviour:\n"
            "- Each extra added at creation increases the booking total by the extra's price.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (create_booking)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="            total_price += extra_price",
        broken="            total_price -= extra_price",
    ),
]


# ---------------------------------------------------------------------------
# Medium-level fixtures
# ---------------------------------------------------------------------------

MEDIUM_BUG_FIXTURES: list[BugFixture] = [
    BugFixture(
        slug="booking-cancel-seat-release-inverted",
        summary="Cancelling a booking does not free up the seat for other passengers",
        description=(
            "When a booking is cancelled the seat remains marked as occupied, so the flight "
            "never regains that capacity and future passengers cannot book it.\n\n"
            "Steps to reproduce:\n"
            "- Create a booking on a flight that has limited seats\n"
            "- Cancel the booking\n"
            "- Observe that the available seat count on the flight has not increased\n\n"
            "Expected behaviour:\n"
            "- Cancelling a booking releases every seat held by that booking, making them "
            "available for new bookings immediately.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (cancel_booking)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="                    inventory.is_booked = False",
        broken="                    inventory.is_booked = True",
    ),
    BugFixture(
        slug="booking-long-haul-threshold-inverted",
        summary="Short-haul flights charge long-haul baggage fees and vice versa",
        description=(
            "The checked-baggage fee is calculated using the wrong haul classification. "
            "Short flights (under 6 hours) are charged the long-haul rate of €70 while "
            "long flights (6 hours or more) are charged the short-haul rate of €35.\n\n"
            "Steps to reproduce:\n"
            "- Add a checked bag extra to a booking on a 3-hour flight with no explicit price\n"
            "- Observe the extra is priced at 70.00 instead of 35.00\n\n"
            "Expected behaviour:\n"
            "- Flights shorter than 6 hours use the short-haul rate (35.00); "
            "flights of 6 hours or longer use the long-haul rate (70.00).\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (_is_long_haul)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="        return duration.total_seconds() >= 6 * 60 * 60",
        broken="        return duration.total_seconds() <= 6 * 60 * 60",
    ),
    BugFixture(
        slug="flight-available-filter-negated",
        summary="Flight search with 'only available' returns fully-booked flights instead",
        description=(
            "The default flight search (only_available=true) returns flights that have no "
            "seats left, while searching with only_available=false hides flights that still "
            "have availability — the filter logic is backwards.\n\n"
            "Steps to reproduce:\n"
            "- Ensure at least one flight is fully booked and at least one has free seats\n"
            "- Call GET /flights/search (only_available defaults to true)\n"
            "- Observe that the fully-booked flight is included in results\n\n"
            "Expected behaviour:\n"
            "- only_available=true excludes any flight where every seat is already booked.\n\n"
            "Affected file:\n"
            "- backend/app/services/flight_service.py (search_flights)"
        ),
        target_file="backend/app/services/flight_service.py",
        correct="        if only_available:",
        broken="        if not only_available:",
    ),
    BugFixture(
        slug="booking-refund-skip-wrong-status",
        summary="Passengers with a pending refund can re-book the same flight",
        description=(
            "After cancelling a booking with a pending refund, the same passenger can "
            "immediately create a new booking on the same flight. The refund conflict check "
            "has its condition inverted — it now allows re-booking when an unresolved refund "
            "IS present, and wrongly blocks passengers whose refund has already been resolved.\n\n"
            "Steps to reproduce:\n"
            "- Create a booking for passenger A on flight F\n"
            "- Cancel that booking with refund_status=pending\n"
            "- Attempt to create a new booking for passenger A on the same flight F\n"
            "- Observe the second booking is created successfully (should be rejected with 409)\n\n"
            "Expected behaviour:\n"
            "- A passenger with an unresolved refund on a flight must not be able to re-book "
            "that same flight until the refund is resolved.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (_ensure_no_duplicate_or_refund_conflicts)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="            if booking.refund_status in UNRESOLVED_REFUND_STATUSES:",
        broken="            if booking.refund_status not in UNRESOLVED_REFUND_STATUSES:",
    ),
    BugFixture(
        slug="booking-reschedule-old-seat-not-freed",
        summary="Rescheduling a booking keeps the original seat occupied on the old flight",
        description=(
            "After rescheduling a booking to a new flight, the seat on the original flight "
            "is not released. It remains marked as booked, permanently reducing that flight's "
            "available capacity.\n\n"
            "Steps to reproduce:\n"
            "- Create a booking on flight A, note the seat number\n"
            "- Reschedule the booking to flight B\n"
            "- Check flight A's seat inventory — the original seat is still marked as booked\n\n"
            "Expected behaviour:\n"
            "- Rescheduling must free every seat on the original flight that was held by the "
            "rescheduled booking.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (reschedule_booking)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="                    current_inventory.is_booked = False",
        broken="                    current_inventory.is_booked = True",
    ),
    BugFixture(
        slug="booking-duplicate-confirmed-check-skipped",
        summary="A passenger can book the same flight twice at the same time",
        description=(
            "The duplicate-booking guard no longer blocks a second booking for the same "
            "passenger when their first booking is still confirmed. The status check that "
            "should trigger a 409 conflict is targeting the wrong booking status.\n\n"
            "Steps to reproduce:\n"
            "- Create booking B1 for passenger A on flight F\n"
            "- Immediately create booking B2 for the same passenger A on the same flight F\n"
            "- Observe that B2 is accepted instead of returning a 409 conflict error\n\n"
            "Expected behaviour:\n"
            "- If a passenger already has a confirmed booking on a flight, any attempt to "
            "create a second booking for them on that same flight must be rejected with a "
            "409 Conflict.\n\n"
            "Affected file:\n"
            "- backend/app/services/booking_service.py (_ensure_no_duplicate_or_refund_conflicts)"
        ),
        target_file="backend/app/services/booking_service.py",
        correct="            if booking.status == BookingStatus.CONFIRMED:\n                identity = next(iter(matching_identities))",
        broken="            if booking.status == BookingStatus.CANCELLED:\n                identity = next(iter(matching_identities))",
    ),
    BugFixture(
        slug="knowledge-search-and-instead-of-or",
        summary="Knowledge base search returns no results for most queries",
        description=(
            "Searching the knowledge base almost always returns an empty list. The search "
            "condition requires the query to appear in the topic, title, AND content fields "
            "simultaneously, so only articles where all three fields contain the exact keyword "
            "are returned.\n\n"
            "Steps to reproduce:\n"
            "- Search for a keyword that appears only in the title of an article\n"
            "- Observe that the article is not returned even though it is a clear match\n\n"
            "Expected behaviour:\n"
            "- A search result is returned if the query appears in ANY ONE of the topic, "
            "title, or content fields.\n\n"
            "Affected file:\n"
            "- backend/app/services/knowledge_service.py (search)"
        ),
        target_file="backend/app/services/knowledge_service.py",
        correct="            or_(",
        broken="            and_(",
    ),
    BugFixture(
        slug="flight-search-excludes-scheduled",
        summary="Flight search returns cancelled flights instead of scheduled ones",
        description=(
            "The flight search endpoint returns flights that are NOT in scheduled status "
            "(i.e. cancelled or delayed) and omits all scheduled flights. Customers see no "
            "bookable flights.\n\n"
            "Steps to reproduce:\n"
            "- Ensure the database has both scheduled and cancelled flights\n"
            "- Call GET /flights/search\n"
            "- Observe that scheduled flights are absent and cancelled flights appear\n\n"
            "Expected behaviour:\n"
            "- Flight search returns only flights with SCHEDULED status.\n\n"
            "Affected file:\n"
            "- backend/app/services/flight_service.py (search_flights)"
        ),
        target_file="backend/app/services/flight_service.py",
        correct="        statement: Select[tuple[Flight]] = select(Flight).where(Flight.status == FlightStatus.SCHEDULED)",
        broken="        statement: Select[tuple[Flight]] = select(Flight).where(Flight.status != FlightStatus.SCHEDULED)",
    ),
    BugFixture(
        slug="seat-type-business-window-column",
        summary="Business class window-seat preference assigns middle seats instead of window seats",
        description=(
            "In the business cabin the seat-type classification is wrong: column D seats are "
            "labelled 'standard' instead of 'window', and column C seats are labelled 'window' "
            "instead of 'aisle'. Passengers who select a window preference in business class "
            "receive a centre seat.\n\n"
            "Steps to reproduce:\n"
            "- Book a business-class flight and request a window seat preference\n"
            "- Observe the assigned seat is in column C (centre) not column D (window)\n\n"
            "Expected behaviour:\n"
            "- In the business cabin columns A and D are window seats; columns B and C are "
            "aisle seats.\n\n"
            "Affected file:\n"
            "- backend/app/db/seat_inventory.py (_seat_type_for)"
        ),
        target_file="backend/app/db/seat_inventory.py",
        correct='        if column in {"A", "D"}:',
        broken='        if column in {"A", "C"}:',
    ),
    BugFixture(
        slug="seat-inventory-economy-window-column-a",
        summary="Economy class column A seats are not classified as window seats",
        description=(
            "In economy (and premium economy) cabins, column A seats are incorrectly "
            "classified as 'standard' instead of 'window'. Passengers requesting a window "
            "preference are not assigned A-column seats, and the window-seat availability "
            "count is understated.\n\n"
            "Steps to reproduce:\n"
            "- Generate seat inventory for an economy flight\n"
            "- Inspect the seat_type for a seat in column A (e.g. 10A)\n"
            "- Observe the type is 'standard' instead of 'window'\n\n"
            "Expected behaviour:\n"
            "- In economy and premium_economy cabins, columns A and F are window seats.\n\n"
            "Affected file:\n"
            "- backend/app/db/seat_inventory.py (_seat_type_for)"
        ),
        target_file="backend/app/db/seat_inventory.py",
        correct='    if column in {"A", "F"}:',
        broken='    if column in {"B", "F"}:',
    ),
]


ALL_BUG_FIXTURES: list[BugFixture] = BUG_FIXTURES + MEDIUM_BUG_FIXTURES


def get_fixture(slug: str) -> BugFixture:
    for fixture in ALL_BUG_FIXTURES:
        if fixture.slug == slug:
            return fixture
    available = ", ".join(f.slug for f in ALL_BUG_FIXTURES)
    raise KeyError(f"Unknown bug fixture '{slug}'. Available: {available}")
