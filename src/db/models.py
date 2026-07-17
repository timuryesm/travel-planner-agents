"""
SQLAlchemy ORM models — the persistence layer for the wizard state machine.

Table layout:
    users              — JWT auth subjects
    trips              — one wizard session per trip
    stops              — one row per city; created when the city stage is committed
    trip_stage_commits — commit wrapper for trip-level stages (setup / country /
                         city / flights / intercity / accommodation /
                         daily_plan / final)
    stop_stage_commits — commit wrapper for stop-level stages (activities)

All PKs are UUIDs. All FKs cascade delete so deleting a trip is a clean sweep.

The lopsided split between the two commit tables is the hub-and-spoke model
showing through: one country, one hub city, optional day-trips out and back.
There is exactly one flight, one hotel and one day-plan per trip, so those are
trip-level. Only "what to do in this city" repeats.

Note on updated_at:
    The onupdate= hook fires only for ORM-driven updates (session.add).
    Bulk UPDATE statements (used by invalidate_after) must set updated_at
    explicitly. This is accepted as a v1 trade-off; a Postgres trigger can
    be added later if strict audit accuracy is required.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.state.enums import CommitType, TripLevelStage, TripStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # RFC 5321 max email length is 320 characters
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    trips: Mapped[list[Trip]] = relationship(
        "Trip", back_populates="user", cascade="all, delete-orphan"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Trip
# ─────────────────────────────────────────────────────────────────────────────

class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Wizard status ─────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TripStatus.in_progress.value
    )

    # ── Wizard position ───────────────────────────────────────────────────────
    # Two-part pointer into the flattened stage sequence.
    #
    #   current_stage = "setup"        current_stop_index = None   → trip-level
    #   current_stage = "flights"      current_stop_index = None   → trip-level
    #   current_stage = "activities"   current_stop_index = 0      → stop-level
    #   current_stage = "activities"   current_stop_index = 2      → stop-level
    #   current_stage = "final"        current_stop_index = None   → trip-level
    #
    # current_stop_index is NULL for every stage except activities — it is the
    # only stage that repeats per city.
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TripLevelStage.setup.value
    )
    current_stop_index: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # ── Denorm ────────────────────────────────────────────────────────────────
    # len(cities) > 1, written when the city commit is saved.
    #
    # Under hub-and-spoke this is no longer a setup question. The user does not
    # declare "this is a multi-city trip" up front; they discover it by pressing
    # "Add another city" at the city stage. So it cannot be known until cities
    # are committed. Lets list/detail queries avoid JSONB extraction.
    multi_city: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="trips")
    stops: Mapped[list[Stop]] = relationship(
        "Stop",
        back_populates="trip",
        order_by="Stop.stop_index",
        cascade="all, delete-orphan",
    )
    trip_stage_commits: Mapped[list[TripStageCommit]] = relationship(
        "TripStageCommit",
        back_populates="trip",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'complete', 'abandoned')",
            name="chk_trip_status",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stop
# ─────────────────────────────────────────────────────────────────────────────

class Stop(Base):
    """
    One row per city chosen at the city stage.

    Stop rows are created when the city commit is written — never before.
    city/country are NOT NULL because by the time we create a Stop row we know
    the city (it comes straight from the CityCommitData).

    stop_index 0 is the HUB: the city you fly into, where the accommodation is,
    and where every day-trip starts and ends. Stops 1..N are spokes — cities
    visited out and back from the hub, with no separate flight or hotel.

    Cascade-invalidate back to country or city deletes Stop rows and their
    StopStageCommit rows via ON DELETE CASCADE, then re-creates them when the
    user commits a new city list.
    """
    __tablename__ = "stops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 0-based position. Single-city trips have exactly one Stop at stop_index=0.
    stop_index: Mapped[int] = mapped_column(Integer, nullable=False)
    city: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── Dates ─────────────────────────────────────────────────────────────────
    # Nullable because the two stop kinds learn their dates at different stages.
    #
    #   hub (stop 0)  — set at stop creation to the setup dates; you are there
    #                   for the whole trip
    #   spokes (1..N) — NULL until the intercity commit, where the user picks
    #                   each day-trip's dates within the trip window
    #
    # NULL means "not chosen yet", never "derive it from the trip". Deriving is
    # precisely what produced identical date ranges for every city under the old
    # design, and it was invisible because the fallback always returned
    # something plausible.
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    trip: Mapped[Trip] = relationship("Trip", back_populates="stops")
    stop_stage_commits: Mapped[list[StopStageCommit]] = relationship(
        "StopStageCommit",
        back_populates="stop",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("trip_id", "stop_index", name="uq_stop_trip_index"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TripStageCommit
# (setup | country | city | flights | intercity | accommodation |
#  daily_plan | final)
# ─────────────────────────────────────────────────────────────────────────────

class TripStageCommit(Base):
    """
    One row per (trip, stage) for trip-level stages.

    SEVEN rows are inserted when a Trip is created — every trip-level stage
    except intercity:

        (trip_id, 'setup', 'unvisited', ...)
        (trip_id, 'country', 'unvisited', ...)
        (trip_id, 'city', 'unvisited', ...)
        (trip_id, 'flights', 'unvisited', ...)
        (trip_id, 'accommodation', 'unvisited', ...)
        (trip_id, 'daily_plan', 'unvisited', ...)
        (trip_id, 'final', 'unvisited', ...)

    intercity is the exception: the city commit creates it when more than one
    city is chosen and deletes it when the user drops back to one — mirroring
    how that same commit creates and deletes Stop rows. A single-city trip has
    no hub-to-spoke leg, and an unvisited intercity row would assert that the
    user skipped a decision they were never offered.

    UNIQUE (trip_id, stage) ensures there is exactly one commit row per stage
    per trip — no append, always upsert-via-update.
    """
    __tablename__ = "trip_stage_commits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    commit_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CommitType.unvisited.value
    )
    # JSONB payload. Deserialise with the matching *CommitData Pydantic schema:
    #   SetupCommitData         for stage='setup'
    #   CountryCommitData       for stage='country'
    #   CityCommitData          for stage='city'
    #   FlightsCommitData       for stage='flights'
    #   IntercityCommitData     for stage='intercity'
    #   AccommodationCommitData for stage='accommodation'
    #   DailyPlanCommitData     for stage='daily_plan'
    #   FinalCommitData         for stage='final'
    #
    # Note that final is data-bearing now, not a position marker: it holds the
    # assembled itinerary and the budget breakdown, so revisiting the stage
    # renders the saved plan instead of paying to regenerate it.
    commit_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    # Populated only when commit_type == 'self_provided'
    self_provided_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True for: chosen | self_provided | skipped
    # False for: unvisited
    # Stored explicitly rather than derived from commit_type, so a scan for gaps
    # is a plain WHERE completed = FALSE. This is what distinguishes a deliberate
    # skip from a stage never reached — the sidebar's status dots read it.
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    trip: Mapped[Trip] = relationship("Trip", back_populates="trip_stage_commits")

    __table_args__ = (
        UniqueConstraint("trip_id", "stage", name="uq_trip_stage"),
        CheckConstraint(
            "stage IN ('setup', 'country', 'city', 'flights', 'intercity', "
            "'accommodation', 'daily_plan', 'final')",
            name="chk_trip_stage_name",
        ),
        CheckConstraint(
            "commit_type IN ('chosen', 'self_provided', 'skipped', 'unvisited')",
            name="chk_trip_stage_commit_type",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# StopStageCommit  (activities)
# ─────────────────────────────────────────────────────────────────────────────

class StopStageCommit(Base):
    """
    One row per (stop, stage) for stop-level stages.

    ONE row is inserted when a Stop is created. activities is the only
    stop-level stage under hub-and-spoke: flights, accommodation and daily_plan
    are all one-per-trip and live on TripStageCommit.

    The table is kept rather than folded into TripStageCommit because the
    (stop_id, stage) shape is what makes activities-per-city expressible, and
    because a future overnight-in-a-spoke feature would put accommodation back
    here.

    UNIQUE (stop_id, stage) — same single-row-per-stage discipline as
    TripStageCommit. The transition function always updates in place.
    """
    __tablename__ = "stop_stage_commits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stops.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    commit_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CommitType.unvisited.value
    )
    # JSONB payload. Deserialise with:
    #   ActivitiesCommitData    for stage='activities'
    commit_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    self_provided_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    stop: Mapped[Stop] = relationship("Stop", back_populates="stop_stage_commits")

    __table_args__ = (
        UniqueConstraint("stop_id", "stage", name="uq_stop_stage"),
        CheckConstraint(
            "stage IN ('activities')",
            name="chk_stop_stage_name",
        ),
        CheckConstraint(
            "commit_type IN ('chosen', 'self_provided', 'skipped', 'unvisited')",
            name="chk_stop_stage_commit_type",
        ),
    )