"""Progress tracking endpoints."""

from typing import List, Optional, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
import structlog

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.progress import Progress, ConceptProgress, ProgressStatus
from app.schemas.progress import (
    ProgressCreate, ProgressUpdate, ProgressResponse,
    ConceptProgressCreate, ConceptProgressUpdate, ConceptProgressResponse,
    BulkProgressUpdate, ProgressSummary
)

logger = structlog.get_logger()
router = APIRouter(prefix="/progress", tags=["progress"])


@router.post("/", response_model=ProgressResponse)
async def create_progress(
    progress: ProgressCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new progress record."""
    # Verify user is creating progress for themselves or is an instructor
    if current_user["sub"] != str(progress.student_id) and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized to create progress for this student")
    
    db_progress = Progress(**progress.dict())
    db.add(db_progress)
    
    try:
        await db.commit()
        await db.refresh(db_progress)
        logger.info("Progress created", student_id=str(progress.student_id))
        return db_progress
    except Exception as e:
        logger.error("Failed to create progress", error=str(e))
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create progress")


@router.get("/{student_id}", response_model=ProgressResponse)
async def get_student_progress(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get overall progress for a student."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized to view this student's progress")
    
    result = await db.execute(
        select(Progress).where(Progress.student_id == student_id)
    )
    progress = result.scalar_one_or_none()
    
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    
    return progress


@router.get("/{student_id}/summary", response_model=ProgressSummary)
async def get_progress_summary(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed progress summary."""
    # Verify authorization
    if current_user["sub"] != student_id and "instructor" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get overall progress
    result = await db.execute(
        select(Progress).where(Progress.student_id == student_id)
    )
    progress = result.scalar_one_or_none()
    
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    
    # Get concept progress stats
    concept_stats = await db.execute(
        select(
            ConceptProgress.status,
            func.count(ConceptProgress.id).label("count")
        ).where(
            ConceptProgress.student_id == student_id
        ).group_by(ConceptProgress.status)
    )
    
    status_counts = {row.status: row.count for row in concept_stats}
    
    # Get recent activity
    recent_concepts = await db.execute(
        select(ConceptProgress).where(
            ConceptProgress.student_id == student_id
        ).order_by(ConceptProgress.last_attempted_at.desc()).limit(10)
    )
    
    return {
        "overall_progress": progress,
        "concept_stats": {
            "not_started": status_counts.get(ProgressStatus.NOT_STARTED.value, 0),
            "in_progress": status_counts.get(ProgressStatus.IN_PROGRESS.value, 0),
            "completed": status_counts.get(ProgressStatus.COMPLETED.value, 0),
            "mastered": status_counts.get(ProgressStatus.MASTERED.value, 0),
        },
        "recent_activity": recent_concepts.scalars().all()
    }


@router.post("/concepts", response_model=ConceptProgressResponse)
async def create_concept_progress(
    concept_progress: ConceptProgressCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create or update concept progress."""
    # Check if progress already exists
    result = await db.execute(
        select(ConceptProgress).where(
            and_(
                ConceptProgress.student_id == concept_progress.student_id,
                ConceptProgress.concept_id == concept_progress.concept_id
            )
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Update existing
        for key, value in concept_progress.dict(exclude_unset=True).items():
            setattr(existing, key, value)
        db_concept = existing
    else:
        # Create new
        db_concept = ConceptProgress(**concept_progress.dict())
        db.add(db_concept)
    
    try:
        await db.commit()
        await db.refresh(db_concept)
        logger.info(
            "Concept progress updated",
            student_id=str(concept_progress.student_id),
            concept_id=str(concept_progress.concept_id)
        )
        return db_concept
    except Exception as e:
        logger.error("Failed to update concept progress", error=str(e))
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update concept progress")


@router.get("/concepts/{student_id}", response_model=List[ConceptProgressResponse])
async def get_concept_progress(
    student_id: str,
    status: Optional[ProgressStatus] = Query(None),
    subject: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get concept progress for a student."""
    # Build query
    query = select(ConceptProgress).where(ConceptProgress.student_id == student_id)
    
    if status:
        query = query.where(ConceptProgress.status == status.value)
    
    if subject:
        query = query.where(ConceptProgress.metadata["subject"].astext == subject)
    
    query = query.offset(offset).limit(limit).order_by(ConceptProgress.last_attempted_at.desc())
    
    result = await db.execute(query)
    return result.scalars().all()


@router.put("/concepts/{concept_progress_id}", response_model=ConceptProgressResponse)
async def update_concept_progress(
    concept_progress_id: str,
    update: ConceptProgressUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update specific concept progress."""
    result = await db.execute(
        select(ConceptProgress).where(ConceptProgress.id == concept_progress_id)
    )
    concept_progress = result.scalar_one_or_none()
    
    if not concept_progress:
        raise HTTPException(status_code=404, detail="Concept progress not found")
    
    # Update fields
    update_data = update.dict(exclude_unset=True)
    
    # Handle status transitions
    if "status" in update_data:
        old_status = concept_progress.status
        new_status = update_data["status"]
        
        # Update timestamps based on status change
        if new_status == ProgressStatus.COMPLETED.value and old_status != ProgressStatus.COMPLETED.value:
            update_data["completed_at"] = datetime.utcnow()
        elif new_status == ProgressStatus.MASTERED.value and old_status != ProgressStatus.MASTERED.value:
            update_data["mastered_at"] = datetime.utcnow()
    
    # Update attempts if score provided
    if "current_score" in update_data:
        concept_progress.attempts += 1
    
    for key, value in update_data.items():
        setattr(concept_progress, key, value)
    
    try:
        await db.commit()
        await db.refresh(concept_progress)
        return concept_progress
    except Exception as e:
        logger.error("Failed to update concept progress", error=str(e))
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update")


@router.post("/bulk-update", response_model=Dict[str, Any])
async def bulk_update_progress(
    updates: BulkProgressUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Bulk update multiple concept progress records."""
    updated_count = 0
    errors = []
    
    for update in updates.updates:
        try:
            # Find existing progress
            result = await db.execute(
                select(ConceptProgress).where(
                    and_(
                        ConceptProgress.student_id == update.student_id,
                        ConceptProgress.concept_id == update.concept_id
                    )
                )
            )
            progress = result.scalar_one_or_none()
            
            if progress:
                # Update existing
                for key, value in update.dict(exclude={"student_id", "concept_id"}, exclude_unset=True).items():
                    setattr(progress, key, value)
            else:
                # Create new
                progress = ConceptProgress(**update.dict())
                db.add(progress)
            
            updated_count += 1
            
        except Exception as e:
            errors.append({
                "student_id": str(update.student_id),
                "concept_id": str(update.concept_id),
                "error": str(e)
            })
    
    try:
        await db.commit()
        return {
            "updated_count": updated_count,
            "errors": errors
        }
    except Exception as e:
        logger.error("Bulk update failed", error=str(e))
        await db.rollback()
        raise HTTPException(status_code=500, detail="Bulk update failed")


@router.get("/leaderboard", response_model=List[Dict[str, Any]])
async def get_leaderboard(
    timeframe: str = Query("all", regex="^(daily|weekly|monthly|all)$"),
    subject: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get progress leaderboard."""
    # Build date filter based on timeframe
    date_filter = None
    if timeframe == "daily":
        date_filter = func.date(Progress.updated_at) == date.today()
    elif timeframe == "weekly":
        date_filter = Progress.updated_at >= func.date_trunc('week', func.current_date())
    elif timeframe == "monthly":
        date_filter = Progress.updated_at >= func.date_trunc('month', func.current_date())
    
    # Query for leaderboard
    query = select(
        Progress.student_id,
        Progress.total_concepts_mastered,
        Progress.current_level,
        func.sum(Progress.total_time_spent).label("time_spent")
    ).group_by(Progress.student_id, Progress.total_concepts_mastered, Progress.current_level)
    
    if date_filter is not None:
        query = query.where(date_filter)
    
    query = query.order_by(Progress.total_concepts_mastered.desc()).limit(limit)
    
    result = await db.execute(query)
    
    leaderboard = []
    for row in result:
        leaderboard.append({
            "student_id": str(row.student_id),
            "concepts_mastered": row.total_concepts_mastered,
            "level": row.current_level,
            "time_spent": row.time_spent,
            "rank": len(leaderboard) + 1
        })
    
    return leaderboard