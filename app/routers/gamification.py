"""Gamification endpoints."""

from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
import structlog

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.gamification import Points, PointHistory, Badge, UserBadge, Streak, Achievement
from app.schemas.gamification import (
    PointsResponse, PointHistoryResponse, BadgeResponse, UserBadgeResponse,
    StreakResponse, AchievementCreate, AchievementResponse, LeaderboardEntry
)
from app.gamification.points_engine import PointsEngine
from app.gamification.badge_engine import BadgeEngine

logger = structlog.get_logger()
router = APIRouter(prefix="/gamification", tags=["gamification"])


@router.get("/points/{student_id}", response_model=PointsResponse)
async def get_student_points(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get points for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(
        select(Points).where(Points.student_id == student_id)
    )
    points = result.scalar_one_or_none()
    
    if not points:
        # Create default points record
        points = Points(student_id=student_id)
        db.add(points)
        await db.commit()
        await db.refresh(points)
    
    return points


@router.post("/points/award", response_model=Dict[str, Any])
async def award_points(
    student_id: str,
    points: int,
    reason: str,
    concept_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Award points to a student."""
    # Only instructors or system can award points
    if "instructor" not in current_user.get("roles", []) and "system" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized to award points")
    
    engine = PointsEngine(db)
    result = await engine.award_points(student_id, points, reason, concept_id)
    
    # Check for badge eligibility
    badge_engine = BadgeEngine(db)
    earned_badges = await badge_engine.check_and_award_badges(
        student_id,
        "points_awarded",
        {"points": points, "total_points": result["total_points"]}
    )
    
    result["earned_badges"] = earned_badges
    return result


@router.get("/points/{student_id}/history", response_model=List[PointHistoryResponse])
async def get_point_history(
    student_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get point history for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(
        select(PointHistory)
        .where(PointHistory.student_id == student_id)
        .order_by(PointHistory.awarded_at.desc())
        .offset(offset)
        .limit(limit)
    )
    
    return result.scalars().all()


@router.get("/badges", response_model=List[BadgeResponse])
async def get_all_badges(
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get all available badges."""
    query = select(Badge).where(Badge.is_active == True)
    
    if category:
        query = query.where(Badge.category == category)
    
    result = await db.execute(query.order_by(Badge.points_value))
    return result.scalars().all()


@router.get("/badges/{student_id}", response_model=List[UserBadgeResponse])
async def get_student_badges(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get badges earned by a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(
        select(UserBadge)
        .options(selectinload(UserBadge.badge))
        .where(UserBadge.student_id == student_id)
        .order_by(UserBadge.earned_at.desc())
    )
    
    return result.scalars().all()


@router.get("/streaks/{student_id}", response_model=StreakResponse)
async def get_student_streak(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get streak information for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(
        select(Streak).where(Streak.student_id == student_id)
    )
    streak = result.scalar_one_or_none()
    
    if not streak:
        # Create default streak record
        streak = Streak(student_id=student_id)
        db.add(streak)
        await db.commit()
        await db.refresh(streak)
    
    # Check if streak needs to be reset
    if streak.last_activity_date and streak.last_activity_date < date.today() - timedelta(days=1):
        # Streak broken
        streak.current_streak = 0
        streak.streak_started_date = None
        await db.commit()
    
    return streak


@router.post("/streaks/{student_id}/update", response_model=StreakResponse)
async def update_streak(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update streak for today's activity."""
    # Verify user is updating their own streak
    if current_user["sub"] != student_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(
        select(Streak).where(Streak.student_id == student_id)
    )
    streak = result.scalar_one_or_none()
    
    if not streak:
        streak = Streak(
            student_id=student_id,
            current_streak=1,
            longest_streak=1,
            streak_started_date=date.today(),
            total_active_days=1
        )
        db.add(streak)
    else:
        # Check if already updated today
        if streak.last_activity_date == date.today():
            return streak
        
        # Check if streak continues
        if streak.last_activity_date == date.today() - timedelta(days=1):
            # Continue streak
            streak.current_streak += 1
            if streak.current_streak > streak.longest_streak:
                streak.longest_streak = streak.current_streak
        else:
            # Start new streak
            streak.current_streak = 1
            streak.streak_started_date = date.today()
        
        streak.last_activity_date = date.today()
        streak.total_active_days += 1
    
    await db.commit()
    await db.refresh(streak)
    
    # Check for streak-related badges
    badge_engine = BadgeEngine(db)
    await badge_engine.check_and_award_badges(
        student_id,
        "daily_streak",
        {"streak_days": streak.current_streak}
    )
    
    return streak


@router.get("/achievements/{student_id}", response_model=List[AchievementResponse])
async def get_student_achievements(
    student_id: str,
    achievement_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get achievements for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = select(Achievement).where(Achievement.student_id == student_id)
    
    if achievement_type:
        query = query.where(Achievement.achievement_type == achievement_type)
    
    query = query.order_by(Achievement.achieved_at.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/achievements", response_model=AchievementResponse)
async def create_achievement(
    achievement: AchievementCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Record a new achievement."""
    # Only system or instructors can create achievements
    if "instructor" not in current_user.get("roles", []) and "system" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    db_achievement = Achievement(**achievement.dict())
    db.add(db_achievement)
    
    try:
        await db.commit()
        await db.refresh(db_achievement)
        return db_achievement
    except Exception as e:
        logger.error("Failed to create achievement", error=str(e))
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create achievement")


@router.get("/leaderboard/points", response_model=List[LeaderboardEntry])
async def get_points_leaderboard(
    timeframe: str = Query("all", regex="^(daily|weekly|monthly|all)$"),
    limit: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get points leaderboard."""
    # Build query based on timeframe
    if timeframe == "all":
        query = select(
            Points.student_id,
            Points.total_points,
            Points.current_level
        ).order_by(Points.total_points.desc())
    else:
        # Calculate points earned in timeframe
        date_filter = datetime.utcnow()
        if timeframe == "daily":
            date_filter = datetime.utcnow() - timedelta(days=1)
        elif timeframe == "weekly":
            date_filter = datetime.utcnow() - timedelta(days=7)
        elif timeframe == "monthly":
            date_filter = datetime.utcnow() - timedelta(days=30)
        
        query = select(
            PointHistory.student_id,
            func.sum(PointHistory.points_awarded).label("total_points"),
            func.max(Points.current_level).label("current_level")
        ).join(
            Points, Points.student_id == PointHistory.student_id
        ).where(
            PointHistory.awarded_at >= date_filter
        ).group_by(
            PointHistory.student_id
        ).order_by(
            func.sum(PointHistory.points_awarded).desc()
        )
    
    query = query.limit(limit)
    result = await db.execute(query)
    
    leaderboard = []
    for idx, row in enumerate(result):
        leaderboard.append({
            "rank": idx + 1,
            "student_id": str(row.student_id),
            "points": row.total_points,
            "level": row.current_level
        })
    
    return leaderboard


@router.get("/leaderboard/streaks", response_model=List[Dict[str, Any]])
async def get_streak_leaderboard(
    limit: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get streak leaderboard."""
    result = await db.execute(
        select(
            Streak.student_id,
            Streak.current_streak,
            Streak.longest_streak,
            Streak.total_active_days
        ).order_by(Streak.current_streak.desc())
        .limit(limit)
    )
    
    leaderboard = []
    for idx, row in enumerate(result):
        leaderboard.append({
            "rank": idx + 1,
            "student_id": str(row.student_id),
            "current_streak": row.current_streak,
            "longest_streak": row.longest_streak,
            "total_active_days": row.total_active_days
        })
    
    return leaderboard