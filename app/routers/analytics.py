"""Analytics and reporting endpoints."""

from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
import structlog

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.analytics import Analytics, LearningMetrics, ProgressSnapshot
from app.models.progress import Progress, ConceptProgress, ProgressStatus
from app.schemas.analytics import (
    AnalyticsResponse, LearningMetricsResponse, ProgressSnapshotResponse,
    AnalyticsCreate, MetricsQuery, InsightsResponse
)

logger = structlog.get_logger()
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/{student_id}", response_model=List[AnalyticsResponse])
async def get_student_analytics(
    student_id: str,
    period: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get analytics for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Build query
    query = select(Analytics).where(
        and_(
            Analytics.student_id == student_id,
            Analytics.period == period
        )
    )
    
    # Add date filters
    if start_date:
        query = query.where(Analytics.period_date >= start_date)
    if end_date:
        query = query.where(Analytics.period_date <= end_date)
    else:
        # Default to last 30 days
        query = query.where(Analytics.period_date >= date.today() - timedelta(days=30))
    
    query = query.order_by(Analytics.period_date.desc())
    
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/aggregate", response_model=Dict[str, Any])
async def aggregate_analytics(
    period: str = Query(..., regex="^(daily|weekly|monthly)$"),
    target_date: date = Query(date.today()),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Aggregate analytics for all students (admin only)."""
    # Only system or admin can aggregate
    if "admin" not in current_user.get("roles", []) and "system" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Calculate date range based on period
    if period == "daily":
        start_date = target_date
        end_date = target_date
    elif period == "weekly":
        start_date = target_date - timedelta(days=target_date.weekday())
        end_date = start_date + timedelta(days=6)
    else:  # monthly
        start_date = target_date.replace(day=1)
        next_month = start_date.replace(day=28) + timedelta(days=4)
        end_date = next_month - timedelta(days=next_month.day)
    
    # Get all students with activity in period
    students_query = select(Progress.student_id).distinct()
    students_result = await db.execute(students_query)
    student_ids = [row[0] for row in students_result]
    
    aggregated_count = 0
    
    for student_id in student_ids:
        # Get concept progress stats for period
        concept_stats = await db.execute(
            select(
                func.count(ConceptProgress.id).filter(
                    ConceptProgress.created_at.between(start_date, end_date + timedelta(days=1))
                ).label("started"),
                func.count(ConceptProgress.id).filter(
                    and_(
                        ConceptProgress.status == ProgressStatus.COMPLETED.value,
                        ConceptProgress.completed_at.between(start_date, end_date + timedelta(days=1))
                    )
                ).label("completed"),
                func.count(ConceptProgress.id).filter(
                    and_(
                        ConceptProgress.status == ProgressStatus.MASTERED.value,
                        ConceptProgress.mastered_at.between(start_date, end_date + timedelta(days=1))
                    )
                ).label("mastered"),
                func.avg(ConceptProgress.current_score).label("avg_score")
            ).where(ConceptProgress.student_id == student_id)
        )
        
        stats = concept_stats.one()
        
        # Calculate time spent (simplified - would need session tracking)
        time_spent = await db.execute(
            select(func.sum(ConceptProgress.attempts * 300)).where(  # Assume 5 min per attempt
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.last_attempted_at.between(start_date, end_date + timedelta(days=1))
                )
            )
        )
        total_time = time_spent.scalar() or 0
        
        # Create or update analytics record
        existing = await db.execute(
            select(Analytics).where(
                and_(
                    Analytics.student_id == student_id,
                    Analytics.period == period,
                    Analytics.period_date == target_date
                )
            )
        )
        analytics = existing.scalar_one_or_none()
        
        if analytics:
            # Update existing
            analytics.concepts_started = stats.started
            analytics.concepts_completed = stats.completed
            analytics.concepts_mastered = stats.mastered
            analytics.average_score = stats.avg_score or 0.0
            analytics.time_spent = total_time
        else:
            # Create new
            analytics = Analytics(
                student_id=student_id,
                period=period,
                period_date=target_date,
                concepts_started=stats.started,
                concepts_completed=stats.completed,
                concepts_mastered=stats.mastered,
                average_score=stats.avg_score or 0.0,
                time_spent=total_time
            )
            db.add(analytics)
        
        aggregated_count += 1
    
    await db.commit()
    
    return {
        "period": period,
        "target_date": str(target_date),
        "students_processed": aggregated_count
    }


@router.get("/{student_id}/metrics", response_model=List[LearningMetricsResponse])
async def get_learning_metrics(
    student_id: str,
    metric_type: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed learning metrics."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = select(LearningMetrics).where(LearningMetrics.student_id == student_id)
    
    if metric_type:
        query = query.where(LearningMetrics.metric_type == metric_type)
    if subject:
        query = query.where(LearningMetrics.subject == subject)
    
    query = query.order_by(LearningMetrics.calculated_at.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{student_id}/calculate-metrics", response_model=Dict[str, Any])
async def calculate_metrics(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Calculate current learning metrics for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    metrics_calculated = []
    
    # Calculate learning velocity (concepts per day)
    velocity_result = await db.execute(
        select(
            func.count(ConceptProgress.id) / func.greatest(
                func.extract('day', func.max(ConceptProgress.created_at) - func.min(ConceptProgress.created_at)),
                1
            )
        ).where(
            and_(
                ConceptProgress.student_id == student_id,
                ConceptProgress.status.in_([ProgressStatus.COMPLETED.value, ProgressStatus.MASTERED.value])
            )
        )
    )
    velocity = velocity_result.scalar() or 0.0
    
    velocity_metric = LearningMetrics(
        student_id=student_id,
        metric_type="velocity",
        metric_value=float(velocity),
        metadata={"unit": "concepts_per_day"}
    )
    db.add(velocity_metric)
    metrics_calculated.append("velocity")
    
    # Calculate accuracy (average score)
    accuracy_result = await db.execute(
        select(func.avg(ConceptProgress.current_score)).where(
            and_(
                ConceptProgress.student_id == student_id,
                ConceptProgress.current_score.isnot(None)
            )
        )
    )
    accuracy = accuracy_result.scalar() or 0.0
    
    accuracy_metric = LearningMetrics(
        student_id=student_id,
        metric_type="accuracy",
        metric_value=float(accuracy),
        metadata={"unit": "percentage"}
    )
    db.add(accuracy_metric)
    metrics_calculated.append("accuracy")
    
    # Calculate consistency (active days / total days)
    consistency_result = await db.execute(
        select(
            func.count(func.distinct(func.date(ConceptProgress.last_attempted_at))),
            func.extract('day', func.max(ConceptProgress.last_attempted_at) - func.min(ConceptProgress.created_at))
        ).where(ConceptProgress.student_id == student_id)
    )
    active_days, total_days = consistency_result.one()
    consistency = (active_days / max(total_days or 1, 1)) * 100
    
    consistency_metric = LearningMetrics(
        student_id=student_id,
        metric_type="consistency",
        metric_value=float(consistency),
        metadata={"active_days": active_days, "total_days": total_days}
    )
    db.add(consistency_metric)
    metrics_calculated.append("consistency")
    
    await db.commit()
    
    return {
        "metrics_calculated": metrics_calculated,
        "values": {
            "velocity": velocity,
            "accuracy": accuracy,
            "consistency": consistency
        }
    }


@router.get("/{student_id}/insights", response_model=InsightsResponse)
async def get_learning_insights(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get AI-generated learning insights."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get recent metrics
    metrics_result = await db.execute(
        select(LearningMetrics).where(
            LearningMetrics.student_id == student_id
        ).order_by(LearningMetrics.calculated_at.desc()).limit(10)
    )
    metrics = metrics_result.scalars().all()
    
    # Get recent progress
    progress_result = await db.execute(
        select(ConceptProgress).where(
            ConceptProgress.student_id == student_id
        ).order_by(ConceptProgress.last_attempted_at.desc()).limit(20)
    )
    recent_progress = progress_result.scalars().all()
    
    # Generate insights (simplified - would use AI in production)
    insights = []
    recommendations = []
    
    # Analyze velocity
    velocity_metrics = [m for m in metrics if m.metric_type == "velocity"]
    if velocity_metrics and velocity_metrics[0].metric_value < 1.0:
        insights.append("Your learning pace has slowed down. Try to complete at least one concept per day.")
        recommendations.append("Set a daily learning goal to maintain momentum.")
    
    # Analyze accuracy
    accuracy_metrics = [m for m in metrics if m.metric_type == "accuracy"]
    if accuracy_metrics and accuracy_metrics[0].metric_value < 70:
        insights.append("Your accuracy is below 70%. Consider reviewing concepts before moving forward.")
        recommendations.append("Focus on mastering current concepts before starting new ones.")
    
    # Analyze streaks
    streak_result = await db.execute(
        select(Streak).where(Streak.student_id == student_id)
    )
    streak = streak_result.scalar_one_or_none()
    
    if streak and streak.current_streak > 7:
        insights.append(f"Great job! You're on a {streak.current_streak}-day learning streak!")
    elif not streak or streak.current_streak == 0:
        recommendations.append("Start a learning streak by studying every day.")
    
    # Identify struggling areas
    struggling_concepts = [
        p for p in recent_progress 
        if p.attempts > 3 and p.current_score < 70
    ]
    if struggling_concepts:
        insights.append(f"You're struggling with {len(struggling_concepts)} concepts. Consider getting help.")
        recommendations.append("Reach out to an instructor for help with difficult concepts.")
    
    return {
        "insights": insights,
        "recommendations": recommendations,
        "strengths": ["Consistency", "Problem-solving"] if streak and streak.current_streak > 3 else [],
        "areas_for_improvement": ["Speed", "Accuracy"] if accuracy_metrics and accuracy_metrics[0].metric_value < 80 else [],
        "generated_at": datetime.utcnow()
    }


@router.get("/{student_id}/snapshot", response_model=ProgressSnapshotResponse)
async def get_progress_snapshot(
    student_id: str,
    snapshot_date: date = Query(date.today()),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get or create progress snapshot."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check for existing snapshot
    result = await db.execute(
        select(ProgressSnapshot).where(
            and_(
                ProgressSnapshot.student_id == student_id,
                ProgressSnapshot.snapshot_date == snapshot_date
            )
        )
    )
    snapshot = result.scalar_one_or_none()
    
    if not snapshot:
        # Create new snapshot
        # Get concept counts
        total_result = await db.execute(
            select(func.count(ConceptProgress.id)).where(
                ConceptProgress.student_id == student_id
            )
        )
        total_concepts = total_result.scalar() or 0
        
        mastered_result = await db.execute(
            select(func.count(ConceptProgress.id)).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.status == ProgressStatus.MASTERED.value
                )
            )
        )
        mastered_concepts = mastered_result.scalar() or 0
        
        in_progress_result = await db.execute(
            select(func.count(ConceptProgress.id)).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.status == ProgressStatus.IN_PROGRESS.value
                )
            )
        )
        in_progress_concepts = in_progress_result.scalar() or 0
        
        # Calculate average mastery time
        mastery_time_result = await db.execute(
            select(
                func.avg(
                    func.extract('day', ConceptProgress.mastered_at - ConceptProgress.created_at)
                )
            ).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.mastered_at.isnot(None)
                )
            )
        )
        avg_mastery_time = mastery_time_result.scalar() or 0.0
        
        snapshot = ProgressSnapshot(
            student_id=student_id,
            snapshot_date=snapshot_date,
            total_concepts=total_concepts,
            mastered_concepts=mastered_concepts,
            in_progress_concepts=in_progress_concepts,
            average_mastery_time=float(avg_mastery_time),
            strongest_subjects=["Mathematics", "Science"],  # Would calculate from data
            weakest_subjects=["History"],  # Would calculate from data
            recommendations=["Focus on consistent daily practice", "Review weak areas"]
        )
        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)
    
    return snapshot