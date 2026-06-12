"""Behavioural grading tests for the booking_service.py fake issues.

Covers: booking-total-wrong-operator, booking-extras-subtract,
booking-create-extras-subtract, booking-cancel-seat-release-inverted,
booking-long-haul-threshold-inverted, booking-refund-skip-wrong-status.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.booking import RefundStatus
from app.models.seat_inventory import SeatInventory
from app.schemas.booking import (
    BookingAddExtrasRequest,
    BookingCancelRequest,
    BookingCreate,
    BookingRescheduleRequest,
    ExtraCreate,
)


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


# ---------------------------------------------------------------------------
# Medium-level fixtures
# ---------------------------------------------------------------------------


def test_cancellation_releases_the_booked_seat(booking_service, session, make_flight, add_seats, passenger):
    # booking-cancel-seat-release-inverted: cancelling a booking must set is_booked=False
    flight = make_flight(price="100.00", capacity=10)
    add_seats(flight, total=6)

    created = booking_service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Test User",
            contact_email="cancel@test.com",
            passengers=[passenger("Ada", "Lovelace")],
        )
    )
    seat_number = created.passengers[0].seat_number
    inv = session.scalar(
        select(SeatInventory).where(
            SeatInventory.flight_id == flight.id,
            SeatInventory.seat_number == seat_number,
        )
    )
    assert inv is not None
    assert inv.is_booked is True, "Seat should be marked booked after creation"

    booking_service.cancel_booking(
        created.booking_reference,
        BookingCancelRequest(reason="test cancellation", refund_status=RefundStatus.NOT_REQUESTED),
    )

    assert inv.is_booked is False, "Seat should be released after cancellation"


def test_short_haul_checked_bag_fee_is_35_and_long_haul_is_70(booking_service, make_flight, add_seats, passenger):
    # booking-long-haul-threshold-inverted: 3-hour flight is short haul ($35), 8-hour is long haul ($70)
    short_flight = make_flight(price="100.00", capacity=10, duration_hours=3)
    long_flight = make_flight(price="100.00", capacity=10, duration_hours=8)
    add_seats(short_flight, total=6)
    add_seats(long_flight, total=6)

    short_booking = booking_service.create_booking(
        BookingCreate(
            flight_id=short_flight.id,
            contact_name="Test",
            contact_email="s@test.com",
            passengers=[passenger("Ada", "Lovelace")],
        )
    )
    long_booking = booking_service.create_booking(
        BookingCreate(
            flight_id=long_flight.id,
            contact_name="Test",
            contact_email="l@test.com",
            passengers=[passenger("Alan", "Turing")],
        )
    )

    # Snapshot prices before the extras call (SQLAlchemy identity map means the same
    # Python object is returned by both create_booking and add_extras).
    short_base = Decimal(short_booking.total_price)
    long_base = Decimal(long_booking.total_price)

    # price=0.00 (default) triggers _resolved_extra_price → _default_extra_price → _is_long_haul
    bag = BookingAddExtrasRequest(extras=[ExtraCreate(extra_type="checked_bag")])
    short_after = booking_service.add_extras(short_booking.booking_reference, bag)
    long_after = booking_service.add_extras(long_booking.booking_reference, bag)

    short_fee = short_after.total_price - short_base
    long_fee = long_after.total_price - long_base

    assert short_fee == Decimal("35.00"), f"Short-haul checked bag should be 35.00, got {short_fee}"
    assert long_fee == Decimal("70.00"), f"Long-haul checked bag should be 70.00, got {long_fee}"


def test_cancelled_booking_with_pending_refund_blocks_rebooking(booking_service, make_flight, add_seats, passenger):
    # booking-refund-skip-wrong-status: a CANCELLED booking with a PENDING refund must
    # still block the same passenger from re-booking on the same flight
    flight = make_flight(price="100.00", capacity=10)
    add_seats(flight, total=20)  # plenty of seats so capacity is never the issue

    ada = passenger("Ada", "Lovelace")

    booking1 = booking_service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Test",
            contact_email="refund@test.com",
            passengers=[ada],
        )
    )
    # Cancel and leave a pending refund
    booking_service.cancel_booking(
        booking1.booking_reference,
        BookingCancelRequest(reason="change of plans"),  # defaults to RefundStatus.PENDING
    )

    # Re-booking the same passenger on the same flight must be rejected (409)
    with pytest.raises(HTTPException) as exc_info:
        booking_service.create_booking(
            BookingCreate(
                flight_id=flight.id,
                contact_name="Test",
                contact_email="refund@test.com",
                passengers=[ada],
            )
        )
    assert exc_info.value.status_code == 409


def test_reschedule_releases_seat_on_original_flight(booking_service, session, make_flight, add_seats, passenger):
    # booking-reschedule-old-seat-not-freed: rescheduling must free the seat on the old flight
    flight1 = make_flight(price="100.00", capacity=10)
    flight2 = make_flight(price="120.00", capacity=10)
    add_seats(flight1, total=6)
    add_seats(flight2, total=6)

    created = booking_service.create_booking(
        BookingCreate(
            flight_id=flight1.id,
            contact_name="Test",
            contact_email="reschedule@test.com",
            passengers=[passenger("Ada", "Lovelace")],
        )
    )
    old_seat = created.passengers[0].seat_number
    inv = session.scalar(
        select(SeatInventory).where(
            SeatInventory.flight_id == flight1.id,
            SeatInventory.seat_number == old_seat,
        )
    )
    assert inv.is_booked is True

    booking_service.reschedule_booking(
        created.booking_reference,
        BookingRescheduleRequest(new_flight_id=flight2.id),
    )

    assert inv.is_booked is False, "Original flight seat must be freed after rescheduling"


def test_confirmed_duplicate_booking_is_rejected(booking_service, make_flight, add_seats, passenger):
    # booking-duplicate-confirmed-check-skipped: a second booking for the same passenger on
    # the same flight must be rejected while the first booking is still confirmed
    flight = make_flight(price="100.00", capacity=10)
    add_seats(flight, total=20)

    ada = passenger("Ada", "Lovelace")
    booking_service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Test",
            contact_email="dup@test.com",
            passengers=[ada],
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        booking_service.create_booking(
            BookingCreate(
                flight_id=flight.id,
                contact_name="Test",
                contact_email="dup@test.com",
                passengers=[ada],
            )
        )
    assert exc_info.value.status_code == 409
