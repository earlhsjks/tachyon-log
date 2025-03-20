from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, time
from models.models import db, User, Attendance, Schedule, GlobalSettings, AttendanceInconsistency

# Create a Blueprint for main user routes
main_bp = Blueprint('main', __name__)

from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def check_attendance_flags(attendance_entry):
    """
    Checks and updates attendance flags based on clock-in and clock-out times.
    Handles late arrivals, early departures, and overtime detection.
    """
    if not attendance_entry or not attendance_entry.clock_in:
        return

    global_settings = GlobalSettings.query.first()
    allowed_late_minutes = global_settings.allowed_late_in if global_settings else 0

    # Get user's schedule for the day
    today = attendance_entry.clock_in.date()
    user_schedule = Schedule.query.filter_by(employee_id=attendance_entry.employee_id, day=today.strftime('%A')).first()

    if user_schedule:
        schedule_start = datetime.combine(today, user_schedule.start_time)
        schedule_end = datetime.combine(today, user_schedule.end_time)

        # LATE: Clock-in is after scheduled start + grace period
        if attendance_entry.clock_in > schedule_start + timedelta(minutes=allowed_late_minutes):
            db.session.add(AttendanceInconsistency(
                employee_id=attendance_entry.employee_id,
                date=today,
                issue_type="Late",
                details=f"Clock-in at {attendance_entry.clock_in.strftime('%I:%M %p')}, scheduled start {schedule_start.strftime('%I:%M %p')}"
            ))

        # EARLY OUT: Clock-out before scheduled end
        if attendance_entry.clock_out and attendance_entry.clock_out < schedule_end:
            db.session.add(AttendanceInconsistency(
                employee_id=attendance_entry.employee_id,
                date=today,
                issue_type="Early Out",
                details=f"Clock-out at {attendance_entry.clock_out.strftime('%I:%M %p')}, scheduled end {schedule_end.strftime('%I:%M %p')}"
            ))

        # OVERTIME: Work exceeds scheduled shift + buffer (default 8 hours)
        if attendance_entry.clock_out:
            work_duration = attendance_entry.clock_out - attendance_entry.clock_in
            scheduled_duration = schedule_end - schedule_start
            overtime_threshold = global_settings.overtime_threshold if global_settings else timedelta(hours=8)

            if work_duration > scheduled_duration + overtime_threshold:
                db.session.add(AttendanceInconsistency(
                    employee_id=attendance_entry.employee_id,
                    date=today,
                    issue_type="Overtime",
                    details=f"Worked {work_duration}, scheduled {scheduled_duration}"
                ))

    db.session.commit()
        
# Home Route
@main_bp.route('/')
def home():
    return render_template('index.html')

@main_bp.route('/', methods=['GET', 'POST'])
def login_employee():
    """Handles employee login from the main index page."""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        
        user = User.query.filter_by(employee_id=employee_id, role="employee").first()

        if user:
            login_user(user)
            return redirect(url_for('main.dashboard_employee'))
        else:
            flash("ID Not Found!", "error")

    return render_template('index.html')

# Employee Dashboard
@main_bp.route('/gia-dashboard')
@login_required
def dashboard_employee():
    month = request.args.get('month')  # Get selected month (format: YYYY-MM)

    if month:
        year, month = map(int, month.split('-'))
    else:
        # Default: Show current month
        today = datetime.today()
        year, month = today.year, today.month

    today_day = datetime.today().strftime('%A')  # Get today's weekday
    user_schedule = Schedule.query.filter_by(employee_id=current_user.employee_id, day=today_day).first()

    attendance_records = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        db.extract('year', Attendance.clock_in) == year,
        db.extract('month', Attendance.clock_in) == month
    ).all()

    status = "Off Duty"  # Default status
    today = datetime.today().date()
    
    if attendance_records:
        last_record = attendance_records[-1]  # Get last recorded attendance
        
        # Only consider 'On Duty' if clock-in is today
        if last_record.clock_out is None and last_record.clock_in.date() == today:
            status = "On Duty"
    
            if GlobalSettings.enable_strict_schedule:
                # Check if the user is late
                if user_schedule and last_record.clock_in.time() > user_schedule.start_time:
                    status = "Late"
    
                # Check if they are working overtime but haven't clocked out yet
                elif user_schedule and datetime.now().time() > user_schedule.end_time:
                    status = "Overtime"
    
        elif last_record.clock_out:  # User has clocked out
            if GlobalSettings.enable_strict_schedule:
                if user_schedule and last_record.clock_in.time() > user_schedule.start_time:
                    status = "Late"
    
                elif user_schedule and last_record.clock_out.time() > user_schedule.end_time:
                    status = "Overtime"
    
    # Format status for CSS class
    status_class = status.lower().replace(" ", "-")

    return render_template(
        'dashboard_employee.html',
        status=status,  # For display text
        status_class=status_class,  # For CSS class
        name=current_user.username,
        attendance_records=attendance_records,
        current_month=f"{year}-{month:02d}"  # Ensure month is always two digits (e.g., 2024-03)
    )

