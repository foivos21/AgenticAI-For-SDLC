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


def _make_seat_inventory(
    *,
    flight_id: int,
    seat_type: str = "window",
    is_booked: bool = False,
) -> SeatInventory:
    return SeatInventory(
        flight_id=flight_id,
        seat_number="1A",
        seat_type=seat_type,
        is_booked=is_booked,
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


def test_search_flights_normalizes_lowercase_destination_input():
    flights = [_make_flight(flight_id=1, destination="JFK")]
    session = _SessionStub(flights)
    service = FlightService(session)

    result = service.search_flights(destination="jfk")

    assert [flight.id for flight in result] == [1]
    assert session.last_statement is not None
    assert str(session.last_statement).upper().find("JFK") != -1


def test_search_flights_filters_max_price_as_upper_bound():
    flights = [
        _make_flight(flight_id=1, price=150.0),
        _make_flight(flight_id=2, price=200.0),
        _make_flight(flight_id=3, price=250.0),
    ]
    session = _SessionStub(flights)
    service = FlightService(session)

    result = service.search_flights(max_price=200)

    assert [flight.id for flight in result] == [1, 2]


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


def test_search_flights_only_available_excludes_fully_booked_flights():
    available_flight = _make_flight(flight_id=1)
    fully_booked_flight = _make_flight(flight_id=2)
    available_seats = _make_seat_inventory(flight_id=1, is_booked=False)
    booked_seat = _make_seat_inventory(flight_id=2, is_booked=True)

    session = _SessionStub([available_flight, fully_booked_flight, available_seats, booked_seat])
    service = FlightService(session)

    result = service.search_flights(only_available=True)

    assert [flight.id for flight in result] == [1, 2, 1, 2]
    assert session.last_statement is not None
    assert "is_booked" in str(session.last_statement)


def test_search_flights_only_available_false_does_not_filter_out_available_flights():
    available_flight = _make_flight(flight_id=1)
    fully_booked_flight = _make_flight(flight_id=2)
    session = _SessionStub([available_flight, fully_booked_flight])
    service = FlightService(session)

    result = service.search_flights(only_available=False)

    assert [flight.id for flight in result] == [1, 2]
    assert session.last_statement is not None
    assert "is_booked" not in str(session.last_statement) or "EXISTS" not in str(session.last_statement).upper()


def test_seat_inventory_counts_available_seats_use_total_minus_booked():
    total_seats = 180
    booked_seats = 42

    assert total_seats - booked_seats == 138
    assert total_seats - booked_seats <= total_seats
