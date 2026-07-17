"""Hub-and-spoke redesign: stop dates, new stage vocabulary

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-16

Three CHECK constraints hard-code the stage and status vocabularies, so the
hub-and-spoke rename is DDL rather than just a Python enum edit:

    chk_trip_stage_name   destination -> country + city; flights, intercity,
                          accommodation and daily_plan promoted from stop level;
                          reconciliation removed
    chk_stop_stage_name   collapses to activities alone
    chk_trip_status       reconciling removed — the stage it named is gone

ADD CONSTRAINT validates existing rows, so any surviving row with
stage='destination' would fail this migration. All trip data was deleted before
this revision was written. That was deliberate rather than convenient: it was
test data from a design that no longer exists, and no backfill is meaningful —
one 'destination' commit does not split into a 'country' and a 'city' commit
without inventing the country it never recorded.

Also drops ix_stop_stage_commits_incomplete, a partial index built for the
reconciliation scan, which no longer exists.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── stops: per-stop dates ─────────────────────────────────────────────────
    # Nullable because they are filled at two different stages. The hub (stop 0)
    # gets the setup dates when stops are created — you are there for the whole
    # trip. Spokes stay NULL until the intercity commit, where the user picks
    # each day-trip's dates. NULL means "not chosen yet", never "derive it from
    # the trip": deriving is exactly what gave every city in a multi-city trip
    # the same date range under the old design.
    op.add_column("stops", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("stops", sa.Column("end_date", sa.Date(), nullable=True))

    # ── trip_stage_commits: new stage vocabulary ──────────────────────────────
    op.drop_constraint("chk_trip_stage_name", "trip_stage_commits", type_="check")
    op.create_check_constraint(
        "chk_trip_stage_name",
        "trip_stage_commits",
        "stage IN ('setup', 'country', 'city', 'flights', 'intercity', "
        "'accommodation', 'daily_plan', 'final')",
    )

    # ── stop_stage_commits: activities is the only stop-level stage ───────────
    # Under hub-and-spoke there is one flight, one hotel and one day-plan per
    # trip, so all three moved to trip level. What remains per city is what to
    # do while you are there.
    op.drop_constraint("chk_stop_stage_name", "stop_stage_commits", type_="check")
    op.create_check_constraint(
        "chk_stop_stage_name",
        "stop_stage_commits",
        "stage IN ('activities')",
    )

    # ── trips: reconciling status retired ─────────────────────────────────────
    op.drop_constraint("chk_trip_status", "trips", type_="check")
    op.create_check_constraint(
        "chk_trip_status",
        "trips",
        "status IN ('in_progress', 'complete', 'abandoned')",
    )

    # ── drop the reconciliation scan index ────────────────────────────────────
    op.drop_index(
        "ix_stop_stage_commits_incomplete", table_name="stop_stage_commits"
    )


def downgrade() -> None:
    """
    Reverse the schema change.

    This will fail on any database holding rows written under the new
    vocabulary — a commit row with stage='country' violates the restored
    chk_trip_stage_name. That is correct behaviour: the old schema cannot
    represent the new data, and silently discarding it would be worse than
    refusing. Wipe trip data before downgrading.
    """
    op.create_index(
        "ix_stop_stage_commits_incomplete",
        "stop_stage_commits",
        ["stop_id"],
        postgresql_where=sa.text("completed = false"),
    )

    op.drop_constraint("chk_trip_status", "trips", type_="check")
    op.create_check_constraint(
        "chk_trip_status",
        "trips",
        "status IN ('in_progress', 'reconciling', 'complete', 'abandoned')",
    )

    op.drop_constraint("chk_stop_stage_name", "stop_stage_commits", type_="check")
    op.create_check_constraint(
        "chk_stop_stage_name",
        "stop_stage_commits",
        "stage IN ('flights', 'accommodation', 'activities', 'daily_plan')",
    )

    op.drop_constraint("chk_trip_stage_name", "trip_stage_commits", type_="check")
    op.create_check_constraint(
        "chk_trip_stage_name",
        "trip_stage_commits",
        "stage IN ('setup', 'destination', 'reconciliation', 'final')",
    )

    op.drop_column("stops", "end_date")
    op.drop_column("stops", "start_date")