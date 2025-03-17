from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, time
from models.models import db, User, Attendance, Schedule, GlobalSettings

# Create a Blueprint for main user routes
main_bp = Blueprint('main', __name__)

def check_attendance_flags(attendance_entry):
    """
    Checks attendance flags and updates the database if needed.
    This function should handle late flags, overtime flags, etc.
    """
    if not attendance_entry:
        return

    # Example: Set 'late' flag if clock-in is after 9:00 AM
    if attendance_entry.clock_in.hour > 9:
        attendance_entry.late = True

    # Example: Set 'overtime' flag if work is more than 8 hours
    if attendance_entry.clock_out and (attendance_entry.clock_out - attendance_entry.clock_in).seconds > 8 * 3600:
        attendance_entry.overtime = True
        
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

    attendance_records = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        db.extract('year', Attendance.clock_in) == year,
        db.extract('month', Attendance.clock_in) == month
    ).all()

    return render_template(
        'dashboard_employee.html',
        name=current_user.username,
        attendance_records=attendance_records,  # Pass the correct variable
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

@main_bp.route('/clock-out')
@login_required
def clock_out():
    # Get today's clock-in record (First clock-in of the day)
    last_record = Attendance.query.filter(
        Attendance.employee_id == current_user.employee_id,
        Attendance.clock_in != None,
        Attendance.clock_in >= datetime.combine(datetime.today(), datetime.min.time()),  # Only today
        Attendance.clock_out == None  # Ensure they haven’t clocked out yet
    ).order_by(Attendance.id.asc()).first()  # Get the earliest clock-in of the day

    if not last_record:
        flash("No active clock-in found for today!", "error")
        return redirect(url_for('main.dashboard_employee'))

    # Get the user's schedule for today
    today_day = datetime.today().strftime("%A")
    schedule = Schedule.query.filter_by(employee_id=current_user.employee_id, day=today_day).first()

    # Default clock-out time: Now
    actual_clock_out = datetime.now()
    time_730pm = datetime.combine(actual_clock_out.date(), time(19, 30))  # 7:30 PM rule

    if schedule:
        schedule_end = datetime.combine(actual_clock_out.date(), schedule.end_time)
        time_limit = schedule_end + timedelta(minutes=30)  # ⏳ 30-minute grace period

        # **Block clock-out if more than 30 minutes late**
        if actual_clock_out > time_limit:
            flash("Clock-out denied! More than 30 minutes past your scheduled end time.", "error")
            return redirect(url_for('main.dashboard_employee'))

        # If between schedule end and 7:30 PM, force clock-out to schedule end
        if schedule_end < actual_clock_out < time_730pm:
            last_record.clock_out = schedule_end
        else:
            last_record.clock_out = actual_clock_out  # Normal clock-out

    else:
        # If no schedule, allow normal clock-out
        last_record.clock_out = actual_clock_out

    db.session.commit()

    # Check attendance flags (Overtime)
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
