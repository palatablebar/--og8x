from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base


class MetricDependency(Base):
    """Direction: ``from_metric`` *requires* ``to_metric`` (or the physical table).

    ``version_id`` ties DSL-managed edges to the exact metric version whose
    ``using (...)`` clause declared them. Only edges belonging to the metric's
    *current* version participate in graph/impact projections; switching the
    current version therefore restores the matching dependency set. Physical
    table dependencies keep ``version_id IS NULL`` (manual registration).
    """

    __tablename__ = "metric_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_metric_id: Mapped[int] = mapped_column(
        ForeignKey("metric_definitions.id"), nullable=False, index=True
    )
    to_metric_id: Mapped[int | None] = mapped_column(
        ForeignKey("metric_definitions.id"), nullable=True, index=True
    )
    to_table: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The version snapshot this edge belongs to (NULL for manually-registered table edges).
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("metric_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    relation: Mapped[str] = mapped_column(String(24), nullable=False, default="derive")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    from_metric = relationship(
        "MetricDefinition", back_populates="outgoing_dependencies", foreign_keys=[from_metric_id]
    )
    to_metric = relationship(
        "MetricDefinition", back_populates="incoming_dependencies", foreign_keys=[to_metric_id]
    )
    version = relationship("MetricVersion", back_populates="dependencies", foreign_keys=[version_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MetricDependency {self.from_metric_id}->{self.to_metric_id or self.to_table}>"
