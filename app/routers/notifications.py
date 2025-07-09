"""Notification endpoints for progress updates."""

from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog
import json

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.messaging import send_message
from app.models.gamification import UserBadge, Achievement
from app.schemas.notifications import (
    NotificationCreate, NotificationResponse, NotificationPreferences,
    NotificationBatch
)

logger = structlog.get_logger()
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/progress-update")
async def send_progress_notification(
    notification: NotificationCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send progress update notification."""
    # Only system or instructors can send notifications
    if "instructor" not in current_user.get("roles", []) and "system" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Queue notification
    background_tasks.add_task(
        _send_notification,
        notification.student_id,
        notification.type,
        notification.title,
        notification.message,
        notification.data
    )
    
    return {"status": "queued", "student_id": notification.student_id}


@router.post("/badge-earned")
async def notify_badge_earned(
    student_id: str,
    badge_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Notify student of earned badge."""
    # Get badge details
    result = await db.execute(
        select(UserBadge).where(
            and_(
                UserBadge.student_id == student_id,
                UserBadge.badge_id == badge_id
            )
        ).options(selectinload(UserBadge.badge))
    )
    user_badge = result.scalar_one_or_none()
    
    if not user_badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    
    # Queue notification
    background_tasks.add_task(
        _send_notification,
        student_id,
        "badge_earned",
        f"New Badge: {user_badge.badge.name}!",
        f"Congratulations! You've earned the {user_badge.badge.name} badge. {user_badge.badge.description}",
        {
            "badge_id": str(badge_id),
            "badge_name": user_badge.badge.name,
            "icon_url": user_badge.badge.icon_url,
            "points_value": user_badge.badge.points_value
        }
    )
    
    return {"status": "queued", "badge_name": user_badge.badge.name}


@router.post("/milestone-reached")
async def notify_milestone(
    student_id: str,
    milestone_type: str,
    milestone_value: Any,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Notify student of reached milestone."""
    milestone_messages = {
        "concepts_mastered": f"Amazing! You've mastered {milestone_value} concepts!",
        "streak_days": f"Incredible! You're on a {milestone_value}-day learning streak!",
        "level_up": f"Level Up! You've reached level {milestone_value}!",
        "points_milestone": f"Milestone reached! You've earned {milestone_value} points!",
    }
    
    message = milestone_messages.get(
        milestone_type,
        f"Congratulations on reaching {milestone_value} {milestone_type}!"
    )
    
    # Queue notification
    background_tasks.add_task(
        _send_notification,
        student_id,
        "milestone",
        "Milestone Reached!",
        message,
        {
            "milestone_type": milestone_type,
            "milestone_value": milestone_value
        }
    )
    
    return {"status": "queued", "milestone_type": milestone_type}


@router.post("/weekly-summary")
async def send_weekly_summary(
    student_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send weekly progress summary."""
    # Get weekly stats
    # This would aggregate data from the past week
    
    summary_data = {
        "concepts_completed": 12,
        "concepts_mastered": 8,
        "points_earned": 450,
        "current_streak": 7,
        "time_spent": 3600,  # seconds
        "badges_earned": 2
    }
    
    message = f"""
    Your Weekly Progress Summary:
    
    ✅ Concepts Completed: {summary_data['concepts_completed']}
    🎯 Concepts Mastered: {summary_data['concepts_mastered']}
    🏆 Points Earned: {summary_data['points_earned']}
    🔥 Current Streak: {summary_data['current_streak']} days
    ⏱️ Time Spent: {summary_data['time_spent'] // 60} minutes
    🥇 Badges Earned: {summary_data['badges_earned']}
    
    Keep up the great work!
    """
    
    # Queue notification
    background_tasks.add_task(
        _send_notification,
        student_id,
        "weekly_summary",
        "Your Weekly Progress Summary",
        message.strip(),
        summary_data
    )
    
    return {"status": "queued", "type": "weekly_summary"}


@router.post("/reminder")
async def send_reminder(
    student_id: str,
    reminder_type: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Send learning reminder."""
    reminders = {
        "daily_practice": "Time for your daily practice! Keep your streak alive!",
        "incomplete_concept": "You have concepts waiting to be completed. Ready to continue?",
        "review_needed": "Some concepts need review to maintain mastery. Let's refresh!",
        "goal_reminder": "You're close to reaching your weekly goal. One more push!"
    }
    
    message = reminders.get(reminder_type, "Don't forget to practice today!")
    
    # Queue notification
    background_tasks.add_task(
        _send_notification,
        student_id,
        "reminder",
        "Learning Reminder",
        message,
        {"reminder_type": reminder_type}
    )
    
    return {"status": "queued", "reminder_type": reminder_type}


@router.post("/batch")
async def send_batch_notifications(
    batch: NotificationBatch,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Send batch notifications."""
    # Only admin can send batch notifications
    if "admin" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    queued_count = 0
    
    for student_id in batch.student_ids:
        background_tasks.add_task(
            _send_notification,
            student_id,
            batch.type,
            batch.title,
            batch.message,
            batch.data
        )
        queued_count += 1
    
    return {
        "status": "queued",
        "queued_count": queued_count,
        "type": batch.type
    }


@router.get("/preferences/{student_id}", response_model=NotificationPreferences)
async def get_notification_preferences(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get notification preferences for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # In production, this would fetch from a preferences table
    # For now, return defaults
    return {
        "student_id": student_id,
        "email_enabled": True,
        "push_enabled": True,
        "sms_enabled": False,
        "notification_types": {
            "progress_updates": True,
            "badges_earned": True,
            "milestones": True,
            "reminders": True,
            "weekly_summary": True
        },
        "quiet_hours": {
            "enabled": True,
            "start": "22:00",
            "end": "08:00"
        }
    }


@router.put("/preferences/{student_id}", response_model=NotificationPreferences)
async def update_notification_preferences(
    student_id: str,
    preferences: NotificationPreferences,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update notification preferences."""
    # Verify user is updating their own preferences
    if current_user["sub"] != student_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # In production, this would update preferences in database
    # For now, just return the updated preferences
    return preferences


async def _send_notification(
    student_id: str,
    notification_type: str,
    title: str,
    message: str,
    data: Optional[Dict[str, Any]] = None
):
    """Internal function to send notification via messaging service."""
    try:
        # Format notification payload
        payload = {
            "student_id": student_id,
            "type": notification_type,
            "title": title,
            "message": message,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send via messaging service (SNS/SQS)
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
        
    except Exception as e:
        logger.error(
            "Failed to send notification",
            student_id=student_id,
            type=notification_type,
            error=str(e)
        )
        # Don't raise - notifications are best effort