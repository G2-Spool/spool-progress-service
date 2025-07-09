"""Points calculation and awarding engine."""

from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.gamification import Points, PointHistory
from app.core.config import settings

logger = structlog.get_logger()


class PointsEngine:
    """Engine for calculating and awarding points."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def award_points(
        self,
        student_id: str,
        points: int,
        reason: str,
        concept_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Award points to a student."""
        try:
            # Get or create points record
            student_points = await self._get_or_create_points(student_id)
            
            # Update points
            student_points.total_points += points
            student_points.lifetime_points += points
            
            # Check for level up
            level_up = await self._check_level_up(student_points)
            
            # Create history record
            history = PointHistory(
                student_id=student_id,
                points_id=student_points.id,
                points_awarded=points,
                reason=reason,
                concept_id=concept_id
            )
            self.db.add(history)
            
            await self.db.commit()
            
            result = {
                "points_awarded": points,
                "total_points": student_points.total_points,
                "current_level": student_points.current_level,
                "level_up": level_up
            }
            
            logger.info(
                "Points awarded",
                student_id=student_id,
                points=points,
                reason=reason,
                level_up=level_up
            )
            
            return result
            
        except Exception as e:
            logger.error("Failed to award points", error=str(e))
            await self.db.rollback()
            raise
    
    async def calculate_event_points(self, event_type: str, metadata: Dict[str, Any] = None) -> int:
        """Calculate points for different events."""
        points_map = {
            "concept_started": settings.POINTS_CONCEPT_STARTED,
            "concept_completed": settings.POINTS_CONCEPT_COMPLETED,
            "concept_mastered": settings.POINTS_CONCEPT_MASTERED,
            "daily_streak": settings.POINTS_DAILY_STREAK,
            "weekly_goal": settings.POINTS_WEEKLY_GOAL,
        }
        
        base_points = points_map.get(event_type, 0)
        
        # Add bonuses
        if event_type == "concept_mastered" and metadata:
            if metadata.get("perfect_score"):
                base_points += settings.POINTS_PERFECT_SCORE_BONUS
            
            # Speed bonus
            if metadata.get("completion_time") and metadata["completion_time"] < 300:  # 5 minutes
                base_points += 5
        
        return base_points
    
    async def _get_or_create_points(self, student_id: str) -> Points:
        """Get or create points record for student."""
        result = await self.db.execute(
            select(Points).where(Points.student_id == student_id)
        )
        points = result.scalar_one_or_none()
        
        if not points:
            points = Points(student_id=student_id)
            self.db.add(points)
            await self.db.flush()
        
        return points
    
    async def _check_level_up(self, points: Points) -> bool:
        """Check if student leveled up."""
        # Simple level calculation: level = sqrt(total_points / 100)
        import math
        new_level = int(math.sqrt(points.total_points / 100)) + 1
        
        if new_level > points.current_level:
            points.current_level = new_level
            points.points_to_next_level = (new_level ** 2) * 100 - points.total_points
            return True
        
        points.points_to_next_level = (points.current_level ** 2) * 100 - points.total_points
        return False