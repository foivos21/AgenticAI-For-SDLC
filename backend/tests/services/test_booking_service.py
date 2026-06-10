from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_extra import BookingExtra, ExtraType
from app.models.flight import Flight, FlightStatus, SeatClass
from app.services.booking_service import BookingService


class DummyBookingAddExtrasRequest:
    def __init__(self, extras: list[object]) -> None:
        self.extras = extras


@pytest.fixture()
def flight_factory(db_session):
    def _create_flight(*, price: Decimal = Decimal("250.00")) -> Flight:
        flight = Flight(
            flight_number="TM123",
            departure_airport_code="JFK",
            arrival_airport_code="LHR",
            departure_time=datetime(2026, 6, 10, 8, 0, tzinfo=UTC),
            arrival_time=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
            status=FlightStatus.SCHEDULED,
            seat_class=SeatClass.ECONOMY,
            price=price,
        )
        db_session.add(flight)
        db_session.flush()
        return flight

    return _create_flight


@pytest.fixture()
def booking_factory(db_session, flight_factory):
    def _create_booking(*, total_price: Decimal = Decimal("250.00")) -> Booking:
        flight = flight_factory()
        booking = Booking(
            booking_reference="TMABCDEFG1",
            flight_id=flight.id,
            contact_name="Test User",
            contact_email="test@example.com",
            contact_phone=None,
            total_price=total_price,
            status=BookingStatus.CONFIRMED,
            refund_status=RefundStatus.NOT_REQUESTED,
        )
        db_session.add(booking)
        db_session.flush()
        return booking

    return _create_booking


def test_add_extras_increases_total_by_single_paid_extra(db_session, booking_factory):
    booking = booking_factory(total_price=Decimal("250.00"))
    service = BookingService(db_session)
    payload = DummyBookingAddExtrasRequest(
        [SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=Decimal("35.00"), description=None)]
    )

    result = service.add_extras(booking.booking_reference, payload)

    assert result.total_price == Decimal("285.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == booking.id).count() == 1
    assert db_session.get(Booking, booking.id).total_price == Decimal("285.00")


def test_add_extras_increases_total_by_combined_prices_for_multiple_extras(db_session, booking_factory):
    booking = booking_factory(total_price=Decimal("250.00"))
    service = BookingService(db_session)
    payload = DummyBookingAddExtrasRequest(
        [
            SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=Decimal("35.00"), description=None),
            SimpleNamespace(extra_type=ExtraType.PET, quantity=1, price=Decimal("90.00"), description=None),
        ]
    )

    result = service.add_extras(booking.booking_reference, payload)

    assert result.total_price == Decimal("375.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == booking.id).count() == 2
    assert db_session.get(Booking, booking.id).total_price == Decimal("375.00")


def test_add_extras_rejects_cancelled_booking(db_session, booking_factory):
    booking = booking_factory(total_price=Decimal("250.00"))
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(UTC)
    booking.cancellation_reason = "Cancelled"
    service = BookingService(db_session)
    payload = DummyBookingAddExtrasRequest(
        [SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=Decimal("35.00"), description=None)]
    )

    with pytest.raises(Exception):
        service.add_extras(booking.booking_reference, payload)
