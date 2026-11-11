"""Dependency graph projection + impact closure (downstream consumers).

Projections are built from the *current version* dependency snapshot of every
metric (plus manually-registered physical-table edges), never from stale edges
left behind by older DSL versions.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithms.graph import build_graph, impact_closure
from app.models import MetricDefinition, MetricDependency, MetricVersion, OwnerTeam
from app.services.dependency_version_service import active_dsl_edges, current_version_ids
from app.services.metric_service import get_metric_or_404


def _load(db: Session):
    metrics = db.scalars(select(MetricDefinition).order_by(MetricDefinition.metric_key)).all()
    metric_dicts = [
        {
            "id": metric.id,
            "key": metric.metric_key,
            "name": metric.display_name,
            "domain": metric.domain,
            "status": metric.status,
            "consumers": metric.consumers_json or [],
        }
        for metric in metrics
    ]
    # Active DSL edges belong to each metric's current version; physical-table
    # edges are manual registrations and always remain visible.
    dsl_edges = active_dsl_edges(db)
    table_edges = list(
        db.scalars(
            select(MetricDependency)
            .where(MetricDependency.to_table.is_not(None))
            .order_by(MetricDependency.id)
        ).all()
    )
    version_ids = {edge.version_id for edge in dsl_edges if edge.version_id is not None}
    version_nos: dict[int, int] = {}
    if version_ids:
        for version in db.scalars(select(MetricVersion).where(MetricVersion.id.in_(version_ids))).all():
            version_nos[version.id] = version.version_no

    edge_dicts = [
        {
            "from_id": edge.from_metric_id,
            "to_id": edge.to_metric_id,
            "to_table": edge.to_table,
            "relation": edge.relation,
            "note": edge.note,
            "version_id": edge.version_id,
            "version_no": version_nos.get(edge.version_id) if edge.version_id is not None else None,
        }
        for edge in [*dsl_edges, *table_edges]
    ]
    return metrics, metric_dicts, edge_dicts


def graph_payload(db: Session) -> dict:
    metrics, metric_dicts, edge_dicts = _load(db)
    teams = {team.id: team for team in db.scalars(select(OwnerTeam)).all()}
    graph = build_graph(metric_dicts, [edge for edge in edge_dicts if edge["to_id"]])
    # build_graph only keeps its known edge fields; re-attach version provenance
    # by matching the (from,to) pair so the UI can audit each edge's source.
    provenance = {(edge["from_id"], edge["to_id"]): (edge["version_id"], edge["version_no"])
                  for edge in edge_dicts if edge["to_id"]}
    for edge in graph["edges"]:
        version_id, version_no = provenance.get((edge["from_id"], edge["to_id"]), (None, None))
        edge["version_id"] = version_id
        edge["version_no"] = version_no
    team_of = {metric.metric_key: teams.get(metric.owner_team_id) for metric in metrics}
    for node in graph["nodes"]:
        team = team_of.get(node["key"])
        node["team_code"] = team.code if team else None
        node["team_name"] = team.name if team else None
    table_edges = [edge for edge in edge_dicts if edge.get("to_table")]
    graph["table_edges"] = table_edges
    return graph


def impact_payload(db: Session, metric_id: int) -> dict:
    metric = get_metric_or_404(db, metric_id)
    _metrics, metric_dicts, edge_dicts = _load(db)
    closure = impact_closure(metric_id, metric_dicts, [edge for edge in edge_dicts if edge["to_id"]])
    closure["metric_name"] = metric.display_name
    closure["domain"] = metric.domain
    current_id = current_version_ids(db, [metric_id]).get(metric_id)
    current = db.get(MetricVersion, current_id) if current_id else None
    closure["version_id"] = current.id if current else None
    closure["version_no"] = current.version_no if current else None
    return closure
