from datetime import datetime, timedelta
from models.models import db, Attendance, GlobalSettings

def auto_clock_out():
    settings = GlobalSettings.query.first()
    if not settings or not settings.auto_clock_out_hours:
        return

    threshold_time = datetime.now() - timedelta(hours=settings.auto_clock_out_hours)

    active_attendance = Attendance.query.filter(Attendance.clock_out.is_(None)).all()

    for record in active_attendance:
        if record.clock_in < threshold_time:
            record.clock_out = threshold_time
            db.session.commit()
            print(f"Auto Clocked-Out: User {record.employee_id}")

# Run this as a scheduled task (Celery, APScheduler, or Cron)
