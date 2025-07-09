"""Progress tracking models."""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.core.database import Base


class ProgressStatus(str, Enum):
    """Progress status for concepts."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MASTERED = "mastered"


class Progress(Base):
    """Overall progress tracking for students."""
    __tablename__ = "progress"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    total_concepts_started = Column(Integer, default=0)
    total_concepts_completed = Column(Integer, default=0)
    total_concepts_mastered = Column(Integer, default=0)
    total_time_spent = Column(Integer, default=0)  # seconds
    average_score = Column(Float, default=0.0)
    last_activity = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    concept_progress = relationship("ConceptProgress", back_populates="student_progress")
    
    __table_args__ = (
        Index("ix_progress_student_activity", "student_id", "last_activity"),
    )


class ConceptProgress(Base):
    """Progress tracking for individual concepts."""
    __tablename__ = "concept_progress"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    concept_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    progress_id = Column(UUID(as_uuid=True), ForeignKey("progress.id"))
    status = Column(String, default=ProgressStatus.NOT_STARTED.value)
    attempts = Column(Integer, default=0)
    best_score = Column(Float, default=0.0)
    last_score = Column(Float, default=0.0)
    time_spent = Column(Integer, default=0)  # seconds
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    mastered_at = Column(DateTime)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    student_progress = relationship("Progress", back_populates="concept_progress")
    
    __table_args__ = (
        UniqueConstraint("student_id", "concept_id"),
        Index("ix_concept_progress_status", "status"),
        Index("ix_concept_progress_student_concept", "student_id", "concept_id"),
    )


class LearningPath(Base):
    """Learning path progress for students."""
    __tablename__ = "learning_paths"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subject = Column(String, nullable=False)
    path_name = Column(String, nullable=False)
    total_concepts = Column(Integer, default=0)
    completed_concepts = Column(Integer, default=0)
    mastered_concepts = Column(Integer, default=0)
    current_concept_id = Column(UUID(as_uuid=True))
    progress_percentage = Column(Float, default=0.0)
    estimated_completion_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_learning_path_student_subject", "student_id", "subject"),
    )