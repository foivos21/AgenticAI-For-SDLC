"""Behavioural grading tests for the passenger-type-pricing feature.

Covers: passenger-type-pricing (FeatureFixture)

Correct behaviour:
  - Adults  pay 100 % of the flight price.
  - Children (age 2–11 inclusive) pay 75 %.
  - Infants  (age < 2) pay 10 %.
  - passenger_type must be consistent with date_of_birth.
  - Reschedule preserves per-type pricing at the new flight's price.
"""

from __future__ import annotations

import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.schemas.booking import BookingCreate, BookingRescheduleRequest, PassengerCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dob(years_ago: int) -> date:
    """Return a date_of_birth exactly ``years_ago`` years in the past (approx)."""
    return date.today() - timedelta(days=int(years_ago * 365.25))


def _adult_passenger(first: str = "Alice", last: str = "Adult") -> PassengerCreate:
    return PassengerCreate(
        first_name=first,
        last_name=last,
        date_of_birth=_dob(30),
        passenger_type="adult",
    )


def _child_passenger(first: str = "Charlie", last: str = "Child") -> PassengerCreate:
    return PassengerCreate(
        first_name=first,
        last_name=last,
        date_of_birth=_dob(7),
        passenger_type="child",
    )


def _infant_passenger(first: str = "Iris", last: str = "Infant") -> PassengerCreate:
    return PassengerCreate(
        first_name=first,
        last_name=last,
        date_of_birth=_dob(1),
        passenger_type="infant",
    )


def _make_booking(booking_service, flight, *passengers):
    payload = BookingCreate(
        flight_id=flight.id,
        contact_name="Test Contact",
        contact_email="test@example.com",
        passengers=list(passengers),
    )
    return booking_service.create_booking(payload)


# ---------------------------------------------------------------------------
# Pricing: single-passenger baselines
# ---------------------------------------------------------------------------

def test_adult_pays_full_price(booking_service, make_flight, add_seats):
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    booking = _make_booking(booking_service, flight, _adult_passenger())
    assert booking.total_price == Decimal("200.00"), (
        f"Adult should pay 100% of £200.00, got {booking.total_price}"
    )


def test_child_pays_75_percent(booking_service, make_flight, add_seats):
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    booking = _make_booking(booking_service, flight, _child_passenger())
    assert booking.total_price == Decimal("150.00"), (
        f"Child should pay 75% of £200.00 = £150.00, got {booking.total_price}"
    )


def test_infant_pays_10_percent(booking_service, make_flight, add_seats):
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    booking = _make_booking(booking_service, flight, _infant_passenger())
    assert booking.total_price == Decimal("20.00"), (
        f"Infant should pay 10% of £200.00 = £20.00, got {booking.total_price}"
    )


# ---------------------------------------------------------------------------
# Pricing: mixed booking
# ---------------------------------------------------------------------------

def test_mixed_booking_total(booking_service, make_flight, add_seats):
    # 1 adult (£200) + 1 child (£150) + 1 infant (£20) = £370
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    booking = _make_booking(
        booking_service,
        flight,
        _adult_passenger("Alice", "Smith"),
        _child_passenger("Bob", "Smith"),
        _infant_passenger("Iris", "Smith"),
    )
    assert booking.total_price == Decimal("370.00"), (
        f"Mixed booking (adult+child+infant) on £200 flight should total £370.00, "
        f"got {booking.total_price}"
    )


def test_multiple_adults_total(booking_service, make_flight, add_seats):
    flight = make_flight(price="150.00", capacity=10)
    add_seats(flight, total=6)
    booking = _make_booking(
        booking_service,
        flight,
        _adult_passenger("A", "One"),
        _adult_passenger("B", "Two"),
        _adult_passenger("C", "Three"),
    )
    assert booking.total_price == Decimal("450.00"), (
        f"3 adults on £150 flight should total £450.00, got {booking.total_price}"
    )


# ---------------------------------------------------------------------------
# Age-type consistency validation
# ---------------------------------------------------------------------------

def test_infant_type_rejected_when_passenger_is_too_old(booking_service, make_flight, add_seats):
    """A 3-year-old submitted as 'infant' (must be under 2) should be rejected."""
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    with pytest.raises(Exception):
        _make_booking(
            booking_service,
            flight,
            PassengerCreate(
                first_name="Old",
                last_name="Baby",
                date_of_birth=_dob(3),
                passenger_type="infant",
            ),
        )


def test_child_type_rejected_when_passenger_is_too_old(booking_service, make_flight, add_seats):
    """A 13-year-old submitted as 'child' (must be under 12) should be rejected."""
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    with pytest.raises(Exception):
        _make_booking(
            booking_service,
            flight,
            PassengerCreate(
                first_name="Teen",
                last_name="Ager",
                date_of_birth=_dob(13),
                passenger_type="child",
            ),
        )


def test_child_type_rejected_when_passenger_is_too_young(booking_service, make_flight, add_seats):
    """A 1-year-old submitted as 'child' (must be at least 2) should be rejected."""
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    with pytest.raises(Exception):
        _make_booking(
            booking_service,
            flight,
            PassengerCreate(
                first_name="Tiny",
                last_name="Toddler",
                date_of_birth=_dob(1),
                passenger_type="child",
            ),
        )


def test_adult_type_rejected_when_passenger_is_too_young(booking_service, make_flight, add_seats):
    """A 10-year-old submitted as 'adult' (must be at least 12) should be rejected."""
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    with pytest.raises(Exception):
        _make_booking(
            booking_service,
            flight,
            PassengerCreate(
                first_name="Young",
                last_name="Kid",
                date_of_birth=_dob(10),
                passenger_type="adult",
            ),
        )


def test_unknown_passenger_type_rejected():
    """Unrecognised passenger_type values should be rejected at schema level."""
    with pytest.raises(Exception):
        PassengerCreate(
            first_name="X",
            last_name="Y",
            date_of_birth=_dob(30),
            passenger_type="spaceman",
        )


# ---------------------------------------------------------------------------
# Reschedule: per-type pricing on the new flight
# ---------------------------------------------------------------------------

def test_reschedule_applies_per_type_pricing_on_new_flight(
    booking_service, make_flight, add_seats
):
    """
    Rescheduling should price each passenger at their type rate against the
    *new* flight's price, not copy the old totals.

    Setup:  old flight £200 → 1 adult (£200) + 1 child (£150) = £350 total
    Action: reschedule to new flight at £300
    Expect: 1 adult (£300) + 1 child (£225) = £525 total
    """
    old_flight = make_flight(price="200.00", capacity=10)
    add_seats(old_flight, total=6)

    new_flight = make_flight(
        price="300.00",
        capacity=10,
        origin="ATH",
        destination="LHR",
    )
    add_seats(new_flight, total=6)

    original = _make_booking(
        booking_service,
        old_flight,
        _adult_passenger("Alice", "Smith"),
        _child_passenger("Bob", "Smith"),
    )
    assert original.total_price == Decimal("350.00")

    rescheduled = booking_service.reschedule_booking(
        original.booking_reference,
        BookingRescheduleRequest(new_flight_id=new_flight.id),
    )
    assert rescheduled.total_price == Decimal("525.00"), (
        f"Rescheduled booking (adult+child) on £300 flight should total £525.00, "
        f"got {rescheduled.total_price}"
    )
