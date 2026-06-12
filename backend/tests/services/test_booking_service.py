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
    def _create_flight(*, price: Decimal = Decimal("250.00"), duration: timedelta = timedelta(hours=10)) -> Flight:
        departure_time = datetime(2026, 6, 10, 8, 0, tzinfo=UTC)
        flight = Flight(
            flight_number="TM123",
            departure_airport_code="JFK",
            arrival_airport_code="LHR",
            departure_time=departure_time,
            arrival_time=departure_time + duration,
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
    def _create_payload(*, passengers: list[object] | None = None, extras: list[object] | None = None) -> DummyBookingCreate:
        default_passengers = [
            DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date()),
        ]
        return DummyBookingCreate(
            flight_id=bookable_flight_with_seats.id,
            passengers=passengers or default_passengers,
            extras=extras or [],
        )

    return _create_payload


@pytest.fixture()
def cancelled_booking_with_seats(db_session, bookable_flight_with_seats):
    booking = Booking(
        booking_reference="TMSEATREL",
        flight_id=bookable_flight_with_seats.id,
        contact_name="Test User",
        contact_email="test@example.com",
        contact_phone=None,
        total_price=Decimal("500.00"),
        status=BookingStatus.CONFIRMED,
        refund_status=RefundStatus.NOT_REQUESTED,
    )
    db_session.add(booking)
    db_session.flush()

    passenger_one = BookingPassenger(
        booking_id=booking.id,
        first_name="Jane",
        last_name="Doe",
        date_of_birth=datetime(1990, 1, 1).date(),
        passenger_type="adult",
        seat_number="1A",
    )
    passenger_two = BookingPassenger(
        booking_id=booking.id,
        first_name="John",
        last_name="Doe",
        date_of_birth=datetime(1991, 1, 1).date(),
        passenger_type="adult",
        seat_number="1B",
    )
    db_session.add_all([passenger_one, passenger_two])
    db_session.flush()

    db_session.get(SeatInventory, 1).is_booked = True
    db_session.get(SeatInventory, 2).is_booked = True
    db_session.flush()
    return booking


# ... existing tests omitted for brevity in this diff block are preserved unchanged ...

def test_create_booking_rejects_same_passenger_same_flight_when_existing_booking_is_confirmed(db_session, bookable_flight_with_seats):
    service = BookingService(db_session)
    existing_booking = Booking(
        booking_reference="TMDUPCONF1",
        flight_id=bookable_flight_with_seats.id,
        contact_name="Existing User",
        contact_email="existing@example.com",
        contact_phone=None,
        total_price=Decimal("250.00"),
        status=BookingStatus.CONFIRMED,
        refund_status=RefundStatus.NOT_REQUESTED,
    )
    db_session.add(existing_booking)
    db_session.flush()
    db_session.add(
        BookingPassenger(
            booking_id=existing_booking.id,
            first_name="Jane",
            last_name="Doe",
            date_of_birth=datetime(1990, 1, 1).date(),
            passenger_type="adult",
            seat_number="1A",
        )
    )
    db_session.flush()

    payload = DummyBookingCreate(
        flight_id=bookable_flight_with_seats.id,
        passengers=[DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date(), seat_number="1C")],
        extras=[],
    )

    with pytest.raises(Exception) as exc_info:
        service.create_booking(payload)

    assert getattr(exc_info.value, "status_code", None) == 409
    assert "already has a booking on this flight" in str(getattr(exc_info.value, "detail", "")).lower()


def test_create_booking_allows_same_passenger_same_flight_when_no_confirmed_booking_exists(db_session, bookable_flight_with_seats):
    service = BookingService(db_session)
    existing_booking = Booking(
        booking_reference="TMNOCONF1",
        flight_id=bookable_flight_with_seats.id,
        contact_name="Existing User",
        contact_email="existing@example.com",
        contact_phone=None,
        total_price=Decimal("250.00"),
        status=BookingStatus.CANCELLED,
        refund_status=RefundStatus.NOT_REQUESTED,
        cancelled_at=datetime.now(UTC),
        cancellation_reason="Cancelled prior booking",
    )
    db_session.add(existing_booking)
    db_session.flush()
    db_session.add(
        BookingPassenger(
            booking_id=existing_booking.id,
            first_name="Jane",
            last_name="Doe",
            date_of_birth=datetime(1990, 1, 1).date(),
            passenger_type="adult",
            seat_number="1A",
        )
    )
    db_session.flush()

    payload = DummyBookingCreate(
        flight_id=bookable_flight_with_seats.id,
        passengers=[DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date(), seat_number="1C")],
        extras=[],
    )

    result = service.create_booking(payload)

    assert result.status == BookingStatus.CONFIRMED
    assert result.flight_id == bookable_flight_with_seats.id
    assert result.booking_reference != existing_booking.booking_reference


# ... remaining existing tests are preserved unchanged ...
