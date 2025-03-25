from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, time
from models.models import db, User, Attendance, Schedule, GlobalSettings, AttendanceInconsistency

# Create a Blueprint for main user routes
main_bp = Blueprint('main', __name__)

def check_attendance_flags(attendance_entry):
    """
    Checks and updates attendance flags based on clock-in and clock-out times.
    Handles late arrivals, early departures, and overtime detection.
    Excludes weekends (Saturday and Sunday).
    """

    # Fetch strict mode setting from the database
    settings = GlobalSettings.query.first()  # Assuming only one settings row exists
    strict_mode = settings.enable_strict_schedule if settings else False

    if not strict_mode:
        return  # Exit function if strict mode is OFF

    if not attendance_entry or not attendance_entry.clock_in:
        return

    today = attendance_entry.clock_in.date()

    # Skip if today is Saturday (5) or Sunday (6)
    if today.weekday() in [5, 6]:
        return

    allowed_late_minutes = 0  # Hardcoded grace period

    # Get user's schedule for the day
    user_schedule = Schedule.query.filter_by(employee_id=attendance_entry.employee_id, day=today.strftime('%A')).first()

    if not user_schedule:
        return  # No schedule found, skip checks

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

    # OVERTIME: Work exceeds scheduled shift + buffer (default 4 hours)
    if attendance_entry.clock_out:
        work_duration = attendance_entry.clock_out - attendance_entry.clock_in
        scheduled_duration = schedule_end - schedule_start
        overtime_threshold = timedelta(hours=4)

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
            flash("ID Not Found!", "danger")

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

    # Get user's schedule for today (normal & broken)
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
        flash("No schedule set for today.", "danger")
        return redirect(url_for('main.dashboard_employee'))

    # Standard allowed early-in time
    allowed_early_in = global_settings.allowed_early_in if global_settings else 0

    # Apply special early-in rule (Weekdays @ 7:30 AM → Extra 30 mins)
    special_early_in = allowed_early_in  # Default: Normal early-in
    if today in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        for schedule in user_schedules:
            if schedule.start_time == time(7, 30):  # Check if schedule is 7:30 AM
                special_early_in += 30  # Add 30 minutes (Total: Early-in + 30 min)

    # Detect if user has a second shift
    has_second_shift = any(sched.is_broken and sched.second_start_time and sched.second_end_time for sched in user_schedules)

    # Validate clock-in time
    valid_schedule = None
    is_second_shift = False

    for schedule in user_schedules:
        earliest_clock_in_time = (datetime.combine(datetime.today(), schedule.start_time) - timedelta(minutes=special_early_in)).time()

        if earliest_clock_in_time <= now <= schedule.end_time:
            valid_schedule = schedule
            break

        if schedule.is_broken and schedule.second_start_time and schedule.second_end_time:
            earliest_second_clock_in_time = (datetime.combine(datetime.today(), schedule.second_start_time) - timedelta(minutes=allowed_early_in)).time()
            if earliest_second_clock_in_time <= now <= schedule.second_end_time:
                valid_schedule = schedule
                is_second_shift = True
                break

    # Get today's clock-ins
    total_clock_ins_today = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        Attendance.clock_in >= datetime.combine(datetime.today(), datetime.min.time())
    ).count()

    active_shifts = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        Attendance.clock_in >= datetime.combine(datetime.today(), datetime.min.time()),
        Attendance.clock_out == None
    ).all()

    # Max clock-in rule for strict schedule
    if global_settings and global_settings.enable_strict_schedule and total_clock_ins_today >= 2:
        flash("Maximum of two clock-ins allowed per day!", "danger")
        return redirect(url_for('main.dashboard_employee'))

    # Prevent duplicate clock-in for the same shift
    for shift in active_shifts:
        if valid_schedule:
            if not is_second_shift and valid_schedule.start_time <= shift.clock_in.time() <= valid_schedule.end_time:
                flash("You are already on duty for this shift! Please clock out before clocking in again.", "warning")
                return redirect(url_for('main.dashboard_employee'))

            if is_second_shift and shift.clock_in.time() >= valid_schedule.second_start_time and shift.clock_out is None:
                flash("You already clocked in for your second shift! Please clock out before clocking in again.", "warning")
                return redirect(url_for('main.dashboard_employee'))

    # Prevent triple clock-in
    if len(active_shifts) >= 2 and has_second_shift:
        flash("You cannot clock in more than twice in a day!", "danger")
        return redirect(url_for('main.dashboard_employee'))

    # Enforce strict schedule
    if global_settings and global_settings.enable_strict_schedule and not valid_schedule:
        flash("You can only clock in during your scheduled shift!", "warning")
        return redirect(url_for('main.dashboard_employee'))

    # Create a new attendance record
    new_entry = Attendance(employee_id=current_user.employee_id, clock_in=datetime.now())
    check_attendance_flags(new_entry)
    db.session.add(new_entry)
    db.session.commit()
    
    return redirect(url_for('main.dashboard_employee', clocked_in=1))

@main_bp.route('/clock-out')
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

    # Get ALL schedules for today (including second shift)
    today_day = today.strftime("%A")
    user_schedules = Schedule.query.filter_by(employee_id=current_user.employee_id, day=today_day).all()

    # Default clock-out time: Now
    actual_clock_out = now

    if strict_schedule and user_schedules:
        # Detect if this is a second shift
        is_second_shift = False
        schedule_end = None

        for schedule in user_schedules:
            if last_record.clock_in.time() >= schedule.start_time and last_record.clock_in.time() <= schedule.end_time:
                schedule_end = datetime.combine(today, schedule.end_time)
                break  # First shift found, stop here

            # If there is a broken schedule (second shift)
            if schedule.is_broken and schedule.second_start_time and schedule.second_end_time:
                if last_record.clock_in.time() >= schedule.second_start_time and last_record.clock_in.time() <= schedule.second_end_time:
                    schedule_end = datetime.combine(today, schedule.second_end_time)
                    is_second_shift = True
                    break  # Second shift found, stop here

        if schedule_end:
            time_limit = schedule_end + timedelta(minutes=30)  # ⏳ 30-minute grace period

            # Block clock-out if more than 30 minutes past scheduled end time
            if actual_clock_out > time_limit:
                flash("Clock-out denied! More than 30 minutes past your scheduled end time.", "danger")
                return redirect(url_for('main.dashboard_employee'))

            # If between schedule end and 7:30 PM, force clock-out to schedule end
            time_730pm = datetime.combine(today, time(19, 30))  # 7:30 PM cutoff
            if schedule_end < actual_clock_out < time_730pm:
                last_record.clock_out = schedule_end
            else:
                last_record.clock_out = actual_clock_out  # Normal clock-out

        else:
            # No schedule found → Allow normal clock-out
            last_record.clock_out = actual_clock_out

    else:
        # No strict schedule → Allow clock-out anytime
        last_record.clock_out = actual_clock_out

    db.session.commit()

    # Check attendance flags (Overtime, etc.)
    check_attendance_flags(last_record)

    # Redirect with `clocked_out=1` parameter
    return redirect(url_for('main.dashboard_employee', clocked_out=1))

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
