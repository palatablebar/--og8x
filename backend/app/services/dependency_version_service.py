"""Version-scoped dependency persistence and projection.

Every DSL version carries its *complete* dependency set (the metric keys in its
``using (...)`` clause). Persisting a version replaces that version's edge rows
inside the same transaction, so removed upstreams never linger. Graph and impact
projections only consider edges of each metric's **current** version plus
manually-registered physical-table edges, which makes switching / rolling back a
version restore the matching dependency graph and impact surface.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.constants.error_codes import AppError, ErrorCode
from app.models import MetricDefinition, MetricDependency, MetricVersion


def validate_dependency_targets(db: Session, metric: MetricDefinition, dependency_keys: list[str]) -> dict[str, MetricDefinition]:
    """Resolve every ``using`` key to an existing metric; fail the whole write
    (before any row is touched) if any target is missing."""
    targets: dict[str, MetricDefinition] = {}
    for key in dependency_keys:
        target = db.scalar(select(MetricDefinition).where(MetricDefinition.metric_key == key))
        if target is None:
            raise AppError(
                ErrorCode.DSL_SEMANTIC,
                message=f"using 中引用的指标 `{key}` 不存在",
                detail={"missing_metric": key},
            )
        targets[key] = target
    return targets


def replace_version_dependencies(
    db: Session,
    version: MetricVersion,
    metric: MetricDefinition,
    dependency_keys: list[str],
) -> list[MetricDependency]:
    """Persist the *complete* dependency set of ``version``.

    All previous DSL edges of this version are deleted and the declared keys are
    re-inserted as a single replace operation; keys dropped from the DSL stop
    producing edges. The caller must validate targets beforehand and is
    responsible for committing/rolling back the surrounding transaction.
    """
    targets = validate_dependency_targets(db, metric, dependency_keys)
    ordered_keys = sorted(set(dependency_keys))
    version.dependencies_json = ordered_keys

    db.execute(delete(MetricDependency).where(MetricDependency.version_id == version.id))
    edges: list[MetricDependency] = []
    for key in ordered_keys:
        edge = MetricDependency(
            from_metric_id=metric.id,
            to_metric_id=targets[key].id,
            version_id=version.id,
            relation="dsl",
            note="由 DSL using 子句维护",
        )
        db.add(edge)
        edges.append(edge)
    return edges


def current_version_ids(db: Session, metric_ids: list[int] | None = None) -> dict[int, int]:
    """Map each metric id to its current version id.

    Prefers the explicitly flagged ``is_current`` row and otherwise falls back
    to the highest version number, matching ``serialize_metric`` semantics. The
    two rules are evaluated separately so an explicit current flag is never
    overridden by a merely higher version number (this is what makes a rollback
    stick).
    """
    stmt = select(MetricVersion)
    if metric_ids:
        stmt = stmt.where(MetricVersion.metric_id.in_(metric_ids))
    versions = db.scalars(
        stmt.order_by(MetricVersion.metric_id, MetricVersion.version_no)
    ).all()
    flagged: dict[int, int] = {}
    highest: dict[int, int] = {}
    highest_no: dict[int, int] = {}
    for version in versions:
        if version.is_current:
            flagged[version.metric_id] = version.id
        if version.metric_id not in highest_no or version.version_no >= highest_no[version.metric_id]:
            highest_no[version.metric_id] = version.version_no
            highest[version.metric_id] = version.id
    return {metric_id: flagged.get(metric_id, highest[metric_id]) for metric_id in highest}


def active_dsl_edges(db: Session) -> list[MetricDependency]:
    """DSL metric→metric edges that belong to each metric's current version."""
    edges = db.scalars(
        select(MetricDependency)
        .where(MetricDependency.to_metric_id.is_not(None), MetricDependency.version_id.is_not(None))
        .order_by(MetricDependency.id)
    ).all()
    current_ids = set(current_version_ids(db).values())
    return [edge for edge in edges if edge.version_id in current_ids]


def active_edges_for_metric(db: Session, metric_id: int) -> list[MetricDependency]:
    """Active edges of one metric: current-version DSL edges + manual table edges."""
    current = current_version_ids(db, [metric_id]).get(metric_id)
    rows = db.scalars(
        select(MetricDependency).where(MetricDependency.from_metric_id == metric_id)
    ).all()
    out: list[MetricDependency] = []
    for edge in rows:
        if edge.version_id is None:
            out.append(edge)  # manually registered (physical table) edge
        elif edge.version_id == current:
            out.append(edge)
    return out


def incoming_active_edges(db: Session, metric_id: int) -> list[MetricDependency]:
    """Edges of other metrics' current versions that point at ``metric_id``."""
    edges = db.scalars(
        select(MetricDependency).where(MetricDependency.to_metric_id == metric_id)
    ).all()
    current_ids = set(current_version_ids(db).values())
    return [edge for edge in edges if edge.version_id in current_ids]
