"""version-scoped dependencies + idempotent findings

Revision ID: 20261111_0002
Revises: 20261110_0001
Create Date: 2026-11-11

Changes:
  * metric_versions.dependencies_json  — complete `using` key set per version
  * metric_dependencies.version_id     — DSL edges tied to their source version
  * conflict_findings unique (check_id, version_a_id, version_b_id, conflict_type)

Backfill: existing DSL edges (to_metric_id IS NOT NULL) are attached to the
metric's current version, and each version's dependency list is derived from
its stored DSL. The runtime also runs ``Base.metadata.create_all`` so fresh
stacks get the columns directly.

Batch alter is used for portability (native ALTER on MySQL, table rebuild on
SQLite), and the JSON column is added nullable then backfilled before being
made NOT NULL, which is accepted by every MySQL 8 build.
"""
import sqlalchemy as sa
from alembic import op

from app.algorithms.dsl_parser import parse_dsl

revision = "20261111_0002"
down_revision = "20261110_0001"
branch_labels = None
depends_on = None


def _reflect(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), autoload_with=op.get_bind())


def _backfill(bind) -> None:
    versions = _reflect("metric_versions")
    dependencies = _reflect("metric_dependencies")

    # ---- per-version dependency snapshot from the stored DSL + current map ----
    version_rows = bind.execute(
        sa.select(
            versions.c.id, versions.c.metric_id, versions.c.version_no,
            versions.c.is_current, versions.c.dsl_text,
        )
    ).all()
    flagged_current: dict[int, int] = {}
    highest: dict[int, tuple[int, int]] = {}
    snapshot: dict[int, list[str]] = {}
    for vid, metric_id, version_no, is_current, dsl_text in version_rows:
        parsed = parse_dsl(dsl_text or "")
        snapshot[vid] = list(parsed["dependencies"]) if parsed["ok"] else []
        if is_current:
            flagged_current[metric_id] = vid
        if metric_id not in highest or version_no >= highest[metric_id][0]:
            highest[metric_id] = (version_no, vid)

    for vid, keys in snapshot.items():
        bind.execute(versions.update().where(versions.c.id == vid).values(dependencies_json=keys))

    current_version = {
        metric_id: flagged_current.get(metric_id, highest[metric_id][1]) for metric_id in highest
    }

    # ---- attach legacy DSL edges to the current version of their metric ----
    legacy_edges = bind.execute(
        sa.select(dependencies.c.id, dependencies.c.from_metric_id).where(
            dependencies.c.to_metric_id.is_not(None)
        )
    ).all()
    for edge_id, from_metric_id in legacy_edges:
        target_version = current_version.get(from_metric_id)
        if target_version is not None:
            bind.execute(
                dependencies.update()
                .where(dependencies.c.id == edge_id)
                .values(version_id=target_version)
            )

    # ---- de-duplicate findings before adding the unique constraint ----
    findings = _reflect("conflict_findings")
    duplicates = bind.execute(
        sa.select(
            findings.c.check_id,
            findings.c.version_a_id,
            findings.c.version_b_id,
            findings.c.conflict_type,
            sa.func.min(findings.c.id).label("keep_id"),
        )
        .group_by(
            findings.c.check_id,
            findings.c.version_a_id,
            findings.c.version_b_id,
            findings.c.conflict_type,
        )
        .having(sa.func.count() > 1)
    ).all()
    for check_id, va, vb, ctype, keep_id in duplicates:
        bind.execute(
            findings.delete().where(
                sa.and_(
                    findings.c.check_id == check_id,
                    findings.c.version_a_id == va,
                    findings.c.version_b_id == vb,
                    findings.c.conflict_type == ctype,
                    findings.c.id != keep_id,
                )
            )
        )


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("metric_versions", sa.Column("dependencies_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("metric_dependencies") as batch:
        batch.add_column(sa.Column("version_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_metric_dependencies_version_id",
            "metric_versions",
            ["version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_metric_dependencies_version_id", ["version_id"])

    _backfill(bind)

    with op.batch_alter_table("metric_versions") as batch:
        batch.alter_column("dependencies_json", existing_type=sa.JSON(), nullable=False)

    with op.batch_alter_table("conflict_findings") as batch:
        batch.create_unique_constraint(
            "uq_finding_batch_pair_type",
            ["check_id", "version_a_id", "version_b_id", "conflict_type"],
        )


def downgrade() -> None:
    with op.batch_alter_table("conflict_findings") as batch:
        batch.drop_constraint("uq_finding_batch_pair_type", type_="unique")
    with op.batch_alter_table("metric_dependencies") as batch:
        batch.drop_index("ix_metric_dependencies_version_id")
        batch.drop_constraint("fk_metric_dependencies_version_id", type_="foreignkey")
        batch.drop_column("version_id")
    with op.batch_alter_table("metric_versions") as batch:
        batch.drop_column("dependencies_json")
