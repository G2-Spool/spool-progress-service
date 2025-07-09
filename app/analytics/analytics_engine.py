"""Analytics calculation and aggregation engine."""

from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, case
import numpy as np
import structlog

from app.models.progress import Progress, ConceptProgress, ProgressStatus
from app.models.analytics import Analytics, LearningMetrics, ProgressSnapshot
from app.models.gamification import Points, PointHistory, Streak

logger = structlog.get_logger()


class AnalyticsEngine:
    """Engine for calculating and aggregating analytics."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def calculate_student_analytics(
        self,
        student_id: str,
        period: str = "daily",
        target_date: date = None
    ) -> Dict[str, Any]:
        """Calculate analytics for a specific student and period."""
        if not target_date:
            target_date = date.today()
        
        # Determine date range
        start_date, end_date = self._get_date_range(period, target_date)
        
        # Get concept statistics
        concept_stats = await self._get_concept_stats(student_id, start_date, end_date)
        
        # Get time spent
        time_spent = await self._calculate_time_spent(student_id, start_date, end_date)
        
        # Get average score
        avg_score = await self._calculate_average_score(student_id, start_date, end_date)
        
        # Get points earned
        points_earned = await self._get_points_earned(student_id, start_date, end_date)
        
        # Get badges earned
        badges_earned = await self._get_badges_earned(student_id, start_date, end_date)
        
        # Create or update analytics record
        analytics = await self._save_analytics(
            student_id=student_id,
            period=period,
            period_date=target_date,
            stats={
                **concept_stats,
                "time_spent": time_spent,
                "average_score": avg_score,
                "points_earned": points_earned,
                "badges_earned": badges_earned
            }
        )
        
        return analytics
    
    async def calculate_learning_velocity(
        self,
        student_id: str,
        days: int = 30
    ) -> float:
        """Calculate learning velocity (concepts per day)."""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(
                func.count(ConceptProgress.id).label("concepts"),
                func.count(func.distinct(func.date(ConceptProgress.last_attempted_at))).label("active_days")
            ).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.status.in_([ProgressStatus.COMPLETED.value, ProgressStatus.MASTERED.value]),
                    ConceptProgress.last_attempted_at >= start_date
                )
            )
        )
        
        data = result.one()
        if data.active_days > 0:
            return data.concepts / data.active_days
        return 0.0
    
    async def calculate_mastery_efficiency(
        self,
        student_id: str
    ) -> Dict[str, float]:
        """Calculate how efficiently student masters concepts."""
        result = await self.db.execute(
            select(
                func.avg(ConceptProgress.attempts).label("avg_attempts"),
                func.avg(
                    func.extract('epoch', ConceptProgress.mastered_at - ConceptProgress.created_at) / 3600
                ).label("avg_hours_to_mastery")
            ).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.status == ProgressStatus.MASTERED.value,
                    ConceptProgress.mastered_at.isnot(None)
                )
            )
        )
        
        data = result.one()
        
        return {
            "average_attempts_to_mastery": float(data.avg_attempts or 0),
            "average_hours_to_mastery": float(data.avg_hours_to_mastery or 0),
            "efficiency_score": self._calculate_efficiency_score(
                data.avg_attempts or 0,
                data.avg_hours_to_mastery or 0
            )
        }
    
    async def predict_completion_time(
        self,
        student_id: str,
        remaining_concepts: int
    ) -> Dict[str, Any]:
        """Predict time to complete remaining concepts based on historical data."""
        # Get historical velocity
        velocity = await self.calculate_learning_velocity(student_id)
        
        if velocity <= 0:
            return {
                "estimated_days": None,
                "confidence": "low",
                "recommendation": "Need more learning data to make predictions"
            }
        
        # Calculate estimated days
        estimated_days = remaining_concepts / velocity
        
        # Calculate confidence based on consistency
        consistency = await self._calculate_learning_consistency(student_id)
        
        confidence = "high" if consistency > 0.8 else "medium" if consistency > 0.5 else "low"
        
        return {
            "estimated_days": int(estimated_days),
            "estimated_completion_date": (date.today() + timedelta(days=estimated_days)).isoformat(),
            "confidence": confidence,
            "daily_target": int(velocity),
            "recommendation": self._get_completion_recommendation(estimated_days, velocity)
        }
    
    async def generate_insights(
        self,
        student_id: str
    ) -> Dict[str, Any]:
        """Generate AI-powered insights based on analytics."""
        # Get recent metrics
        metrics = await self._get_recent_metrics(student_id)
        
        # Get progress patterns
        patterns = await self._analyze_progress_patterns(student_id)
        
        # Get strengths and weaknesses
        strengths_weaknesses = await self._analyze_strengths_weaknesses(student_id)
        
        insights = []
        recommendations = []
        
        # Analyze velocity trends
        if "velocity_trend" in patterns:
            if patterns["velocity_trend"] < -0.2:
                insights.append("Your learning pace has decreased by {:.0%} recently.".format(abs(patterns["velocity_trend"])))
                recommendations.append("Try shorter, more frequent study sessions to maintain momentum.")
            elif patterns["velocity_trend"] > 0.2:
                insights.append("Great job! Your learning pace has increased by {:.0%}.".format(patterns["velocity_trend"]))
        
        # Analyze accuracy
        if metrics.get("accuracy", 100) < 70:
            insights.append("Your accuracy is below optimal levels.")
            recommendations.append("Review difficult concepts before moving to new material.")
        
        # Analyze consistency
        if metrics.get("consistency", 0) < 0.5:
            insights.append("Your study pattern is irregular.")
            recommendations.append("Set a daily reminder to maintain consistent progress.")
        
        # Add strength/weakness insights
        if strengths_weaknesses["strengths"]:
            insights.append(f"You excel at: {', '.join(strengths_weaknesses['strengths'][:3])}")
        
        if strengths_weaknesses["weaknesses"]:
            recommendations.append(f"Focus more on: {', '.join(strengths_weaknesses['weaknesses'][:3])}")
        
        return {
            "insights": insights,
            "recommendations": recommendations,
            "metrics_summary": metrics,
            "patterns": patterns,
            "strengths": strengths_weaknesses["strengths"],
            "weaknesses": strengths_weaknesses["weaknesses"]
        }
    
    def _get_date_range(self, period: str, target_date: date) -> tuple:
        """Get start and end date for period."""
        if period == "daily":
            return target_date, target_date
        elif period == "weekly":
            start = target_date - timedelta(days=target_date.weekday())
            end = start + timedelta(days=6)
            return start, end
        else:  # monthly
            start = target_date.replace(day=1)
            next_month = start.replace(day=28) + timedelta(days=4)
            end = next_month - timedelta(days=next_month.day)
            return start, end
    
    async def _get_concept_stats(self, student_id: str, start_date: date, end_date: date) -> Dict[str, int]:
        """Get concept statistics for date range."""
        result = await self.db.execute(
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
                ).label("mastered")
            ).where(ConceptProgress.student_id == student_id)
        )
        
        stats = result.one()
        
        return {
            "concepts_started": stats.started,
            "concepts_completed": stats.completed,
            "concepts_mastered": stats.mastered
        }
    
    async def _calculate_time_spent(self, student_id: str, start_date: date, end_date: date) -> int:
        """Calculate time spent in seconds."""
        # Simplified calculation based on attempts
        result = await self.db.execute(
            select(func.sum(ConceptProgress.attempts * 300)).where(  # 5 min per attempt estimate
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.last_attempted_at.between(start_date, end_date + timedelta(days=1))
                )
            )
        )
        
        return result.scalar() or 0
    
    async def _calculate_average_score(self, student_id: str, start_date: date, end_date: date) -> float:
        """Calculate average score for period."""
        result = await self.db.execute(
            select(func.avg(ConceptProgress.current_score)).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.last_attempted_at.between(start_date, end_date + timedelta(days=1)),
                    ConceptProgress.current_score.isnot(None)
                )
            )
        )
        
        return float(result.scalar() or 0.0)
    
    async def _get_points_earned(self, student_id: str, start_date: date, end_date: date) -> int:
        """Get points earned in period."""
        result = await self.db.execute(
            select(func.sum(PointHistory.points_awarded)).where(
                and_(
                    PointHistory.student_id == student_id,
                    PointHistory.awarded_at.between(start_date, end_date + timedelta(days=1))
                )
            )
        )
        
        return result.scalar() or 0
    
    async def _get_badges_earned(self, student_id: str, start_date: date, end_date: date) -> int:
        """Get badges earned in period."""
        from app.models.gamification import UserBadge
        
        result = await self.db.execute(
            select(func.count(UserBadge.id)).where(
                and_(
                    UserBadge.student_id == student_id,
                    UserBadge.earned_at.between(start_date, end_date + timedelta(days=1))
                )
            )
        )
        
        return result.scalar() or 0
    
    async def _save_analytics(self, student_id: str, period: str, period_date: date, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Save analytics to database."""
        # Check for existing record
        result = await self.db.execute(
            select(Analytics).where(
                and_(
                    Analytics.student_id == student_id,
                    Analytics.period == period,
                    Analytics.period_date == period_date
                )
            )
        )
        analytics = result.scalar_one_or_none()
        
        if analytics:
            # Update existing
            for key, value in stats.items():
                setattr(analytics, key, value)
        else:
            # Create new
            analytics = Analytics(
                student_id=student_id,
                period=period,
                period_date=period_date,
                **stats
            )
            self.db.add(analytics)
        
        await self.db.commit()
        await self.db.refresh(analytics)
        
        return {
            "student_id": str(analytics.student_id),
            "period": analytics.period,
            "period_date": str(analytics.period_date),
            **stats
        }
    
    def _calculate_efficiency_score(self, avg_attempts: float, avg_hours: float) -> float:
        """Calculate efficiency score (0-100)."""
        # Lower attempts and hours = higher efficiency
        attempt_score = max(0, 100 - (avg_attempts - 1) * 20)
        time_score = max(0, 100 - avg_hours * 2)
        
        return (attempt_score + time_score) / 2
    
    async def _calculate_learning_consistency(self, student_id: str) -> float:
        """Calculate learning consistency (0-1)."""
        result = await self.db.execute(
            select(
                func.count(func.distinct(func.date(ConceptProgress.last_attempted_at))).label("active_days"),
                func.datediff(
                    func.max(ConceptProgress.last_attempted_at),
                    func.min(ConceptProgress.created_at)
                ).label("total_days")
            ).where(ConceptProgress.student_id == student_id)
        )
        
        data = result.one()
        if data.total_days and data.total_days > 0:
            return min(1.0, data.active_days / data.total_days)
        return 0.0
    
    def _get_completion_recommendation(self, estimated_days: float, velocity: float) -> str:
        """Get personalized completion recommendation."""
        if estimated_days < 30:
            return f"At your current pace of {velocity:.1f} concepts/day, you're on track to complete soon!"
        elif estimated_days < 90:
            return f"Maintain your pace of {velocity:.1f} concepts/day to complete within 3 months."
        else:
            target_velocity = estimated_days / 60  # Complete in 2 months
            return f"Increase your pace to {target_velocity:.1f} concepts/day to complete within 2 months."
    
    async def _get_recent_metrics(self, student_id: str) -> Dict[str, float]:
        """Get recent learning metrics."""
        result = await self.db.execute(
            select(
                LearningMetrics.metric_type,
                LearningMetrics.metric_value
            ).where(
                LearningMetrics.student_id == student_id
            ).order_by(
                LearningMetrics.calculated_at.desc()
            ).limit(10)
        )
        
        metrics = {}
        for row in result:
            if row.metric_type not in metrics:
                metrics[row.metric_type] = row.metric_value
        
        return metrics
    
    async def _analyze_progress_patterns(self, student_id: str) -> Dict[str, Any]:
        """Analyze progress patterns over time."""
        # Get weekly analytics for trend analysis
        result = await self.db.execute(
            select(
                Analytics.period_date,
                Analytics.concepts_mastered,
                Analytics.time_spent
            ).where(
                and_(
                    Analytics.student_id == student_id,
                    Analytics.period == "weekly"
                )
            ).order_by(Analytics.period_date).limit(8)
        )
        
        data = result.all()
        if len(data) < 2:
            return {}
        
        # Calculate velocity trend
        velocities = [d.concepts_mastered / max(d.time_spent / 3600, 1) for d in data]
        velocity_trend = np.polyfit(range(len(velocities)), velocities, 1)[0]
        
        return {
            "velocity_trend": velocity_trend,
            "recent_weeks": len(data),
            "peak_week": max(data, key=lambda x: x.concepts_mastered).period_date.isoformat()
        }
    
    async def _analyze_strengths_weaknesses(self, student_id: str) -> Dict[str, List[str]]:
        """Analyze student's strengths and weaknesses."""
        # This is simplified - in production would analyze by subject/topic
        result = await self.db.execute(
            select(
                ConceptProgress.metadata["subject"].astext.label("subject"),
                func.avg(ConceptProgress.current_score).label("avg_score"),
                func.count(ConceptProgress.id).label("attempts")
            ).where(
                and_(
                    ConceptProgress.student_id == student_id,
                    ConceptProgress.current_score.isnot(None)
                )
            ).group_by(
                ConceptProgress.metadata["subject"].astext
            ).having(
                func.count(ConceptProgress.id) >= 3
            )
        )
        
        subjects = result.all()
        
        # Sort by average score
        sorted_subjects = sorted(subjects, key=lambda x: x.avg_score, reverse=True)
        
        strengths = [s.subject for s in sorted_subjects[:3] if s.avg_score >= 80]
        weaknesses = [s.subject for s in sorted_subjects if s.avg_score < 70]
        
        return {
            "strengths": strengths,
            "weaknesses": weaknesses
        }