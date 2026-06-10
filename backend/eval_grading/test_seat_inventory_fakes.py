"""Behavioural grading test for the seat_inventory.py fake issue.

Covers: seat-available-count-inflated.
"""

from __future__ import annotations

from app.db.seat_inventory import seat_inventory_counts


def test_available_seats_is_total_minus_booked(session, make_flight, add_seats):
    flight = make_flight(capacity=10)
    add_seats(flight, total=10, booked=4)
    counts = seat_inventory_counts(session, flight.id)
    assert counts["booked_seats"] == 4
    assert counts["available_seats"] == 6
