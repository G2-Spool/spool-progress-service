"""Dashboard data aggregation endpoints."""

from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, case
import structlog

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.progress import Progress, ConceptProgress, ProgressStatus
from app.models.gamification import Points, Badge, UserBadge, Streak
from app.models.analytics import Analytics, LearningMetrics
from app.schemas.dashboard import (
    DashboardOverview, StudentDashboard, InstructorDashboard,
    ClassOverview, ProgressChart, EngagementMetrics
)

logger = structlog.get_logger()
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/student/{student_id}", response_model=StudentDashboard)
async def get_student_dashboard(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive dashboard data for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get overall progress
    progress_result = await db.execute(
        select(Progress).where(Progress.student_id == student_id)
    )
    progress = progress_result.scalar_one_or_none()
    
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    
    # Get points and level
    points_result = await db.execute(
        select(Points).where(Points.student_id == student_id)
    )
    points = points_result.scalar_one_or_none()
    
    # Get current streak
    streak_result = await db.execute(
        select(Streak).where(Streak.student_id == student_id)
    )
    streak = streak_result.scalar_one_or_none()
    
    # Get recent badges
    badges_result = await db.execute(
        select(UserBadge)
        .options(selectinload(UserBadge.badge))
        .where(UserBadge.student_id == student_id)
        .order_by(UserBadge.earned_at.desc())
        .limit(5)
    )
    recent_badges = badges_result.scalars().all()
    
    # Get concept stats
    concept_stats = await db.execute(
        select(
            func.count(ConceptProgress.id).label("total"),
            func.count(case((ConceptProgress.status == ProgressStatus.NOT_STARTED.value, 1))).label("not_started"),
            func.count(case((ConceptProgress.status == ProgressStatus.IN_PROGRESS.value, 1))).label("in_progress"),
            func.count(case((ConceptProgress.status == ProgressStatus.COMPLETED.value, 1))).label("completed"),
            func.count(case((ConceptProgress.status == ProgressStatus.MASTERED.value, 1))).label("mastered")
        ).where(ConceptProgress.student_id == student_id)
    )
    stats = concept_stats.one()
    
    # Get weekly activity
    week_ago = datetime.utcnow() - timedelta(days=7)
    weekly_activity = await db.execute(
        select(
            func.date(ConceptProgress.last_attempted_at).label("date"),
            func.count(ConceptProgress.id).label("concepts_practiced")
        ).where(
            and_(
                ConceptProgress.student_id == student_id,
                ConceptProgress.last_attempted_at >= week_ago
            )
        ).group_by(func.date(ConceptProgress.last_attempted_at))
    )
    
    activity_by_date = {
        str(row.date): row.concepts_practiced
        for row in weekly_activity
    }
    
    # Get next recommended concepts (simplified)
    next_concepts = await db.execute(
        select(ConceptProgress).where(
            and_(
                ConceptProgress.student_id == student_id,
                ConceptProgress.status == ProgressStatus.IN_PROGRESS.value
            )
        ).limit(3)
    )
    
    return {
        "student_id": student_id,
        "overview": {
            "total_concepts": stats.total,
            "mastered_concepts": stats.mastered,
            "completed_concepts": stats.completed,
            "in_progress_concepts": stats.in_progress,
            "mastery_percentage": (stats.mastered / stats.total * 100) if stats.total > 0 else 0
        },
        "gamification": {
            "current_level": points.current_level if points else 1,
            "total_points": points.total_points if points else 0,
            "points_to_next_level": points.points_to_next_level if points else 100,
            "current_streak": streak.current_streak if streak else 0,
            "longest_streak": streak.longest_streak if streak else 0,
            "recent_badges": [
                {
                    "badge_id": str(ub.badge.id),
                    "name": ub.badge.name,
                    "icon_url": ub.badge.icon_url,
                    "earned_at": ub.earned_at
                }
                for ub in recent_badges
            ]
        },
        "weekly_activity": activity_by_date,
        "next_concepts": [
            {
                "concept_id": str(c.concept_id),
                "current_score": c.current_score,
                "attempts": c.attempts
            }
            for c in next_concepts.scalars()
        ],
        "last_updated": datetime.utcnow()
    }


@router.get("/instructor/class/{class_id}", response_model=InstructorDashboard)
async def get_instructor_dashboard(
    class_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get instructor dashboard for a class."""
    # Verify instructor role
    if "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # In production, would verify instructor has access to this class
    
    # Get class students (simplified - would come from class service)
    # For now, get all students with progress
    students_result = await db.execute(
        select(Progress.student_id).distinct()
    )
    student_ids = [row[0] for row in students_result]
    
    # Calculate class averages
    class_stats = await db.execute(
        select(
            func.avg(Progress.overall_progress).label("avg_progress"),
            func.avg(Progress.total_concepts_mastered).label("avg_mastered"),
            func.count(Progress.student_id).label("total_students")
        )
    )
    stats = class_stats.one()
    
    # Get engagement metrics
    engagement = await db.execute(
        select(
            func.count(case((Streak.current_streak > 0, 1))).label("active_students"),
            func.avg(Streak.current_streak).label("avg_streak")
        ).select_from(Streak)
    )
    engagement_stats = engagement.one()
    
    # Get struggling students (low progress or accuracy)
    struggling = await db.execute(
        select(Progress).where(
            Progress.overall_progress < 50
        ).order_by(Progress.overall_progress).limit(5)
    )
    
    # Get top performers
    top_performers = await db.execute(
        select(Progress).order_by(
            Progress.total_concepts_mastered.desc()
        ).limit(5)
    )
    
    # Get concept completion rates
    concept_completion = await db.execute(
        select(
            ConceptProgress.concept_id,
            func.count(case((ConceptProgress.status == ProgressStatus.MASTERED.value, 1))).label("mastered_count"),
            func.count(ConceptProgress.student_id).label("attempted_count")
        ).group_by(ConceptProgress.concept_id)
        .order_by(func.count(ConceptProgress.student_id).desc())
        .limit(10)
    )
    
    return {
        "class_id": class_id,
        "overview": {
            "total_students": stats.total_students,
            "average_progress": float(stats.avg_progress or 0),
            "average_mastery": float(stats.avg_mastered or 0),
            "active_students": engagement_stats.active_students or 0,
            "average_streak": float(engagement_stats.avg_streak or 0)
        },
        "struggling_students": [
            {
                "student_id": str(s.student_id),
                "progress": s.overall_progress,
                "concepts_mastered": s.total_concepts_mastered
            }
            for s in struggling.scalars()
        ],
        "top_performers": [
            {
                "student_id": str(s.student_id),
                "progress": s.overall_progress,
                "concepts_mastered": s.total_concepts_mastered,
                "level": s.current_level
            }
            for s in top_performers.scalars()
        ],
        "concept_stats": [
            {
                "concept_id": str(row.concept_id),
                "mastery_rate": (row.mastered_count / row.attempted_count * 100) if row.attempted_count > 0 else 0,
                "attempted_by": row.attempted_count
            }
            for row in concept_completion
        ],
        "last_updated": datetime.utcnow()
    }


@router.get("/progress-chart/{student_id}", response_model=ProgressChart)
async def get_progress_chart(
    student_id: str,
    days: int = Query(30, ge=7, le=365),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get progress chart data."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    start_date = date.today() - timedelta(days=days)
    
    # Get daily progress data
    daily_progress = await db.execute(
        select(
            Analytics.period_date,
            Analytics.concepts_completed,
            Analytics.concepts_mastered,
            Analytics.points_earned,
            Analytics.time_spent
        ).where(
            and_(
                Analytics.student_id == student_id,
                Analytics.period == "daily",
                Analytics.period_date >= start_date
            )
        ).order_by(Analytics.period_date)
    )
    
    chart_data = []
    cumulative_mastered = 0
    
    for row in daily_progress:
        cumulative_mastered += row.concepts_mastered
        chart_data.append({
            "date": str(row.period_date),
            "concepts_completed": row.concepts_completed,
            "concepts_mastered": row.concepts_mastered,
            "cumulative_mastered": cumulative_mastered,
            "points_earned": row.points_earned,
            "time_spent_minutes": row.time_spent // 60
        })
    
    return {
        "student_id": student_id,
        "period_days": days,
        "data_points": chart_data
    }


@router.get("/engagement-metrics", response_model=EngagementMetrics)
async def get_engagement_metrics(
    timeframe: str = Query("weekly", regex="^(daily|weekly|monthly)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get platform-wide engagement metrics (admin only)."""
    # Only admin can view platform metrics
    if "admin" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Calculate date range
    if timeframe == "daily":
        start_date = date.today()
    elif timeframe == "weekly":
        start_date = date.today() - timedelta(days=7)
    else:  # monthly
        start_date = date.today() - timedelta(days=30)
    
    # Get active users
    active_users = await db.execute(
        select(func.count(func.distinct(ConceptProgress.student_id))).where(
            ConceptProgress.last_attempted_at >= start_date
        )
    )
    active_count = active_users.scalar() or 0
    
    # Get total users
    total_users = await db.execute(
        select(func.count(func.distinct(Progress.student_id)))
    )
    total_count = total_users.scalar() or 0
    
    # Get average session time (simplified)
    avg_time = await db.execute(
        select(func.avg(Analytics.time_spent)).where(
            and_(
                Analytics.period == "daily",
                Analytics.period_date >= start_date
            )
        )
    )
    avg_session_time = (avg_time.scalar() or 0) // 60  # Convert to minutes
    
    # Get completion rates
    completion_stats = await db.execute(
        select(
            func.count(case((ConceptProgress.status == ProgressStatus.COMPLETED.value, 1))).label("completed"),
            func.count(case((ConceptProgress.status == ProgressStatus.MASTERED.value, 1))).label("mastered"),
            func.count(ConceptProgress.id).label("total")
        ).where(
            ConceptProgress.last_attempted_at >= start_date
        )
    )
    completion = completion_stats.one()
    
    return {
        "timeframe": timeframe,
        "active_users": active_count,
        "total_users": total_count,
        "engagement_rate": (active_count / total_count * 100) if total_count > 0 else 0,
        "average_session_minutes": avg_session_time,
        "completion_rate": (completion.completed / completion.total * 100) if completion.total > 0 else 0,
        "mastery_rate": (completion.mastered / completion.total * 100) if completion.total > 0 else 0,
        "generated_at": datetime.utcnow()
    }