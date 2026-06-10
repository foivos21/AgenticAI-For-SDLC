from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_extra import BookingExtra, ExtraType
from app.models.booking_passenger import BookingPassenger
from app.models.flight import Flight, FlightStatus, SeatClass
from app.models.seat_inventory import SeatInventory
from app.schemas.booking import BookingCreate
from app.services.booking_service import BookingService


class DummyBookingAddExtrasRequest:
    def __init__(self, extras: list[object]) -> None:
        self.extras = extras


class DummyBookingPassenger:
    def __init__(
        self,
        *,
        first_name: str,
        last_name: str,
        date_of_birth,
        passenger_type: str = "adult",
        seat_preference=None,
        seat_number=None,
        assistance_type=None,
        assistance_notes=None,
        mobility_assistance_required: bool = False,
    ) -> None:
        self.first_name = first_name
        self.last_name = last_name
        self.date_of_birth = date_of_birth
        self.passenger_type = passenger_type
        self.seat_preference = seat_preference
        self.seat_number = seat_number
        self.assistance_type = assistance_type
        self.assistance_notes = assistance_notes
        self.mobility_assistance_required = mobility_assistance_required


class DummyBookingCreate:
    def __init__(self, *, flight_id: int, passengers: list[object], extras: list[object], contact_name: str = "Test User") -> None:
        self.flight_id = flight_id
        self.passengers = passengers
        self.extras = extras
        self.contact_name = contact_name
        self.contact_email = "test@example.com"
        self.contact_phone = None


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


@pytest.fixture()
def bookable_flight_with_seats(db_session, flight_factory):
    flight = flight_factory(price=Decimal("250.00"))
    db_session.add_all(
        [
            SeatInventory(flight_id=flight.id, seat_number="1A", cabin=SeatClass.ECONOMY.value, seat_type="window", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1B", cabin=SeatClass.ECONOMY.value, seat_type="aisle", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1C", cabin=SeatClass.ECONOMY.value, seat_type="window", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1D", cabin=SeatClass.ECONOMY.value, seat_type="aisle", is_booked=False),
        ]
    )
    db_session.flush()
    return flight


@pytest.fixture()
def booking_create_payload_factory(bookable_flight_with_seats):
    def _create_payload(*, extras: list[object] | None = None) -> DummyBookingCreate:
        passengers = [
            DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date()),
        ]
        return DummyBookingCreate(
            flight_id=bookable_flight_with_seats.id,
            passengers=passengers,
            extras=extras or [],
        )

    return _create_payload


def test_create_booking_with_paid_extras_adds_to_total(db_session, booking_create_payload_factory):
    service = BookingService(db_session)
    payload = booking_create_payload_factory(
        extras=[SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=Decimal("35.00"), description=None)]
    )

    result = service.create_booking(payload)

    assert result.total_price == Decimal("285.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == result.id).count() == 1
    assert db_session.query(BookingPassenger).filter(BookingPassenger.booking_id == result.id).count() == 1


def test_create_booking_with_multiple_paid_extras_adds_sum_to_total(db_session, booking_create_payload_factory):
    service = BookingService(db_session)
    payload = booking_create_payload_factory(
        extras=[
            SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=Decimal("35.00"), description=None),
            SimpleNamespace(extra_type=ExtraType.PET, quantity=1, price=Decimal("90.00"), description=None),
        ]
    )

    result = service.create_booking(payload)

    assert result.total_price == Decimal("375.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == result.id).count() == 2


def test_create_booking_without_extras_keeps_base_fare(db_session, booking_create_payload_factory):
    service = BookingService(db_session)
    payload = booking_create_payload_factory(extras=[])

    result = service.create_booking(payload)

    assert result.total_price == Decimal("250.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == result.id).count() == 0


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
