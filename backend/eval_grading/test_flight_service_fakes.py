"""Behavioural grading tests for the flight_service.py fake issues.

Covers: flight-price-filter-inverted, flight-origin-case,
flight-destination-case, flight-sort-by-price-inverted.
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