# Logout Route
@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.home'))

# Clock-In/Clock-Out Routes
@main_bp.route('/clock-in')
@login_required
def clock_in():
    today = datetime.today().strftime('%A')  # Get current day
    now = datetime.now().time()

    # Get user's schedule for today (including broken schedules)
    user_schedules = Schedule.query.filter_by(employee_id=current_user.employee_id, day=today).all()
    global_settings = GlobalSettings.query.first()

    # Apply global schedule if no personal schedule is found
    if not user_schedules and global_settings and global_settings.default_schedule_start and global_settings.default_schedule_end:
        user_schedules = [Schedule(
            employee_id=current_user.employee_id,
            day=today,
            start_time=global_settings.default_schedule_start,
            end_time=global_settings.default_schedule_end
        )]

    if not user_schedules:
        flash("No schedule set for today.", "error")
        return redirect(url_for('main.dashboard_employee'))

    # Get allowed early-in time
    allowed_early_in = global_settings.allowed_early_in if global_settings and global_settings.allowed_early_in else 0

    # Detect if the user has a second shift (broken schedule)
    has_second_shift = any(sched.is_broken and sched.second_start_time and sched.second_end_time for sched in user_schedules)

    # Validate clock-in time (Checking both normal & broken schedules)
    valid_schedule = None
    is_second_shift = False  # Track if user is clocking in for second shift

    for schedule in user_schedules:
        earliest_clock_in_time = (datetime.combine(datetime.today(), schedule.start_time) - timedelta(minutes=allowed_early_in)).time()

        # First shift check
        if earliest_clock_in_time <= now <= schedule.end_time:
            valid_schedule = schedule
            break

        # Second shift check (Broken Schedule)
        if schedule.is_broken and schedule.second_start_time and schedule.second_end_time:
            earliest_second_clock_in_time = (datetime.combine(datetime.today(), schedule.second_start_time) - timedelta(minutes=allowed_early_in)).time()
            if earliest_second_clock_in_time <= now <= schedule.second_end_time:
                valid_schedule = schedule
                is_second_shift = True  # Mark this as second shift clock-in
                break

    # Prevent clock-in if still on duty (for this shift)
    active_shifts = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        Attendance.clock_in != None,
        Attendance.clock_out == None,  # No clock-out yet
        Attendance.clock_in >= datetime.combine(datetime.today(), datetime.min.time())  # Only today's records
    ).all()

    # If user already has an active shift today, check if it's in the same time block
    for shift in active_shifts:
        if valid_schedule:
            # First shift protection
            if not is_second_shift and valid_schedule.start_time <= shift.clock_in.time() <= valid_schedule.end_time:
                flash("You are already on duty for this shift! Please clock out before clocking in again.", "warning")
                return redirect(url_for('main.dashboard_employee'))

            # Second shift protection
            if is_second_shift and shift.clock_in.time() >= valid_schedule.second_start_time and shift.clock_out is None:
                flash("You already clocked in for your second shift! Please clock out before clocking in again.", "warning")
                return redirect(url_for('main.dashboard_employee'))

    # Allow second clock-in ONLY IF still within the scheduled shift
    if len(active_shifts) == 1 and not has_second_shift:
        active_shift = active_shifts[0]
        if active_shift.clock_in.time() <= now <= valid_schedule.end_time:
            flash("Clocking in again during the same shift!", "info")
        else:
            flash("You cannot clock in twice outside your scheduled hours!", "error")
            return redirect(url_for('main.dashboard_employee'))

    # Prevent triple clock-ins for users with second shifts
    if len(active_shifts) >= 2 and has_second_shift:
        flash("You cannot clock in more than twice in a day!", "warning")
        return redirect(url_for('main.dashboard_employee'))

    # Enforce strict schedule rule
    if global_settings and global_settings.enable_strict_schedule and not valid_schedule:
        flash("You can only clock in during your scheduled shift!", "error")
        return redirect(url_for('main.dashboard_employee'))

    # Create a new attendance entry
    new_entry = Attendance(employee_id=current_user.employee_id, clock_in=datetime.now())
    check_attendance_flags(new_entry)
    db.session.add(new_entry)
    db.session.commit()

    flash("Clocked in successfully!", "success")
    return redirect(url_for('main.dashboard_employee'))

