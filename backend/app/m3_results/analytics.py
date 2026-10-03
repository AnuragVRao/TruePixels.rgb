"""
Module M3 System Analytics & Monitoring Queries (F.16, F.18).
Implements bounded SQL queries for dashboard tiles, time-series volume, confidence histograms, and error rates.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, case, and_
from sqlalchemy.orm import Session
from app.m3_results.models import Prediction, Image, LogEntry, ModelRegistry, User
from app.m3_results.schemas import (
    AdminSummaryTile,
    SystemAnalytics,
    TimeSeriesPoint,
    ConfidenceHistogramBin,
)


def get_admin_summary(db: Session) -> AdminSummaryTile:
    """Computes bounded aggregate summary tiles for the Admin Dashboard (F.16)."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    total_preds = db.query(func.count(Prediction.prediction_id)).scalar() or 0
    preds_24h = (
        db.query(func.count(Prediction.prediction_id))
        .filter(Prediction.prediction_timestamp >= day_ago)
        .scalar()
        or 0
    )

    class_counts = (
        db.query(Prediction.predicted_class, func.count(Prediction.prediction_id))
        .group_by(Prediction.predicted_class)
        .all()
    )
    class_dist = {"Real": 0, "AI Generated": 0}
    for cls_name, count in class_counts:
        if cls_name in class_dist:
            class_dist[cls_name] = count

    error_24h = (
        db.query(func.count(LogEntry.log_id))
        .filter(LogEntry.severity == "error", LogEntry.log_timestamp >= day_ago)
        .scalar()
        or 0
    )

    active_models = (
        db.query(ModelRegistry)
        .filter(ModelRegistry.is_active.is_(True))
        .order_by(ModelRegistry.model_type)
        .all()
    )
    models_info = [
        {"model_type": m.model_type, "model_name": m.model_name, "version": m.model_version}
        for m in active_models
    ]

    return AdminSummaryTile(
        total_predictions=total_preds,
        predictions_last_24h=preds_24h,
        class_distribution=class_dist,
        error_count_last_24h=error_24h,
        active_models=models_info,
    )


def get_system_analytics(db: Session, days: int = 30) -> SystemAnalytics:
    """Computes comprehensive aggregated analytics for admin review (F.18)."""
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # 1. Total Predictions
    total_preds = db.query(func.count(Prediction.prediction_id)).scalar() or 0

    # 2. Class Distribution
    class_counts = (
        db.query(Prediction.predicted_class, func.count(Prediction.prediction_id))
        .group_by(Prediction.predicted_class)
        .all()
    )
    class_dist = {"Real": 0, "AI Generated": 0}
    for cls_name, count in class_counts:
        class_dist[cls_name] = count

    # 3. Time-series usage over time (Daily predictions & active users)
    # Using Image join to count distinct users per day
    daily_stats = (
        db.query(
            func.date(Prediction.prediction_timestamp).label("pred_date"),
            func.count(Prediction.prediction_id).label("count"),
            func.count(func.distinct(Image.user_id)).label("active_users"),
        )
        .join(Image, Image.image_id == Prediction.image_id)
        .filter(Prediction.prediction_timestamp >= start_date)
        .group_by(func.date(Prediction.prediction_timestamp))
        .order_by(func.date(Prediction.prediction_timestamp).asc())
        .all()
    )

    usage_over_time = [
        TimeSeriesPoint(
            date=str(row.pred_date),
            predictions_count=row.count,
            active_users=row.active_users,
        )
        for row in daily_stats
    ]

    # 4. Confidence Distribution in 10 uniform bins [0.0-0.1, ..., 0.9-1.0]
    bins_data = [
        (0.0, 0.1, "0.0 - 0.1"),
        (0.1, 0.2, "0.1 - 0.2"),
        (0.2, 0.3, "0.2 - 0.3"),
        (0.3, 0.4, "0.3 - 0.4"),
        (0.4, 0.5, "0.4 - 0.5"),
        (0.5, 0.6, "0.5 - 0.6"),
        (0.6, 0.7, "0.6 - 0.7"),
        (0.7, 0.8, "0.7 - 0.8"),
        (0.8, 0.9, "0.8 - 0.9"),
        (0.9, 1.0, "0.9 - 1.0"),
    ]
    confidence_bins = []
    for low, high, label in bins_data:
        # Include high boundary for 1.0
        if high == 1.0:
            cond = and_(Prediction.confidence_score >= low, Prediction.confidence_score <= high)
        else:
            cond = and_(Prediction.confidence_score >= low, Prediction.confidence_score < high)
        cnt = db.query(func.count(Prediction.prediction_id)).filter(cond).scalar() or 0
        confidence_bins.append(ConfidenceHistogramBin(bin_range=label, count=cnt))

    # 5. Error Rate
    total_logs = db.query(func.count(LogEntry.log_id)).scalar() or 0
    error_logs = (
        db.query(func.count(LogEntry.log_id))
        .filter(LogEntry.severity == "error")
        .scalar()
        or 0
    )
    error_rate = (error_logs / total_logs * 100.0) if total_logs > 0 else 0.0

    return SystemAnalytics(
        total_predictions=total_preds,
        class_distribution=class_dist,
        usage_over_time=usage_over_time,
        confidence_distribution=confidence_bins,
        error_rate_percentage=round(error_rate, 2),
        total_logs=total_logs,
    )
