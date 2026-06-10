"""Behavioural grading tests for the booking_service.py fake issues.

Covers: booking-total-wrong-operator, booking-extras-subtract,
booking-create-extras-subtract.
"""

from __future__ import annotations

from decimal import Decimal

from app.schemas.booking import BookingAddExtrasRequest, BookingCreate, ExtraCreate


def test_base_total_is_price_times_passengers(booking_service, make_flight, add_seats, passenger):
    # booking-total-wrong-operator: 200.00 * 3 passengers == 600.00
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    payload = BookingCreate(
        flight_id=flight.id,
        contact_name="Org Buyer",
        contact_email="buyer@example.com",
        passengers=[
            passenger("Ada", "Lovelace"),
            passenger("Alan", "Turing"),
            passenger("Grace", "Hopper"),
        ],
    )
    booking = booking_service.create_booking(payload)
    assert booking.total_price == Decimal("600.00")


def test_extras_added_at_creation_increase_total(booking_service, make_flight, add_seats, passenger):
    # booking-create-extras-subtract: 200.00 + 50.00 extra == 250.00
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    payload = BookingCreate(
        flight_id=flight.id,
        contact_name="Org Buyer",
        contact_email="buyer@example.com",
        passengers=[passenger("Ada", "Lovelace")],
        extras=[ExtraCreate(extra_type="checked_bag", price=Decimal("50.00"))],
    )
    booking = booking_service.create_booking(payload)
    assert booking.total_price == Decimal("250.00")


def test_adding_extras_later_increases_total(booking_service, make_flight, add_seats, passenger):
    # booking-extras-subtract: 200.00 then +50.00 extra == 250.00
    flight = make_flight(price="200.00", capacity=10)
    add_seats(flight, total=6)
    created = booking_service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Org Buyer",
            contact_email="buyer@example.com",
            passengers=[passenger("Ada", "Lovelace")],
        )
    )
    assert created.total_price == Decimal("200.00")
    updated = booking_service.add_extras(
        created.booking_reference,
        BookingAddExtrasRequest(extras=[ExtraCreate(extra_type="checked_bag", price=Decimal("50.00"))]),
    )
    assert updated.total_price == Decimal("250.00")
