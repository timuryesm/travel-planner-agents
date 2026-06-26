"""
SQLAlchemy ORM models — the persistence layer for the wizard state machine.

Table layout:
    users              — JWT auth subjects
    trips              — one wizard session per trip
    stops              — one row per city; created when destination is committed
    trip_stage_commits — commit wrapper for trip-level stages (setup / destination /
                         reconciliation / final)
    stop_stage_commits — commit wrapper for stop-level stages (flights /
                         accommodation / activities / daily_plan)

All PKs are UUIDs. All FKs cascade delete so deleting a trip is a clean sweep.

Note on updated_at:
    The onupdate= hook fires only for ORM-driven updates (session.add).
    Bulk UPDATE statements (used by invalidate_after) must set updated_at
    explicitly. This is accepted as a v1 trade-off; a Postgres trigger can
    be added later if strict audit accuracy is required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

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
    #   current_stage = "flights"      current_stop_index = 0      → stop-level
    #   current_stage = "daily_plan"   current_stop_index = 2      → stop-level
    #   current_stage = "reconciliation" current_stop_index = None → trip-level
    #
    # current_stop_index is NULL for all trip-level stages
    # (setup, destination, reconciliation, final).
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TripLevelStage.setup.value
    )
    current_stop_index: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # ── Denorm ────────────────────────────────────────────────────────────────
    # Mirrors setup_commit.commit_data["multi_city"].
    # Written when the setup commit is saved; updated if the user goes back to
    # setup and changes it. Lets list/detail queries avoid JSONB extraction.
    multi_city: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

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
            "status IN ('in_progress', 'reconciling', 'complete', 'abandoned')",
            name="chk_trip_status",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stop
# ─────────────────────────────────────────────────────────────────────────────

class Stop(Base):
    """
    One row per city chosen at the destination stage.

    Stop rows are created when the destination commit is written —
    never before. city/country are NOT NULL because by the time we
    create a Stop row we know the city (it comes straight from the
    DestinationCommitData).

    Cascade-invalidate back to destination deletes Stop rows and their
    StopStageCommit rows via ON DELETE CASCADE, then re-creates them
    when the user commits a new destination.
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
    # 0-based position in the multi-city sequence.
    # Single-city trips have exactly one Stop at stop_index=0.
    stop_index: Mapped[int] = mapped_column(Integer, nullable=False)
    city: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

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
# TripStageCommit  (setup | destination | reconciliation | final)
# ─────────────────────────────────────────────────────────────────────────────

class TripStageCommit(Base):
    """
    One row per (trip, stage) for trip-level stages.

    Four rows are inserted when a Trip is created:
        (trip_id, 'setup', 'unvisited', ...)
        (trip_id, 'destination', 'unvisited', ...)
        (trip_id, 'reconciliation', 'unvisited', ...)
        (trip_id, 'final', 'unvisited', ...)

    The transition function updates these rows as the user moves through
    the wizard. commit_data is null for reconciliation and final (they
    are position markers, not data-bearing stages).

    UNIQUE (trip_id, stage) ensures there is exactly one commit row per
    stage per trip — no append, always upsert-via-update.
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
    #   SetupCommitData       for stage='setup'
    #   DestinationCommitData for stage='destination'
    #   null                  for stage='reconciliation' and 'final'
    commit_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    # Populated only when commit_type == 'self_provided'
    self_provided_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True for: chosen | self_provided | skipped
    # False for: unvisited
    # Stored explicitly (not derived) so reconciliation can scan with
    # a simple WHERE completed = FALSE rather than decoding commit_type.
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    trip: Mapped[Trip] = relationship("Trip", back_populates="trip_stage_commits")

    __table_args__ = (
        UniqueConstraint("trip_id", "stage", name="uq_trip_stage"),
        CheckConstraint(
            "stage IN ('setup', 'destination', 'reconciliation', 'final')",
            name="chk_trip_stage_name",
        ),
        CheckConstraint(
            "commit_type IN ('chosen', 'self_provided', 'skipped', 'unvisited')",
            name="chk_trip_stage_commit_type",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# StopStageCommit  (flights | accommodation | activities | daily_plan)
# ─────────────────────────────────────────────────────────────────────────────

class StopStageCommit(Base):
    """
    One row per (stop, stage) for stop-level stages.

    Four rows are inserted when a Stop is created (one per StopLevelStage),
    all initialised to commit_type='unvisited', completed=False.

    UNIQUE (stop_id, stage) — same single-row-per-stage discipline as
    TripStageCommit. The transition function always updates in place.

    Reconciliation query to find stages needing attention:
        SELECT ssc.*
        FROM stop_stage_commits ssc
        JOIN stops s ON s.id = ssc.stop_id
        WHERE s.trip_id = :trip_id
          AND ssc.completed = FALSE          -- NAG_GAPS_ONLY
        -- or:
          AND ssc.commit_type IN ('skipped', 'unvisited')  -- NAG_BOTH
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
    #   FlightsCommitData       for stage='flights'
    #   AccommodationCommitData for stage='accommodation'
    #   ActivitiesCommitData    for stage='activities'
    #   DailyPlanCommitData     for stage='daily_plan'
    commit_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    self_provided_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    stop: Mapped[Stop] = relationship("Stop", back_populates="stop_stage_commits")

    __table_args__ = (
        UniqueConstraint("stop_id", "stage", name="uq_stop_stage"),
        CheckConstraint(
            "stage IN ('flights', 'accommodation', 'activities', 'daily_plan')",
            name="chk_stop_stage_name",
        ),
        CheckConstraint(
            "commit_type IN ('chosen', 'self_provided', 'skipped', 'unvisited')",
            name="chk_stop_stage_commit_type",
        ),
    )