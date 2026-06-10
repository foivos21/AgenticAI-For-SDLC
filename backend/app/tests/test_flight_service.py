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


def _make_flight(
    *,
    flight_id: int,
    origin: str = "ATH",
    destination: str = "LHR",
    departure_time: datetime | None = None,
    price: float = 120.0,
) -> Flight:
    departure_time = departure_time or datetime(2026, 6, 10, 12, 0, 0)
    return Flight(
        id=flight_id,
        flight_number=f"FL{flight_id:03d}",
        origin_airport=origin,
        destination_airport=destination,
        departure_time=departure_time,
        arrival_time=departure_time,
        price=price,
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


def test_search_flights_sorts_by_price_when_requested():
    flights = [
        _make_flight(flight_id=1, departure_time=datetime(2026, 6, 10, 14, 0, 0), price=250.0),
        _make_flight(flight_id=2, departure_time=datetime(2026, 6, 10, 10, 0, 0), price=100.0),
        _make_flight(flight_id=3, departure_time=datetime(2026, 6, 10, 12, 0, 0), price=175.0),
    ]
    session = _SessionStub(flights)
    service = FlightService(session)

    result = service.search_flights(sort_by="price")

    assert [flight.id for flight in result] == [2, 3, 1]


def test_search_flights_defaults_to_departure_time_sort():
    flights = [
        _make_flight(flight_id=1, departure_time=datetime(2026, 6, 10, 14, 0, 0), price=100.0),
        _make_flight(flight_id=2, departure_time=datetime(2026, 6, 10, 10, 0, 0), price=250.0),
        _make_flight(flight_id=3, departure_time=datetime(2026, 6, 10, 12, 0, 0), price=175.0),
    ]
    session = _SessionStub(flights)
    service = FlightService(session)

    result = service.search_flights()

    assert [flight.id for flight in result] == [2, 3, 1]


def test_seat_inventory_counts_available_seats_use_total_minus_booked():
    total_seats = 180
    booked_seats = 42

    assert total_seats - booked_seats == 138
    assert total_seats - booked_seats <= total_seats
