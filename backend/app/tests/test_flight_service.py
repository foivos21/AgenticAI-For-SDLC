from __future__ import annotations

from datetime import datetime

from app.models.flight import Flight, FlightStatus, SeatClass, SeatPreference
from app.models.seat_inventory import SeatInventory
from app.services.flight_service import FlightService


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _SessionStub:
    def __init__(self, flights):
        self.flights = flights
        self.last_statement = None

    def scalars(self, statement):
        self.last_statement = statement
        return _ScalarResult(self.flights)

    def get(self, model, key):
        return None


def _make_flight(*, flight_id: int, origin: str = "ATH", destination: str = "LHR", departure_time: datetime | None = None) -> Flight:
    return Flight(
        id=flight_id,
        flight_number=f"FL{flight_id:03d}",
        origin_airport=origin,
        destination_airport=destination,
        departure_time=departure_time or datetime(2026, 6, 10, 12, 0, 0),
        arrival_time=(departure_time or datetime(2026, 6, 10, 12, 0, 0)),
        price=120.0,
        status=FlightStatus.SCHEDULED,
        seat_class=SeatClass.ECONOMY,
    )


def test_search_flights_normalizes_lowercase_origin_input():
    flights = [_make_flight(flight_id=1, origin="ATH")]
    session = _SessionStub(flights)
    service = FlightService(session)

    service.search_flights(origin="ath")

    assert session.last_statement is not None
    assert str(session.last_statement).upper().find("ATH") != -1


def test_search_flights_normalizes_mixed_case_origin_input():
    flights = [_make_flight(flight_id=1, origin="ATH")]
    session = _SessionStub(flights)
    service = FlightService(session)

    service.search_flights(origin="AtH")

    assert session.last_statement is not None
    assert str(session.last_statement).upper().find("ATH") != -1


def test_search_flights_preserves_uppercase_origin_input():
    flights = [_make_flight(flight_id=1, origin="ATH")]
    session = _SessionStub(flights)
    service = FlightService(session)

    service.search_flights(origin="ATH")

    assert session.last_statement is not None
    assert str(session.last_statement).upper().find("ATH") != -1
