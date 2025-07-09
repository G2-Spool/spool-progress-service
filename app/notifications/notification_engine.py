"""Notification engine for progress updates."""

from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import json
import structlog

from app.core.messaging import send_message
from app.models.progress import Progress, ConceptProgress, ProgressStatus
from app.models.gamification import Points, Streak, UserBadge

logger = structlog.get_logger()


class NotificationEngine:
    """Engine for managing and sending notifications."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def send_progress_update(
        self,
        student_id: str,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> bool:
        """Send progress update notification based on event."""
        try:
            # Get student preferences (simplified - would fetch from DB)
            preferences = await self._get_notification_preferences(student_id)
            
            if not self._should_send_notification(event_type, preferences):
                return False
            
            # Generate notification content
            notification = self._generate_notification(event_type, event_data)
            
            # Send notification
            await self._send_notification(
                student_id=student_id,
                notification_type=event_type,
                title=notification["title"],
                message=notification["message"],
                data=event_data
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to send notification",
                student_id=student_id,
                event_type=event_type,
                error=str(e)
            )
            return False
    
    async def send_daily_reminder(self, student_id: str) -> bool:
        """Send daily practice reminder."""
        # Check if student has been active today
        result = await self.db.execute(
            select(ConceptProgress).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.last_attempted_at >= date.today()
                )
            ).limit(1)
        )
        
        if result.scalar_one_or_none():
            # Already active today
            return False
        
        # Get streak info
        streak_result = await self.db.execute(
            select(Streak).where(Streak.student_id == student_id)
        )
        streak = streak_result.scalar_one_or_none()
        
        # Generate reminder message
        if streak and streak.current_streak > 0:
            message = f"Don't break your {streak.current_streak}-day streak! Time for today's practice."
        else:
            message = "Ready to learn something new today? Your next concept is waiting!"
        
        await self._send_notification(
            student_id=student_id,
            notification_type="daily_reminder",
            title="Daily Learning Reminder",
            message=message,
            data={"streak": streak.current_streak if streak else 0}
        )
        
        return True
    
    async def send_weekly_summary(self, student_id: str) -> bool:
        """Send weekly progress summary."""
        # Calculate weekly stats
        week_start = date.today() - timedelta(days=7)
        
        # Get concepts progress
        concepts_result = await self.db.execute(
            select(
                func.count(ConceptProgress.id).filter(
                    ConceptProgress.created_at >= week_start
                ).label("started"),
                func.count(ConceptProgress.id).filter(
                    and_(
                        ConceptProgress.status == ProgressStatus.MASTERED.value,
                        ConceptProgress.mastered_at >= week_start
                    )
                ).label("mastered")
            ).where(ConceptProgress.student_id == student_id)
        )
        concepts = concepts_result.one()
        
        # Get points earned
        points_result = await self.db.execute(
            select(func.sum(PointHistory.points_awarded)).where(
                and_(
                    PointHistory.student_id == student_id,
                    PointHistory.awarded_at >= week_start
                )
            )
        )
        points_earned = points_result.scalar() or 0
        
        # Get badges earned
        badges_result = await self.db.execute(
            select(UserBadge).where(
                and_(
                    UserBadge.student_id == student_id,
                    UserBadge.earned_at >= week_start
                )
            ).options(selectinload(UserBadge.badge))
        )
        badges = badges_result.scalars().all()
        
        # Generate summary
        summary = {
            "concepts_started": concepts.started,
            "concepts_mastered": concepts.mastered,
            "points_earned": points_earned,
            "badges_earned": len(badges),
            "badge_names": [b.badge.name for b in badges]
        }
        
        message = self._generate_weekly_summary_message(summary)
        
        await self._send_notification(
            student_id=student_id,
            notification_type="weekly_summary",
            title="Your Weekly Progress Summary",
            message=message,
            data=summary
        )
        
        return True
    
    async def send_milestone_notification(
        self,
        student_id: str,
        milestone_type: str,
        milestone_value: Any
    ) -> bool:
        """Send milestone achievement notification."""
        milestone_config = {
            "concepts_mastered": {
                "title": "Concepts Milestone!",
                "message": f"Amazing! You've mastered {milestone_value} concepts!",
                "emoji": "🎯"
            },
            "streak_days": {
                "title": "Streak Milestone!",
                "message": f"Incredible! You're on a {milestone_value}-day learning streak!",
                "emoji": "🔥"
            },
            "level_up": {
                "title": "Level Up!",
                "message": f"Congratulations! You've reached level {milestone_value}!",
                "emoji": "⬆️"
            },
            "points_milestone": {
                "title": "Points Milestone!",
                "message": f"Fantastic! You've earned {milestone_value} total points!",
                "emoji": "🏆"
            }
        }
        
        config = milestone_config.get(milestone_type)
        if not config:
            return False
        
        await self._send_notification(
            student_id=student_id,
            notification_type="milestone",
            title=config["title"],
            message=f"{config['emoji']} {config['message']}",
            data={
                "milestone_type": milestone_type,
                "milestone_value": milestone_value
            }
        )
        
        return True
    
    async def check_and_send_reminders(self) -> Dict[str, int]:
        """Check all students and send appropriate reminders."""
        sent_counts = {
            "daily_reminders": 0,
            "streak_warnings": 0,
            "goal_reminders": 0
        }
        
        # Get all active students
        students_result = await self.db.execute(
            select(Progress.student_id).distinct()
        )
        student_ids = [row[0] for row in students_result]
        
        for student_id in student_ids:
            # Check for daily reminder
            if await self._should_send_daily_reminder(student_id):
                if await self.send_daily_reminder(student_id):
                    sent_counts["daily_reminders"] += 1
            
            # Check for streak warning
            if await self._should_send_streak_warning(student_id):
                if await self._send_streak_warning(student_id):
                    sent_counts["streak_warnings"] += 1
            
            # Check for goal reminder
            if await self._should_send_goal_reminder(student_id):
                if await self._send_goal_reminder(student_id):
                    sent_counts["goal_reminders"] += 1
        
        return sent_counts
    
    async def _get_notification_preferences(self, student_id: str) -> Dict[str, Any]:
        """Get notification preferences for student."""
        # In production, would fetch from database
        return {
            "email_enabled": True,
            "push_enabled": True,
            "notification_types": {
                "progress_updates": True,
                "badges_earned": True,
                "milestones": True,
                "reminders": True,
                "weekly_summary": True
            },
            "quiet_hours": {
                "enabled": True,
                "start": 22,
                "end": 8
            }
        }
    
    def _should_send_notification(self, event_type: str, preferences: Dict[str, Any]) -> bool:
        """Check if notification should be sent based on preferences."""
        # Check if notification type is enabled
        notification_category = self._get_notification_category(event_type)
        if not preferences["notification_types"].get(notification_category, True):
            return False
        
        # Check quiet hours
        if preferences["quiet_hours"]["enabled"]:
            current_hour = datetime.utcnow().hour
            start = preferences["quiet_hours"]["start"]
            end = preferences["quiet_hours"]["end"]
            
            if start > end:  # Crosses midnight
                if current_hour >= start or current_hour < end:
                    return False
            else:
                if start <= current_hour < end:
                    return False
        
        return True
    
    def _get_notification_category(self, event_type: str) -> str:
        """Map event type to notification category."""
        category_map = {
            "concept_completed": "progress_updates",
            "concept_mastered": "progress_updates",
            "badge_earned": "badges_earned",
            "level_up": "milestones",
            "streak_milestone": "milestones",
            "daily_reminder": "reminders",
            "weekly_summary": "weekly_summary"
        }
        
        return category_map.get(event_type, "progress_updates")
    
    def _generate_notification(self, event_type: str, event_data: Dict[str, Any]) -> Dict[str, str]:
        """Generate notification content based on event."""
        templates = {
            "concept_completed": {
                "title": "Concept Completed!",
                "message": "Great job! You've completed '{concept_name}'."
            },
            "concept_mastered": {
                "title": "Concept Mastered!",
                "message": "Excellent! You've mastered '{concept_name}' with a score of {score}%!"
            },
            "badge_earned": {
                "title": "New Badge Earned!",
                "message": "Congratulations! You've earned the '{badge_name}' badge!"
            },
            "level_up": {
                "title": "Level Up!",
                "message": "Amazing! You've reached level {level}!"
            }
        }
        
        template = templates.get(event_type, {
            "title": "Progress Update",
            "message": "You've made progress in your learning journey!"
        })
        
        # Format message with event data
        title = template["title"]
        message = template["message"]
        
        for key, value in event_data.items():
            message = message.replace(f"{{{key}}}", str(value))
        
        return {"title": title, "message": message}
    
    def _generate_weekly_summary_message(self, summary: Dict[str, Any]) -> str:
        """Generate weekly summary message."""
        message_parts = [
            f"This week you:",
            f"• Started {summary['concepts_started']} concepts",
            f"• Mastered {summary['concepts_mastered']} concepts",
            f"• Earned {summary['points_earned']} points"
        ]
        
        if summary['badges_earned'] > 0:
            message_parts.append(f"• Earned {summary['badges_earned']} badges: {', '.join(summary['badge_names'])}")
        
        message_parts.append("\nKeep up the great work!")
        
        return "\n".join(message_parts)
    
    async def _send_notification(
        self,
        student_id: str,
        notification_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Send notification via messaging service."""
        try:
            payload = {
                "student_id": student_id,
                "type": notification_type,
                "title": title,
                "message": message,
                "data": data or {},
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await send_message(
                topic="progress-notifications",
                message=json.dumps(payload),
                attributes={
                    "student_id": student_id,
                    "notification_type": notification_type
                }
            )
            
            logger.info(
                "Notification sent",
                student_id=student_id,
                type=notification_type
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to send notification",
                student_id=student_id,
                type=notification_type,
                error=str(e)
            )
            return False
    
    async def _should_send_daily_reminder(self, student_id: str) -> bool:
        """Check if daily reminder should be sent."""
        # Check if already active today
        result = await self.db.execute(
            select(ConceptProgress).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.last_attempted_at >= date.today()
                )
            ).limit(1)
        )
        
        return result.scalar_one_or_none() is None
    
    async def _should_send_streak_warning(self, student_id: str) -> bool:
        """Check if streak warning should be sent."""
        result = await self.db.execute(
            select(Streak).where(Streak.student_id == student_id)
        )
        streak = result.scalar_one_or_none()
        
        if not streak or streak.current_streak < 3:
            return False
        
        # Check if last activity was yesterday (at risk of breaking streak)
        return streak.last_activity_date == date.today() - timedelta(days=1)
    
    async def _send_streak_warning(self, student_id: str) -> bool:
        """Send streak warning notification."""
        result = await self.db.execute(
            select(Streak).where(Streak.student_id == student_id)
        )
        streak = result.scalar_one_or_none()
        
        if not streak:
            return False
        
        await self._send_notification(
            student_id=student_id,
            notification_type="streak_warning",
            title="Streak at Risk!",
            message=f"Your {streak.current_streak}-day streak is at risk! Complete a concept today to keep it alive.",
            data={"current_streak": streak.current_streak}
        )
        
        return True
    
    async def _should_send_goal_reminder(self, student_id: str) -> bool:
        """Check if goal reminder should be sent."""
        # Check if close to weekly goal
        week_start = date.today() - timedelta(days=date.today().weekday())
        
        result = await self.db.execute(
            select(func.count(ConceptProgress.id)).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.status == ProgressStatus.MASTERED.value,
                    ConceptProgress.mastered_at >= week_start
                )
            )
        )
        
        mastered_this_week = result.scalar() or 0
        weekly_goal = 5  # Default goal
        
        # Send reminder if close to goal (80% or more) but not reached
        return weekly_goal * 0.8 <= mastered_this_week < weekly_goal
    
    async def _send_goal_reminder(self, student_id: str) -> bool:
        """Send goal reminder notification."""
        week_start = date.today() - timedelta(days=date.today().weekday())
        
        result = await self.db.execute(
            select(func.count(ConceptProgress.id)).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.status == ProgressStatus.MASTERED.value,
                    ConceptProgress.mastered_at >= week_start
                )
            )
        )
        
        mastered_this_week = result.scalar() or 0
        weekly_goal = 5  # Default goal
        remaining = weekly_goal - mastered_this_week
        
        await self._send_notification(
            student_id=student_id,
            notification_type="goal_reminder",
            title="Close to Your Weekly Goal!",
            message=f"You're just {remaining} concept{'s' if remaining > 1 else ''} away from your weekly goal!",
            data={
                "mastered_this_week": mastered_this_week,
                "weekly_goal": weekly_goal,
                "remaining": remaining
            }
        )
        
        return True