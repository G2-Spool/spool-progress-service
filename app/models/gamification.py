"""Gamification models."""

from datetime import datetime, date
from enum import Enum
from typing import Optional
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, UniqueConstraint, Index, Date, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.core.database import Base


class BadgeCategory(str, Enum):
    """Badge categories."""
    SPEED = "speed"
    CONSISTENCY = "consistency"
    MASTERY = "mastery"
    EXPLORATION = "exploration"
    COLLABORATION = "collaboration"
    MILESTONE = "milestone"


class Points(Base):
    """Points tracking for students."""
    __tablename__ = "points"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    total_points = Column(Integer, default=0)
    current_level = Column(Integer, default=1)
    points_to_next_level = Column(Integer, default=100)
    lifetime_points = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    point_history = relationship("PointHistory", back_populates="student_points")


class PointHistory(Base):
    """History of point awards."""
    __tablename__ = "point_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    points_id = Column(UUID(as_uuid=True), ForeignKey("points.id"))
    points_awarded = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    concept_id = Column(UUID(as_uuid=True))
    awarded_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    student_points = relationship("Points", back_populates="point_history")
    
    __table_args__ = (
        Index("ix_point_history_student_date", "student_id", "awarded_at"),
    )


class Badge(Base):
    """Badge definitions."""
    __tablename__ = "badges"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False)
    category = Column(String, nullable=False)
    icon_url = Column(String)
    points_value = Column(Integer, default=0)
    criteria = Column(JSON, nullable=False)  # JSON criteria for earning
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user_badges = relationship("UserBadge", back_populates="badge")


class UserBadge(Base):
    """Badges earned by users."""
    __tablename__ = "user_badges"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    badge_id = Column(UUID(as_uuid=True), ForeignKey("badges.id"))
    earned_at = Column(DateTime, default=datetime.utcnow)
    progress = Column(Float, default=0.0)  # For progressive badges
    
    # Relationships
    badge = relationship("Badge", back_populates="user_badges")
    
    __table_args__ = (
        UniqueConstraint("student_id", "badge_id"),
        Index("ix_user_badge_earned", "earned_at"),
    )


class Streak(Base):
    """Learning streak tracking."""
    __tablename__ = "streaks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_activity_date = Column(Date, default=date.today)
    streak_started_date = Column(Date)
    total_active_days = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Achievement(Base):
    """Special achievements and milestones."""
    __tablename__ = "achievements"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    achievement_type = Column(String, nullable=False)
    achievement_name = Column(String, nullable=False)
    description = Column(String)
    metadata = Column(JSON)  # Additional achievement data
    achieved_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_achievement_student_type", "student_id", "achievement_type"),
    )