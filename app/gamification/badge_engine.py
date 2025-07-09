"""Badge awarding and tracking engine."""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import json
import structlog

from app.models.gamification import Badge, UserBadge, BadgeCategory
from app.models.progress import ConceptProgress, ProgressStatus

logger = structlog.get_logger()


class BadgeEngine:
    """Engine for checking and awarding badges."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def check_and_award_badges(
        self,
        student_id: str,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Check if student earned any badges based on event."""
        earned_badges = []
        
        # Get all active badges
        result = await self.db.execute(
            select(Badge).where(Badge.is_active == True)
        )
        badges = result.scalars().all()
        
        for badge in badges:
            if await self._check_badge_criteria(student_id, badge, event_type, event_data):
                # Award badge if not already earned
                user_badge = await self._award_badge(student_id, badge)
                if user_badge:
                    earned_badges.append({
                        "badge_id": str(badge.id),
                        "name": badge.name,
                        "description": badge.description,
                        "icon_url": badge.icon_url,
                        "points_value": badge.points_value
                    })
        
        return earned_badges
    
    async def _check_badge_criteria(
        self,
        student_id: str,
        badge: Badge,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> bool:
        """Check if badge criteria are met."""
        criteria = badge.criteria
        
        # Quick Learner: Master 5 concepts in one day
        if badge.name == "Quick Learner":
            if event_type == "concept_mastered":
                result = await self.db.execute(
                    select(ConceptProgress).where(
                        and_(
                            ConceptProgress.student_id == student_id,
                            ConceptProgress.status == ProgressStatus.MASTERED.value,
                            ConceptProgress.mastered_at >= datetime.utcnow() - timedelta(days=1)
                        )
                    )
                )
                mastered_today = len(result.scalars().all())
                return mastered_today >= 5
        
        # Consistency King: 7-day learning streak
        elif badge.name == "Consistency King":
            if event_type == "daily_streak":
                return event_data.get("streak_days", 0) >= 7
        
        # Subject Master: Master all concepts in a subject
        elif badge.name == "Subject Master":
            if event_type == "concept_mastered":
                subject = event_data.get("subject")
                if subject:
                    # This would need to check against content service
                    # For now, simplified check
                    return event_data.get("subject_completion", 0) >= 100
        
        # Add more badge criteria checks...
        
        return False
    
    async def _award_badge(self, student_id: str, badge: Badge) -> Optional[UserBadge]:
        """Award badge to student if not already earned."""
        # Check if already earned
        result = await self.db.execute(
            select(UserBadge).where(
                and_(
                    UserBadge.student_id == student_id,
                    UserBadge.badge_id == badge.id
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            return None
        
        # Award new badge
        user_badge = UserBadge(
            student_id=student_id,
            badge_id=badge.id
        )
        self.db.add(user_badge)
        
        try:
            await self.db.commit()
            logger.info(
                "Badge awarded",
                student_id=student_id,
                badge_name=badge.name
            )
            return user_badge
        except Exception as e:
            logger.error("Failed to award badge", error=str(e))
            await self.db.rollback()
            return None