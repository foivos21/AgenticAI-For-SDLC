"""Catalog of single-file bug fixtures for the ALMAS evaluation dataset.

Each :class:`BugFixture` describes one easy, self-contained defect injected into
a **real application file**:

* ``target_file`` is the single real file the bug lives in.
* ``correct`` / ``broken`` are an exact, reversible search/replace pair. The
  ``correct`` text is what ships in the repo; injecting the bug swaps it for
  ``broken``, restoring swaps it back.
* ``summary`` / ``description`` become the Jira ticket. The description states
  only the *symptom* and acceptance criteria — it never reveals the fix.

Every bug is a runtime logic error inside a function body, so injecting it never
breaks Python import / app startup. The ``ai_task:<slug>`` label ties each ticket
back to its fixture.
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
        correct="            booking.total_price += extra_price",
        broken="            booking.total_price -= extra_price",
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


def get_fixture(slug: str) -> BugFixture:
    for fixture in BUG_FIXTURES:
        if fixture.slug == slug:
            return fixture
    available = ", ".join(f.slug for f in BUG_FIXTURES)
    raise KeyError(f"Unknown bug fixture '{slug}'. Available: {available}")
