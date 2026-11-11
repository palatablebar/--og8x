"""Version history, DSL write path and backend five-tuple comparison."""
from fastapi import Request
from sqlalchemy.orm import Session

from app.middlewares import audit_logger
from app.models import OwnerTeam, User
from app.schemas.metric import VersionCreate, VersionUpdate
from app.services import metric_service, version_service


def _team(db: Session, team_id: int | None) -> OwnerTeam | None:
    return db.get(OwnerTeam, team_id) if team_id else None


def list_versions(db: Session, metric_id: int) -> dict:
    metric = metric_service.get_metric_or_404(db, metric_id)
    return {
        "metric_id": metric.id,
        "metric_key": metric.metric_key,
        "items": version_service.list_versions(db, metric_id),
    }


def create_version(request: Request, db: Session, user: User, metric_id: int, payload: VersionCreate) -> dict:
    version = version_service.create_version(db, user, metric_id, payload)
    team = _team(db, version.team_id)
    audit_logger.record(
        request,
        "VERSION_CREATED",
        "metric_version",
        version.id,
        after={
            "metric_id": version.metric_id,
            "version_no": version.version_no,
            "agg": version.agg,
            "window": version.window,
            "grain": version.grain,
        },
    )
    return metric_service.serialize_version(version, team)


def update_version(request: Request, db: Session, user: User, version_id: int, payload: VersionUpdate) -> dict:
    version = version_service.get_version_or_404(db, version_id)
    before = {"dsl_text": version.dsl_text, "agg": version.agg, "measure": version.measure}
    version = version_service.update_version(db, user, version, payload.dsl_text)
    team = _team(db, version.team_id)
    audit_logger.record(
        request,
        "VERSION_UPDATED",
        "metric_version",
        version.id,
        before=before,
        after={"dsl_text": version.dsl_text, "agg": version.agg, "measure": version.measure},
    )
    return metric_service.serialize_version(version, team)


def activate_version(request: Request, db: Session, user: User, version_id: int) -> dict:
    """Switch the metric's current version (rollback included); the dependency
    graph and impact surface follow the activated version's stored edges."""
    version = version_service.get_version_or_404(db, version_id)
    before_version = next(
        (
            row
            for row in version_service.versions_for_metric(db, version.metric_id)
            if row.is_current and row.id != version.id
        ),
        None,
    )
    version = version_service.activate_version(db, user, version)
    team = _team(db, version.team_id)
    audit_logger.record(
        request,
        "VERSION_ACTIVATED",
        "metric_version",
        version.id,
        before={"current_version_id": before_version.id if before_version else None},
        after={
            "current_version_id": version.id,
            "version_no": version.version_no,
            "dependencies": list(version.dependencies_json or []),
        },
    )
    return metric_service.serialize_version(version, team)


def compare(db: Session, metric_id: int, version_a_id: int, version_b_id: int) -> dict:
    return version_service.compare_versions(db, metric_id, version_a_id, version_b_id)
