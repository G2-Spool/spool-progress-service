"""Analytics and reporting models."""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Index, Date, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.core.database import Base


class Analytics(Base):
    """Aggregated analytics for students."""
    __tablename__ = "analytics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    period = Column(String, nullable=False)  # daily, weekly, monthly
    period_date = Column(Date, nullable=False)
    concepts_started = Column(Integer, default=0)
    concepts_completed = Column(Integer, default=0)
    concepts_mastered = Column(Integer, default=0)
    time_spent = Column(Integer, default=0)  # seconds
    average_score = Column(Float, default=0.0)
    points_earned = Column(Integer, default=0)
    badges_earned = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_analytics_student_period", "student_id", "period", "period_date"),
    )


class LearningMetrics(Base):
    """Detailed learning metrics."""
    __tablename__ = "learning_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    metric_type = Column(String, nullable=False)  # velocity, accuracy, consistency
    metric_value = Column(Float, nullable=False)
    subject = Column(String)
    calculated_at = Column(DateTime, default=datetime.utcnow)
    metadata = Column(JSON)  # Additional metric data
    
    __table_args__ = (
        Index("ix_metrics_student_type", "student_id", "metric_type"),
    )


class ProgressSnapshot(Base):
    """Point-in-time progress snapshots."""
    __tablename__ = "progress_snapshots"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False)
    total_concepts = Column(Integer, default=0)
    mastered_concepts = Column(Integer, default=0)
    in_progress_concepts = Column(Integer, default=0)
    average_mastery_time = Column(Float)  # days
    strongest_subjects = Column(JSON)  # Array of subjects
    weakest_subjects = Column(JSON)  # Array of subjects
    recommendations = Column(JSON)  # AI-generated recommendations
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_snapshot_student_date", "student_id", "snapshot_date"),
    )