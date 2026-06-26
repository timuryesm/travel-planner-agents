"""Initial schema — users, trips, stops, trip_stage_commits, stop_stage_commits

Revision ID: 0001
Revises:
Create Date: 2026-06-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── trips ──────────────────────────────────────────────────────────────────
    op.create_table(
        "trips",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="in_progress",
        ),
        # Two-part wizard position.
        # current_stop_index is NULL when current_stage is a trip-level stage.
        sa.Column(
            "current_stage",
            sa.String(32),
            nullable=False,
            server_default="setup",
        ),
        sa.Column("current_stop_index", sa.Integer(), nullable=True),
        # Denorm from setup commit; avoids JSONB extraction for list views.
        sa.Column(
            "multi_city",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'reconciling', 'complete', 'abandoned')",
            name="chk_trip_status",
        ),
    )
    op.create_index("ix_trips_user_id", "trips", ["user_id"])

    # ── stops ──────────────────────────────────────────────────────────────────
    # Created when destination is committed; deleted by CASCADE when a trip is
    # deleted or when destination is cascade-invalidated and re-committed.
    op.create_table(
        "stops",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trip_id",
            UUID(as_uuid=True),
            sa.ForeignKey("trips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stop_index", sa.Integer(), nullable=False),
        sa.Column("city", sa.String(200), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("trip_id", "stop_index", name="uq_stop_trip_index"),
    )
    op.create_index("ix_stops_trip_id", "stops", ["trip_id"])

    # ── trip_stage_commits ─────────────────────────────────────────────────────
    # Four rows inserted per trip at creation time (one per TripLevelStage),
    # all initialised to commit_type='unvisited', completed=false.
    op.create_table(
        "trip_stage_commits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trip_id",
            UUID(as_uuid=True),
            sa.ForeignKey("trips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column(
            "commit_type",
            sa.String(32),
            nullable=False,
            server_default="unvisited",
        ),
        # JSONB payload. Schema: SetupCommitData | DestinationCommitData | null.
        # Null for reconciliation and final (position-marker stages only).
        sa.Column("commit_data", JSONB(), nullable=True),
        # Non-null only when commit_type = 'self_provided'.
        sa.Column("self_provided_text", sa.Text(), nullable=True),
        # Explicitly stored (not derived) for fast reconciliation scans.
        sa.Column(
            "completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("trip_id", "stage", name="uq_trip_stage"),
        sa.CheckConstraint(
            "stage IN ('setup', 'destination', 'reconciliation', 'final')",
            name="chk_trip_stage_name",
        ),
        sa.CheckConstraint(
            "commit_type IN ('chosen', 'self_provided', 'skipped', 'unvisited')",
            name="chk_trip_stage_commit_type",
        ),
    )
    op.create_index(
        "ix_trip_stage_commits_trip_id", "trip_stage_commits", ["trip_id"]
    )

    # ── stop_stage_commits ─────────────────────────────────────────────────────
    # Four rows inserted per stop at stop-creation time (one per StopLevelStage),
    # all initialised to commit_type='unvisited', completed=false.
    op.create_table(
        "stop_stage_commits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "stop_id",
            UUID(as_uuid=True),
            sa.ForeignKey("stops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column(
            "commit_type",
            sa.String(32),
            nullable=False,
            server_default="unvisited",
        ),
        # JSONB payload. Schema:
        #   FlightsCommitData       for stage='flights'
        #   AccommodationCommitData for stage='accommodation'
        #   ActivitiesCommitData    for stage='activities'
        #   DailyPlanCommitData     for stage='daily_plan'
        sa.Column("commit_data", JSONB(), nullable=True),
        sa.Column("self_provided_text", sa.Text(), nullable=True),
        sa.Column(
            "completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("stop_id", "stage", name="uq_stop_stage"),
        sa.CheckConstraint(
            "stage IN ('flights', 'accommodation', 'activities', 'daily_plan')",
            name="chk_stop_stage_name",
        ),
        sa.CheckConstraint(
            "commit_type IN ('chosen', 'self_provided', 'skipped', 'unvisited')",
            name="chk_stop_stage_commit_type",
        ),
    )
    op.create_index(
        "ix_stop_stage_commits_stop_id", "stop_stage_commits", ["stop_id"]
    )
    # Partial index for the reconciliation scan: finds all incomplete stop-level
    # stages for a trip without scanning committed rows.
    op.create_index(
        "ix_stop_stage_commits_incomplete",
        "stop_stage_commits",
        ["stop_id"],
        postgresql_where=sa.text("completed = false"),
    )


def downgrade() -> None:
    op.drop_table("stop_stage_commits")
    op.drop_table("trip_stage_commits")
    op.drop_table("stops")
    op.drop_table("trips")
    op.drop_table("users")