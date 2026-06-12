"""Behavioural grading tests for the seat_inventory.py fake issues.

Covers: seat-available-count-inflated, seat-type-business-window-column.
"""

from __future__ import annotations

from app.db.seat_inventory import iter_seat_inventory, seat_inventory_counts
from app.models.flight import SeatClass


def test_available_seats_is_total_minus_booked(session, make_flight, add_seats):
    # seat-available-count-inflated
    flight = make_flight(capacity=10)
    add_seats(flight, total=10, booked=4)
    counts = seat_inventory_counts(session, flight.id)
    assert counts["booked_seats"] == 4
    assert counts["available_seats"] == 6


# ---------------------------------------------------------------------------
# Medium-level fixtures
# ---------------------------------------------------------------------------


def test_business_class_column_d_seats_are_window_type(make_flight):
    # seat-type-business-window-column: in business cabin, columns A and D are window seats
    flight = make_flight(seat_class=SeatClass.BUSINESS)
    seats = list(iter_seat_inventory(flight))

    d_seats = [s for s in seats if s.seat_number.endswith("D")]
    assert d_seats, "Expected D-column seats in business cabin"
    assert all(s.seat_type == "window" for s in d_seats), (
        f"Business D-column seats should be 'window', got: "
        f"{[(s.seat_number, s.seat_type) for s in d_seats]}"
    )


def test_economy_column_a_seats_are_window_type(make_flight):
    # seat-inventory-economy-window-column-a: in economy cabin, columns A and F are window seats
    flight = make_flight(seat_class=SeatClass.ECONOMY)
    seats = list(iter_seat_inventory(flight))

    a_seats = [s for s in seats if s.seat_number.endswith("A")]
    assert a_seats, "Expected A-column seats in economy cabin"
    assert all(s.seat_type == "window" for s in a_seats), (
        f"Economy A-column seats should be 'window', got: "
        f"{[(s.seat_number, s.seat_type) for s in a_seats[:3]]}"
    )


def test_business_class_column_c_seats_are_aisle_type(make_flight):
    # seat-type-business-window-column companion: column C should be aisle, not window
    flight = make_flight(seat_class=SeatClass.BUSINESS)
    seats = list(iter_seat_inventory(flight))

    c_seats = [s for s in seats if s.seat_number.endswith("C")]
    assert c_seats, "Expected C-column seats in business cabin"
    assert all(s.seat_type == "aisle" for s in c_seats), (
        f"Business C-column seats should be 'aisle', got: "
        f"{[(s.seat_number, s.seat_type) for s in c_seats]}"
    )
