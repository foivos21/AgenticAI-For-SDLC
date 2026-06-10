"""Shared in-memory database + seed factories for the fake-issue behavioural tests.

Each test gets a fresh SQLite database (no disk, no shared state) with all the
real ORM tables created, plus small factory fixtures to seed exactly the rows a
given test needs. The tests then call the real services so a fix is graded by
actual behaviour, not by matching an exact line.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base

# Import every model module so its table registers on Base.metadata.
from app.models import (  # noqa: F401
    booking,
    booking_event,
    booking_extra,
    booking_passenger,
    flight,
    knowledge_article,
    seat_inventory,
)
from app.models.flight import Flight, FlightStatus, SeatClass
from app.models.knowledge_article import KnowledgeArticle
from app.models.seat_inventory import SeatInventory
from app.services.booking_service import BookingService
from app.services.flight_service import FlightService
from app.services.knowledge_service import KnowledgeService


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def flight_service(session):
    return FlightService(session)


@pytest.fixture
def knowledge_service(session):
    return KnowledgeService(session)


@pytest.fixture
def booking_service(session):
    return BookingService(session)


@pytest.fixture
def make_flight(session):
    """Insert a scheduled flight and return it."""

    counter = {"n": 0}

    def _make(
        *,
        origin: str = "ATH",
        destination: str = "JFK",
        price: str = "200.00",
        seat_class: SeatClass = SeatClass.ECONOMY,
        departure: datetime | None = None,
        duration_hours: int = 3,
        capacity: int = 120,
    ) -> Flight:
        counter["n"] += 1
        dep = departure or datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)
        row = Flight(
            flight_number=f"TM{100 + counter['n']}",
            origin_airport=origin,
            destination_airport=destination,
            departure_time=dep,
            arrival_time=dep + timedelta(hours=duration_hours),
            seat_class=seat_class,
            price=Decimal(price),
            capacity=capacity,
            status=FlightStatus.SCHEDULED,
        )
        session.add(row)
        session.flush()
        return row

    return _make


@pytest.fixture
def add_seats(session):
    """Add standard economy seats to a flight; mark the first ``booked`` taken."""

    def _add(flight: Flight, *, total: int = 6, booked: int = 0) -> None:
        for index in range(total):
            session.add(
                SeatInventory(
                    flight_id=flight.id,
                    seat_number=f"{10 + index}A",
                    cabin=flight.seat_class.value,
                    seat_type="standard",
                    is_booked=index < booked,
                )
            )
        session.flush()

    return _add


@pytest.fixture
def make_article(session):
    """Insert a knowledge-base article and return it."""

    def _make(*, topic: str, title: str, content: str) -> KnowledgeArticle:
        row = KnowledgeArticle(topic=topic, title=title, content=content)
        session.add(row)
        session.flush()
        return row

    return _make


@pytest.fixture
def passenger():
    """Build a PassengerCreate payload with sensible defaults."""

    from app.schemas.booking import PassengerCreate

    def _make(first_name: str = "Ada", last_name: str = "Lovelace") -> "PassengerCreate":
        return PassengerCreate(
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date(1990, 1, 1),
            passenger_type="adult",
        )

    return _make
