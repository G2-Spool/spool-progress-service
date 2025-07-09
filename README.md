# Spool Progress Service

Progress tracking, gamification, and analytics service for the Spool platform.

## Overview

The Progress Service is responsible for:

- **Progress Tracking**: Monitor student advancement through learning paths
- **Gamification**: Points, badges, streaks, and achievements
- **Analytics**: Generate insights and reports for students, parents, and educators
- **Notifications**: Achievement alerts and milestone celebrations
- **Dashboards**: Comprehensive views for different user roles

## Architecture

```
Learning Event → Progress Update → Gamification Engine
                       ↓                    ↓
                Analytics Engine      Notification System
                       ↓                    ↓
                  Dashboard APIs      Achievement Alerts
```

## Quick Start

### Prerequisites
- Python 3.11+
- Docker
- PostgreSQL or Redis
- Access to other Spool services

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
cp .env.example .env
# Edit .env with your values
```

3. Run locally:
```bash
uvicorn app.main:app --reload --port 8004
```

### Docker

```bash
# Build
docker build -t spool-progress-service .

# Run
docker run -p 8004:8004 spool-progress-service
```

## API Endpoints

### Health Check
```
GET /health
```

### Progress Tracking
```
POST /api/progress/track
  - Track learning event
  - Body: {
      "student_id": "string",
      "concept_id": "string",
      "event_type": "started|completed|mastered",
      "score": 0.0-1.0,
      "time_spent": seconds
    }

GET /api/progress/student/{student_id}
  - Get overall progress for a student

GET /api/progress/student/{student_id}/concept/{concept_id}
  - Get progress for specific concept

GET /api/progress/learning-path/{student_id}
  - Get learning path progress with visualization data
```

### Gamification
```
GET /api/gamification/points/{student_id}
  - Get current points and history

GET /api/gamification/badges/{student_id}
  - Get earned badges

GET /api/gamification/streak/{student_id}
  - Get current learning streak

POST /api/gamification/award-points
  - Award points for achievement
  - Body: {
      "student_id": "string",
      "points": integer,
      "reason": "string"
    }

GET /api/gamification/leaderboard
  - Get leaderboard (with privacy controls)
```

### Analytics
```
GET /api/analytics/report/{student_id}
  - Generate comprehensive progress report
  - Query params: start_date, end_date, format

GET /api/analytics/insights/{student_id}
  - Get AI-generated insights about learning patterns

GET /api/analytics/trends/{student_id}
  - Get learning trends and predictions

POST /api/analytics/export
  - Export analytics data
  - Body: {
      "student_ids": ["array"],
      "date_range": {},
      "format": "pdf|csv|json"
    }
```

### Notifications
```
GET /api/notifications/{user_id}
  - Get pending notifications

POST /api/notifications/mark-read
  - Mark notifications as read
  - Body: { "notification_ids": ["array"] }

GET /api/notifications/preferences/{user_id}
  - Get notification preferences

PUT /api/notifications/preferences/{user_id}
  - Update notification preferences
```

### Dashboards
```
GET /api/dashboard/student/{student_id}
  - Get student dashboard data

GET /api/dashboard/parent/{parent_id}
  - Get parent dashboard with all children

GET /api/dashboard/educator/{educator_id}
  - Get educator dashboard with class overview

GET /api/dashboard/admin/{admin_id}
  - Get admin dashboard with system metrics
```

## Configuration

### Environment Variables
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection for caching
- `JWT_SECRET`: Secret for JWT tokens
- `NOTIFICATION_SERVICE_URL`: URL for notification service
- `EMAIL_ENABLED`: Enable email notifications
- `PUSH_NOTIFICATIONS_ENABLED`: Enable push notifications
- `ANALYTICS_RETENTION_DAYS`: Days to retain detailed analytics
- `LEADERBOARD_SIZE`: Max users in leaderboard

## Data Models

### Progress Tracking
```python
{
  "student_id": "uuid",
  "concept_id": "uuid",
  "status": "not_started|in_progress|completed|mastered",
  "attempts": integer,
  "best_score": float,
  "total_time_spent": seconds,
  "last_accessed": datetime,
  "mastery_date": datetime
}
```

### Gamification Models
```python
# Points
{
  "student_id": "uuid",
  "total_points": integer,
  "level": integer,
  "points_to_next_level": integer
}

# Badges
{
  "badge_id": "uuid",
  "name": "string",
  "description": "string",
  "icon_url": "string",
  "criteria": {},
  "points_value": integer
}

# Streaks
{
  "student_id": "uuid",
  "current_streak": integer,
  "longest_streak": integer,
  "last_activity_date": date
}
```

### Analytics Models
```python
{
  "student_id": "uuid",
  "metrics": {
    "concepts_mastered": integer,
    "total_time_spent": seconds,
    "average_score": float,
    "learning_velocity": float,
    "strongest_subjects": ["array"],
    "areas_for_improvement": ["array"]
  },
  "trends": {
    "weekly_progress": [],
    "subject_distribution": {},
    "time_patterns": {}
  }
}
```

## Gamification System

### Point System
- Concept Started: 5 points
- Concept Completed: 10 points
- Concept Mastered: 25 points
- Perfect Score: 10 bonus points
- Daily Streak: 5 points per day
- Weekly Goal Met: 50 points

### Badges
- **Quick Learner**: Master 5 concepts in one day
- **Consistency King**: 7-day learning streak
- **Subject Master**: Master all concepts in a subject
- **Perfect Week**: 100% completion for a week
- **Helper**: Help another student (peer learning)
- **Explorer**: Try concepts from 5 different subjects

### Levels
- Novice: 0-100 points
- Apprentice: 101-500 points
- Scholar: 501-1000 points
- Expert: 1001-5000 points
- Master: 5000+ points

## Analytics Features

### Student Analytics
- Learning velocity trends
- Subject strength analysis
- Time-of-day performance patterns
- Concept mastery predictions
- Personalized recommendations

### Parent Analytics
- Weekly progress summaries
- Comparison with goals
- Time spent analysis
- Achievement notifications
- Areas needing attention

### Educator Analytics
- Class overview
- Individual student progress
- Concept difficulty analysis
- Engagement metrics
- Intervention recommendations

## Monitoring

### Metrics
- Active users (DAU/MAU)
- Average session duration
- Streak retention rates
- Badge award frequency
- Notification engagement

### Logging
Structured JSON logging with:
- Progress events
- Achievement unlocks
- Analytics generation
- Dashboard access

## Development

### Testing
```bash
# Unit tests
pytest tests/unit

# Integration tests
pytest tests/integration

# All tests
pytest
```

### Code Quality
```bash
# Linting
ruff check app

# Type checking
mypy app

# Format code
black app
```

## Deployment

### AWS ECS
```bash
# Build and push to ECR
./scripts/build-and-push.sh

# Deploy to ECS
./scripts/deploy-ecs.sh
```

### Database Migrations
```bash
# Run migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"
```

## Troubleshooting

### Common Issues

1. **Progress Not Updating**
   - Check service connectivity
   - Verify event payload format
   - Check database connections

2. **Gamification Not Triggering**
   - Verify badge criteria configuration
   - Check point calculation logic
   - Review event processing queue

3. **Analytics Slow**
   - Enable caching
   - Optimize database queries
   - Consider data aggregation

## License

Copyright © 2024 Spool. All rights reserved.