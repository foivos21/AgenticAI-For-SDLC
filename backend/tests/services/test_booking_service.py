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


def test_create_booking_with_paid_extras_adds_to_total(db_session, booking_create_payload_factory):
    service = BookingService(db_session)
    payload = booking_create_payload_factory(
        extras=[SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=Decimal("35.00"), description=None)]
    )

    result = service.create_booking(payload)

    assert result.total_price == Decimal("285.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == result.id).count() == 1
    assert db_session.query(BookingPassenger).filter(BookingPassenger.booking_id == result.id).count() == 1


def test_create_booking_calculates_base_total_for_single_passenger(db_session, booking_create_payload_factory):
    service = BookingService(db_session)
    payload = booking_create_payload_factory(extras=[])

    result = service.create_booking(payload)

    assert result.total_price == Decimal("250.00")
    assert db_session.query(BookingPassenger).filter(BookingPassenger.booking_id == result.id).count() == 1


def test_create_booking_calculates_base_total_for_multiple_passengers(db_session, booking_create_payload_factory):
    service = BookingService(db_session)
    payload = booking_create_payload_factory(
        passengers=[
            DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date()),
            DummyBookingPassenger(first_name="John", last_name="Doe", date_of_birth=datetime(1991, 1, 1).date()),
            DummyBookingPassenger(first_name="Jill", last_name="Doe", date_of_birth=datetime(1992, 1, 1).date()),
        ],
        extras=[],
    )

    result = service.create_booking(payload)

    assert result.total_price == Decimal("750.00")
    assert db_session.query(BookingPassenger).filter(BookingPassenger.booking_id == result.id).count() == 3


def test_create_booking_without_explicit_checked_bag_price_uses_short_haul_rate_for_under_six_hours(db_session, booking_create_payload_factory, flight_factory):
    flight = flight_factory(duration=timedelta(hours=3))
    db_session.add_all(
        [
            SeatInventory(flight_id=flight.id, seat_number="1A", cabin=SeatClass.ECONOMY.value, seat_type="window", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1B", cabin=SeatClass.ECONOMY.value, seat_type="aisle", is_booked=False),
        ]
    )
    db_session.flush()
    service = BookingService(db_session)
    payload = DummyBookingCreate(
        flight_id=flight.id,
        passengers=[DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date())],
        extras=[SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=None, description=None)],
    )

    result = service.create_booking(payload)

    assert result.total_price == Decimal("285.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == result.id).one().price == Decimal("35.00")


def test_create_booking_without_explicit_checked_bag_price_uses_long_haul_rate_for_six_hours_or_more(db_session, flight_factory):
    flight = flight_factory(duration=timedelta(hours=6))
    db_session.add_all(
        [
            SeatInventory(flight_id=flight.id, seat_number="1A", cabin=SeatClass.ECONOMY.value, seat_type="window", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1B", cabin=SeatClass.ECONOMY.value, seat_type="aisle", is_booked=False),
        ]
    )
    db_session.flush()
    service = BookingService(db_session)
    payload = DummyBookingCreate(
        flight_id=flight.id,
        passengers=[DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date())],
        extras=[SimpleNamespace(extra_type=ExtraType.CHECKED_BAG, quantity=1, price=None, description=None)],
    )

    result = service.create_booking(payload)

    assert result.total_price == Decimal("320.00")
    assert db_session.query(BookingExtra).filter(BookingExtra.booking_id == result.id).one().price == Decimal("70.00")


def test_default_extra_price_helper_respects_six_hour_threshold(db_session, flight_factory):
    service = BookingService(db_session)
    short_flight = flight_factory(duration=timedelta(hours=5, minutes=59))
    long_flight = flight_factory(duration=timedelta(hours=6))

    assert service._is_long_haul(short_flight) is False
    assert service._is_long_haul(long_flight) is True


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


def test_cancelled_booking_with_pending_refund_blocks_rebooking_same_flight(db_session, bookable_flight_with_seats):
    service = BookingService(db_session)
    original_booking = Booking(
        booking_reference="TMPENDING1",
        flight_id=bookable_flight_with_seats.id,
        contact_name="Test User",
        contact_email="test@example.com",
        contact_phone=None,
        total_price=Decimal("250.00"),
        status=BookingStatus.CANCELLED,
        refund_status=RefundStatus.PENDING,
        cancelled_at=datetime.now(UTC),
        cancellation_reason="Customer requested cancellation",
    )
    db_session.add(original_booking)
    db_session.flush()
    db_session.add(
        BookingPassenger(
            booking_id=original_booking.id,
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
        passengers=[DummyBookingPassenger(first_name="Jane", last_name="Doe", date_of_birth=datetime(1990, 1, 1).date())],
        extras=[],
    )

    with pytest.raises(Exception) as exc_info:
        service.create_booking(payload)

    assert getattr(exc_info.value, "status_code", None) == 409
    assert "unresolved refund" in str(getattr(exc_info.value, "detail", "")).lower()


def test_resolved_refund_allows_rebooking_same_flight(db_session, bookable_flight_with_seats):
    service = BookingService(db_session)
    original_booking = Booking(
        booking_reference="TMRESOLVED1",
        flight_id=bookable_flight_with_seats.id,
        contact_name="Test User",
        contact_email="test@example.com",
        contact_phone=None,
        total_price=Decimal("250.00"),
        status=BookingStatus.CANCELLED,
        refund_status=RefundStatus.NOT_REQUESTED,
        cancelled_at=datetime.now(UTC),
        cancellation_reason="Customer requested cancellation",
    )
    db_session.add(original_booking)
    db_session.flush()
    db_session.add(
        BookingPassenger(
            booking_id=original_booking.id,
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


def test_cancel_booking_releases_all_seats_and_restores_flight_availability(db_session, bookable_flight_with_seats):
    passenger_one = BookingPassenger(
        booking_id=1,
        first_name="Jane",
        last_name="Doe",
        date_of_birth=datetime(1990, 1, 1).date(),
        passenger_type="adult",
        seat_number="1A",
    )
    passenger_two = BookingPassenger(
        booking_id=1,
        first_name="John",
        last_name="Doe",
        date_of_birth=datetime(1991, 1, 1).date(),
        passenger_type="adult",
        seat_number="1B",
    )
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
    passenger_one.booking_id = booking.id
    passenger_two.booking_id = booking.id
    db_session.add_all([passenger_one, passenger_two])
    db_session.get(SeatInventory, 1).is_booked = True
    db_session.get(SeatInventory, 2).is_booked = True
    db_session.flush()

    service = BookingService(db_session)
    cancelled = service.cancel_booking(
        booking.booking_reference,
        SimpleNamespace(reason="No longer needed", refund_status=RefundStatus.NOT_REQUESTED, refund_amount=None),
    )

    assert cancelled.status == BookingStatus.CANCELLED
    assert db_session.get(SeatInventory, 1).is_booked is False
    assert db_session.get(SeatInventory, 2).is_booked is False
    assert cancelled.flight.booked_seats == 0
    assert cancelled.flight and cancelled.flight.id == bookable_flight_with_seats.id
    assert db_session.get(Flight, bookable_flight_with_seats.id).booked_seats == 0

    follow_up = DummyBookingCreate(
        flight_id=bookable_flight_with_seats.id,
        passengers=[DummyBookingPassenger(first_name="Alice", last_name="Smith", date_of_birth=datetime(1992, 1, 1).date(), seat_number="1A")],
        extras=[],
    )
    result = service.create_booking(follow_up)
    assert result.status == BookingStatus.CONFIRMED
    assert db_session.get(SeatInventory, 1).is_booked is True
