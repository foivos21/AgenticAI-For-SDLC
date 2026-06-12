"""Behavioural grading tests for the flight_service.py fake issues.

Covers: flight-price-filter-inverted, flight-origin-case,
flight-destination-case, flight-sort-by-price-inverted,
flight-available-filter-negated.
"""

from __future__ import annotations

from datetime import datetime, timezone


def test_max_price_filter_returns_only_cheaper_flights(flight_service, make_flight):
    # flight-price-filter-inverted
    cheap = make_flight(price="100.00")
    make_flight(price="300.00")
    results = flight_service.search_flights(max_price=200, only_available=False)
    assert [f.id for f in results] == [cheap.id]


def test_origin_filter_is_case_insensitive(flight_service, make_flight):
    # flight-origin-case
    flight = make_flight(origin="ATH")
    results = flight_service.search_flights(origin="ath", only_available=False)
    assert [f.id for f in results] == [flight.id]


def test_destination_filter_is_case_insensitive(flight_service, make_flight):
    # flight-destination-case
    flight = make_flight(destination="JFK")
    results = flight_service.search_flights(destination="jfk", only_available=False)
    assert [f.id for f in results] == [flight.id]


def test_sort_by_price_orders_cheapest_first(flight_service, make_flight):
    # flight-sort-by-price-inverted D prices intentionally out of order vs time
    make_flight(price="300.00", departure=datetime(2030, 1, 1, 6, 0, tzinfo=timezone.utc))
    make_flight(price="100.00", departure=datetime(2030, 1, 2, 6, 0, tzinfo=timezone.utc))
    make_flight(price="200.00", departure=datetime(2030, 1, 3, 6, 0, tzinfo=timezone.utc))
    results = flight_service.search_flights(sort_by="price", only_available=False)
    prices = [float(f.price) for f in results]
    assert prices == [100.0, 200.0, 300.0]


# ---------------------------------------------------------------------------
# Medium-level fixtures
# ---------------------------------------------------------------------------


def test_search_returns_only_scheduled_flights(flight_service, session, make_flight):
    # flight-search-excludes-scheduled: search must include SCHEDULED flights and
    # exclude CANCELLED ones, not the other way around
    from app.models.flight import FlightStatus

    scheduled = make_flight(price="100.00")
    cancelled = make_flight(price="150.00")
    cancelled.status = FlightStatus.CANCELLED
    session.flush()

    results = flight_service.search_flights(only_available=False)
    result_ids = [f.id for f in results]
    assert scheduled.id in result_ids, "SCHEDULED flight must appear in search results"
    assert cancelled.id not in result_ids, "CANCELLED flight must not appear in search results"


def test_only_available_true_hides_fully_booked_flights(flight_service, make_flight, add_seats):
    # flight-available-filter-negated: only_available=True must exclude flights with no free seats
    available_flight = make_flight(price="100.00")
    booked_flight = make_flight(price="200.00")

    add_seats(available_flight, total=4, booked=3)  # one free seat remains
    add_seats(booked_flight, total=4, booked=4)      # completely full

    results_available = flight_service.search_flights(only_available=True)
    results_all = flight_service.search_flights(only_available=False)

    assert len(results_all) == 2, "only_available=False should return both flights"
    assert len(results_available) == 1, "only_available=True should return only the flight with free seats"
    assert results_available[0].id == available_flight.id