@main_bp.route('/clock_out')
@login_required
def clock_out():
    today = datetime.today()
    now = datetime.now()
    
    # Get the latest clock-in record for today
    last_record = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        Attendance.clock_in != None,
        Attendance.clock_in >= datetime.combine(today, datetime.min.time()),  # Only today's records
        Attendance.clock_out == None  # Ensure they haven’t clocked out yet
    ).order_by(Attendance.id.desc()).first()  # Get the latest clock-in

    if not last_record:
        flash("No active clock-in found for today!", "danger")
        return redirect(url_for('main.dashboard_employee'))

    # Fetch global settings
    global_settings = GlobalSettings.query.first()
    strict_schedule = global_settings.enable_strict_schedule if global_settings else False

    # Get the user's schedule for today
    today_day = today.strftime("%A")
    user_schedule = Schedule.query.filter_by(employee_id=current_user.employee_id, day=today_day).first()

    # Default clock-out time: Now
    actual_clock_out = now

    if strict_schedule and user_schedule:
        schedule_end = datetime.combine(today, user_schedule.end_time)
        time_limit = schedule_end + timedelta(minutes=30)  # ⏳ 30-minute grace period

        # Block clock-out if more than 30 minutes past scheduled end time
        if actual_clock_out > time_limit:
            flash("Clock-out denied! More than 30 minutes past your scheduled end time.", "error")
            return redirect(url_for('main.dashboard_employee'))

        # If between schedule end and 7:30 PM, force clock-out to schedule end
        time_730pm = datetime.combine(today, time(19, 30))  # 7:30 PM cutoff
        if schedule_end < actual_clock_out < time_730pm:
            last_record.clock_out = schedule_end
        else:
            last_record.clock_out = actual_clock_out  # Normal clock-out

    else:
        # 🔓 No strict schedule → Allow clock-out anytime
        last_record.clock_out = actual_clock_out

    db.session.commit()

    # Check attendance flags (Overtime, etc.)
    check_attendance_flags(last_record)

    flash("Clocked out successfully!", "success")
    return redirect(url_for('main.dashboard_employee'))

# Break Tracking Feature (Disabled)
@main_bp.route('/start-break')
@login_required
def start_break():
    """Logs the start of an employee's break."""
    last_record = Attendance.query.filter_by(employee_id=current_user.employee_id).order_by(Attendance.id.desc()).first()

    if not last_record or last_record.clock_out:
        flash("You must be clocked in before starting a break!", "warning")
        return redirect(url_for('main.dashboard_employee'))

    if last_record.break_start and not last_record.break_end:
        flash("You are already on a break!", "warning")
        return redirect(url_for('main.dashboard_employee'))

    last_record.break_start = datetime.now()
    db.session.commit()
    flash("Break started!", "success")

    return redirect(url_for('main.dashboard_employee'))

@main_bp.route('/end-break')
@login_required
def end_break():
    """Logs the end of an employee's break."""
    last_record = Attendance.query.filter_by(employee_id=current_user.employee_id).order_by(Attendance.id.desc()).first()

    if not last_record or not last_record.break_start:
        flash("You must start a break before ending it!", "warning")
        return redirect(url_for('main.dashboard_employee'))

    if last_record.break_end:
        flash("You have already ended your break!", "warning")
        return redirect(url_for('main.dashboard_employee'))

    last_record.break_end = datetime.now()
    db.session.commit()
    flash("Break ended!", "success")

    return redirect(url_for('main.dashboard_employee'))

# User Manual
@main_bp.route('/manual')
def manual():

    return render_template('manual.html')
