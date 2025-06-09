from flask import (Blueprint, render_template, redirect, url_for, request, flash, 
                   send_file, session)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
import pandas as pd
import io
from collections import defaultdict
from datetime import datetime, timedelta
from models.models import db, User, Attendance, Schedule, GlobalSettings, Logs, AttendanceInconsistency
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text, or_

# Create a Blueprint for admin routes
admin_bp = Blueprint('admin', __name__)

@admin_bp.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

# Funtion of udate user schedule
def parse_time(time_str):
    """Convert string to time object, return None if empty or invalid."""
    if not time_str or time_str.strip() == "":  # Ensure empty strings return None
        return None
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        return None  # Handle incorrect formats safely

def log_entry(admin_id, action, details=None):
    log_entry = Logs(
        admin_id=admin_id,
        action=action,
        details=details,
        timestamp=datetime.now()
    )

    db.session.add(log_entry)
    db.session.commit()

# Admin Login
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        password = request.form.get('password')

        # Corrected filter condition to check both roles properly
        user = User.query.filter(
            User.employee_id == employee_id,
            or_(User.role == "admin", User.role == "superadmin")
        ).first()

        if user and check_password_hash(user.password, password):
            login_user(user)        

            return redirect(url_for("admin.admin_dashboard"))
        else:
            flash("Invalid Credentials. Please try again.", "danger")

    return render_template('auth/admin.html')    

# Auto Logout
@admin_bp.route('/logout')
def logout():
    logout_user()  # Logs out the user
    session.clear()  # Clears session data
    return render_template('auth/admin.html')  # Redirect to login page

# Dashboard
@admin_bp.route('/dashboard')
@login_required
def admin_dashboard():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')

    # Exclude superadmin from statistics
    total_employees = User.query.filter(User.role != "superadmin").count()

    # Today's Date
    today = datetime.now().date()

    # Fetch on-duty employees (clocked in today, not clocked out)
    on_duty_today_list = (
        db.session.query(
            User.employee_id,
            User.last_name,
            Attendance.clock_in
        )
        .join(Attendance, Attendance.employee_id == User.employee_id)
        .filter(
            Attendance.clock_out.is_(None),
            db.func.date(Attendance.clock_in) == today  # Only today
        )
        .all()
    )

    # Fetch employees who forgot to clock out (previous days)
    forgot_to_clock_out_list = (
        db.session.query(
            User.employee_id,
            User.last_name,
            Attendance.clock_in
        )
        .join(Attendance, Attendance.employee_id == User.employee_id)
        .filter(
            Attendance.clock_out.is_(None),
            db.func.date(Attendance.clock_in) < today  # Before today
        )
        .all()
    )

    # Fetch attendance inconsistencies
    late_employees = (
        AttendanceInconsistency.query.filter_by(issue_type="Late", date=today).count()
    )
    early_out_employees = (
        AttendanceInconsistency.query.filter_by(issue_type="Early Out", date=today).count()
    )
    overtime_employees = (
        AttendanceInconsistency.query.filter_by(issue_type="Overtime", date=today).count()
    )

    # Employees who are absent based on schedule
    all_users = User.query.filter(User.role != "superadmin").all()
    present_users = [att.employee_id for att in Attendance.query.filter(Attendance.clock_in.isnot(None)).all()]
    absent_employees = AttendanceInconsistency.query.filter_by(issue_type="Absent", date=today).count()

    # Fetch attendance inconsistencies and map them by employee_id and date
    inconsistencies = {}
    inconsistency_records = AttendanceInconsistency.query.all()

    for record in inconsistency_records:
        date_str = record.date.strftime('%Y-%m-%d')  # Ensure proper format
        if record.employee_id not in inconsistencies:
            inconsistencies[record.employee_id] = {}
        if date_str not in inconsistencies[record.employee_id]:
            inconsistencies[record.employee_id][date_str] = []
        inconsistencies[record.employee_id][date_str].append(record.issue_type)

    return render_template(
        'admin/dashboard.html',
        user=current_user,
        total_employees=total_employees,
        late_employees=late_employees,
        early_out_employees=early_out_employees,
        overtime_employees=overtime_employees,
        absent_employees=absent_employees,
        on_duty_today_list=on_duty_today_list,
        forgot_to_clock_out_list=forgot_to_clock_out_list,
        current_time=datetime.now().time(),
        inconsistencies=inconsistencies
    )

@admin_bp.route('/force-clock-out/<string:employee_id>', methods=['POST'])
@login_required
def force_clock_out(employee_id):
    """Allows admins to forcibly clock out an employee, ensuring schedule end time is logged if applicable."""
    
    # Only superadmin or admin can use this
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized access!", "danger")
        return render_template('auth/admin.html')

    # Get the latest active attendance record
    attendance = Attendance.query.filter(
        Attendance.employee_id == employee_id,
        Attendance.clock_out.is_(None)  # Only employees still on duty
    ).order_by(Attendance.clock_in.desc()).first()

    if not attendance:
        flash("Employee is not currently on duty!", "danger")
        return redirect(url_for("admin.dashboard"))

    # Get the employee's schedule for today
    today_day = datetime.today().strftime("%A")
    schedule = Schedule.query.filter_by(employee_id=employee_id, day=today_day).first()

    # Default clock-out time is now
    actual_clock_out = datetime.now()

    if schedule:
        schedule_end = datetime.combine(actual_clock_out.date(), schedule.end_time)

        # If admin forces clock-out **after** scheduled end time → log schedule end instead
        if actual_clock_out >= schedule_end:
            attendance.clock_out = schedule_end
        else:
            attendance.clock_out = actual_clock_out  # Normal clock-out
    else:
        # No schedule found → log the actual clock-out time
        attendance.clock_out = actual_clock_out

    db.session.commit()

    # Log the action
    log_entry = Logs(
        admin_id=current_user.employee_id,
        action=f"Force Clocked Out {employee_id}",
        details=f"Clock-out set to {attendance.clock_out.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    db.session.add(log_entry)
    db.session.commit()

    flash("Employee successfully clocked out!", "success")
    return redirect(url_for("admin.admin_dashboard"))  # Redirect back to dashboard

# Admin Attendance
@admin_bp.route('/attendance-records', methods=['GET', 'POST'])
@login_required
def admin_attendance():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized Access!", "danger")
        return render_template('auth/admin.html')

    # Ensure `month` is properly formatted
    month = request.args.get('month', '').strip()

    if not month or '-' not in month:  # Handle missing or incorrect format
        month = datetime.today().strftime('%Y-%m')  # Default to current month

    try:
        year, month = map(int, month.split('-'))  # Convert to integers
    except ValueError:
        flash("Invalid month format. Please select a valid month.", "danger")
        return redirect(url_for('admin.admin_attendance'))

    # Query attendance records for the selected month
    attendance_records = db.session.query(
        User.first_name,
        User.last_name,
        Attendance.employee_id,
        Attendance.clock_in,
        Attendance.clock_out
    ).join(User).filter(
        db.extract('year', Attendance.clock_in) == year,
        db.extract('month', Attendance.clock_in) == month
    ).order_by(Attendance.clock_in.desc()).all()

    # Fetch attendance inconsistencies for the selected month
    inconsistency_records = AttendanceInconsistency.query.filter(
        db.extract('year', AttendanceInconsistency.date) == year,
        db.extract('month', AttendanceInconsistency.date) == month
    ).all()

    # Process inconsistencies into a dictionary (indexed by employee_id & date)
    inconsistencies = {}
    for record in inconsistency_records:
        date_str = record.date.strftime('%Y-%m-%d')  # Format properly
        if record.employee_id not in inconsistencies:
            inconsistencies[record.employee_id] = {}
        if date_str not in inconsistencies[record.employee_id]:
            inconsistencies[record.employee_id][date_str] = []
        inconsistencies[record.employee_id][date_str].append(record.issue_type)

    # Pass the data to the template
    return render_template(
        'admin/attendance_records.html',
        user=current_user,  # Ensure `user` is available in the template
        attendance=attendance_records,
        inconsistencies=inconsistencies,
        current_month=f"{year}-{month:02d}",
        datetime=datetime
    )

# View Employee Management Page
@admin_bp.route('/users')
@login_required
def admin_employees():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')

    users = db.session.scalars(db.select(User)).all()
    users = User.query.filter(User.role != "superadmin").all()

    return render_template('admin/users.html', users=users)

# Edit User (Loads the Edit Page)
@admin_bp.route('/edit_user/<string:employee_id>', methods=['GET'])
@login_required
def edit_user(employee_id):
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')

    user = User.query.get_or_404(employee_id)

    # Get all schedules for the user (including broken ones)
    schedules = Schedule.query.filter_by(employee_id=user.employee_id).all()

    # Separate normal and broken schedules
    schedule_dict = {}  # Stores normal schedules
    broken_schedules = []  # Stores broken schedules

    for sched in schedules:
        if sched.is_broken:
            broken_schedules.append(sched)
        else:
            schedule_dict[sched.day] = sched

    return render_template(
        "admin/edit_user.html",
        user=user,
        schedule=schedule_dict,
        broken_schedules=broken_schedules  # Pass broken shifts separately
    )

# Update User & Schedule
@admin_bp.route('/update-user/<string:employee_id>', methods=['POST'])
@login_required
def update_user(employee_id):
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')

    user = User.query.get_or_404(employee_id)
    
    new_employee_id_list = request.form.getlist('employee_id')
    new_employee_id = new_employee_id_list[-1] if new_employee_id_list else user.employee_id

    # Get and process name fields
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip().upper()
    if middle_name:
        if not middle_name.endswith('.'):
            middle_name += '.'
    else:
        middle_name = None

    role = request.form.get('role')

    old_employee_id = user.employee_id
    old_role = user.role

    # Update user fields
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name
    user.middle_name = middle_name
    if role:
        user.role = role

    try:
        changes = []

        # Step 1: Check if employee ID needs to change
        if new_employee_id and new_employee_id != old_employee_id:
            existing_user = User.query.get(new_employee_id)
            if existing_user:
                flash("Employee ID already exists! Choose a different one.", "danger")
                return redirect(url_for('admin.update_user', employee_id=old_employee_id))

            # Step 2: Update the User's employee_id first
            db.session.execute(
                text("UPDATE users SET employee_id = :new_id WHERE employee_id = :old_id"),
                {"new_id": new_employee_id, "old_id": old_employee_id}
            )

            # Step 3: Update foreign keys in related tables
            db.session.execute(
                text("UPDATE schedule SET employee_id = :new_id WHERE employee_id = :old_id"),
                {"new_id": new_employee_id, "old_id": old_employee_id}
            )
            db.session.execute(
                text("UPDATE attendance SET employee_id = :new_id WHERE employee_id = :old_id"),
                {"new_id": new_employee_id, "old_id": old_employee_id}
            )
            db.session.execute(
                text("UPDATE logs SET admin_id = :new_id WHERE admin_id = :old_id"),
                {"new_id": new_employee_id, "old_id": old_employee_id}
            )

            changes.append(f"Changed Employee ID from {old_employee_id} to {new_employee_id}")

        # Step 4: Normal Schedule Update
        for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
            start_time = request.form.get(f"{day.lower()}_start")
            end_time = request.form.get(f"{day.lower()}_end")

            start_time = parse_time(start_time) if start_time else None
            end_time = parse_time(end_time) if end_time else None

            if start_time and end_time:
                schedule = Schedule.query.filter_by(employee_id=new_employee_id, day=day, is_broken=False).first()
                if not schedule:
                    schedule = Schedule(employee_id=new_employee_id, day=day, is_broken=False)
                    db.session.add(schedule)

                if schedule.start_time != start_time or schedule.end_time != end_time:
                    changes.append(f"Updated {day} schedule: {schedule.start_time} - {schedule.end_time} → {start_time} - {end_time}")

                schedule.start_time = start_time
                schedule.end_time = end_time

        # Step 5: Broken Schedule Update
        days = request.form.getlist("day[]")
        second_start_times = request.form.getlist("second_start_time[]")
        second_end_times = request.form.getlist("second_end_time[]")

        # Remove old broken schedules to prevent duplicates
        Schedule.query.filter_by(employee_id=new_employee_id, is_broken=True).delete()

        for day, second_start, second_end in zip(days, second_start_times, second_end_times):
            if second_start and second_end:
                new_schedule = Schedule(
                    employee_id=new_employee_id,
                    day=day,
                    is_broken=True,
                    second_start_time=parse_time(second_start),
                    second_end_time=parse_time(second_end),
                    start_time=parse_time("00:00"),
                    end_time=parse_time("00:00")
                )
                db.session.add(new_schedule)

                changes.append(f"Added broken schedule for {day}: {second_start} - {second_end}")

        db.session.commit()

        # Log the changes
        if changes:
            log_entry = Logs(
                admin_id=current_user.employee_id,
                action=f"Updated User {new_employee_id}",
                details="; ".join(changes)
            )
            db.session.add(log_entry)
            db.session.commit()

        flash("User updated successfully!", "success")

    except IntegrityError as e:
        db.session.rollback()
        flash(f"Database Integrity Error: {str(e)}", "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating user: {str(e)}", "danger")

    return redirect(url_for('admin.admin_employees'))

# Add New User
@admin_bp.route('/add-user', methods=['POST'])
@login_required
def add_user():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')

    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip().upper()
    if middle_name:
        if not middle_name.endswith('.'):
            middle_name += '.'
    else:
        middle_name = None
    employee_id = request.form.get('employee_id')
    role = request.form.get('role')

    if User.query.filter_by(employee_id=employee_id).first():
        flash("Employee ID already exists!", "danger")
        return redirect(url_for('admin.admin_employees'))

    try:
        new_user = User(
            employee_id=employee_id,
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            role=role
        )

        if role in ["superadmin", "admin", "manager", "employee"]: 
            new_user.set_password("admin123")  # Default password setup

        db.session.add(new_user)
        db.session.commit()

        # Log the user creation
        log_entry = Logs(
            admin_id=current_user.employee_id,
            action=f"Added New User {employee_id}",
            details=f"Created user {first_name} {middle_name or ''} {last_name} ({employee_id}) with role {role}"
        )
        db.session.add(log_entry)
        db.session.commit()

        flash("User added successfully!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error adding user: {str(e)}", "danger")

    return redirect(url_for('admin.admin_employees'))

# Delete User
@admin_bp.route('/delete-user/<string:employee_id>', methods=['POST'])
@login_required
def delete_user(employee_id):
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')
    
    user = User.query.get_or_404(employee_id)

    if user.role == "admin" and user.employee_id == "admin":
        flash("You cannot delete the built-in Admin account!", "danger")
        return redirect(url_for('admin.edit_user', employee_id=user.employee_id))

    try:
        # Delete related attendance records
        Attendance.query.filter_by(employee_id=user.employee_id).delete()
        
        # Delete the user
        db.session.delete(user)
        db.session.commit()

        # Log the deletion
        log_entry = Logs(
            admin_id=current_user.employee_id,
            action=f"Deleted User {employee_id}",
            details=f"Removed user {user.first_name} {user.middle_name or ''} {user.last_name} ({employee_id}) with role {user.role}"
        )
        db.session.add(log_entry)
        db.session.commit()

        flash("User deleted successfully!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting user: {str(e)}", "danger")

    return redirect(url_for('admin.admin_employees'))

# Specific User Attendance
@admin_bp.route('/user-logs/<string:employee_id>', methods=['GET'])
@login_required
def view_user_logs(employee_id):
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized Access!", "danger")
        return render_template('auth/admin.html')

    month = request.args.get('month')  # Use GET instead of POST to match filter form

    user = User.query.get_or_404(employee_id)

    if month:
        try:
            year, month = map(int, month.split('-'))
        except ValueError:
            flash("Invalid date format.", "danger")
            return redirect(url_for('admin.view_user_logs', employee_id=employee_id))
    else:
        today = datetime.today()
        year, month = today.year, today.month

    # Fetch attendance records for the selected employee and month
    attendance_records = Attendance.query.filter(
        Attendance.employee_id == employee_id,
        db.extract('year', Attendance.clock_in) == year,
        db.extract('month', Attendance.clock_in) == month
    ).all()

    # Fetch inconsistencies for the selected employee and month
    inconsistency_records = AttendanceInconsistency.query.filter(
        AttendanceInconsistency.employee_id == employee_id,
        db.extract('year', AttendanceInconsistency.date) == year,
        db.extract('month', AttendanceInconsistency.date) == month
    ).all()

    # Properly map inconsistencies by employee_id and date
    inconsistencies = {}
    for record in inconsistency_records:
        date_str = record.date.strftime('%Y-%m-%d')
        if employee_id not in inconsistencies:
            inconsistencies[employee_id] = {}
        if date_str not in inconsistencies[employee_id]:
            inconsistencies[employee_id][date_str] = []
        inconsistencies[employee_id][date_str].append(record.issue_type)

    return render_template(
        'admin/user_attendance.html',
        user=user,
        attendance=attendance_records or [],
        inconsistencies=inconsistencies,
        employee_id=employee_id,
        current_month=f"{year}-{month:02d}"  # Ensure correct formatting
    )

# Edit Attendance Logs
@admin_bp.route('/edit-attendance', methods=['POST'])
@login_required
def edit_attendance():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized Access!", "danger")
        return render_template('auth/admin.html')

    record_id = request.form.get('save')  # Get the record ID from the button
    if not record_id:
        flash("Invalid request!", "danger")
        return redirect(request.referrer)

    attendance = Attendance.query.get_or_404(record_id)

    try:
        clock_in = request.form.get(f'clock_in_{record_id}')
        clock_out = request.form.get(f'clock_out_{record_id}')

        # Preserve the existing date
        existing_date = attendance.clock_in.date() if attendance.clock_in else datetime.today().date()

        changes = []  # To store log details

        # Update clock-in with the same date
        if clock_in:
            clock_in_time = datetime.strptime(clock_in, "%H:%M").time()
            new_clock_in = datetime.combine(existing_date, clock_in_time)
            if attendance.clock_in != new_clock_in:
                changes.append(f"Clock-In changed from {attendance.clock_in.strftime('%H:%M')} to {clock_in}")
                attendance.clock_in = new_clock_in

        # Update clock-out with the same date
        if clock_out:
            clock_out_time = datetime.strptime(clock_out, "%H:%M").time()
            new_clock_out = datetime.combine(existing_date, clock_out_time)
            if attendance.clock_out != new_clock_out:
                changes.append(f"Clock-Out changed from {attendance.clock_out.strftime('%H:%M') if attendance.clock_out else 'N/A'} to {clock_out}")
                attendance.clock_out = new_clock_out

        db.session.commit()

        # Log the attendance update
        if changes:
            log_entry = Logs(
                admin_id=current_user.employee_id,
                action=f"Edited Attendance Record {record_id}",
                details=" | ".join(changes)
            )
            db.session.add(log_entry)
            db.session.commit()

        flash("Attendance record updated successfully!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error updating record: {e}", "danger")

    return redirect(request.referrer)

@admin_bp.route('/add-attendance-entry', methods=['POST'])
@login_required
def add_attendance_entry():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized Access!", "danger")
        return render_template('auth/admin.html')

    employee_id = request.form.get('employee_id')
    date_str = request.form.get('date')
    clock_in_str = request.form.get('clock_in')
    clock_out_str = request.form.get('clock_out')

    try:
        clock_in = datetime.strptime(f"{date_str} {clock_in_str}", "%Y-%m-%d %H:%M")
        clock_out = datetime.strptime(f"{date_str} {clock_out_str}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        flash("Invalid date or time format.", "danger")
        return redirect(url_for('admin.view_user_logs', employee_id=employee_id))

    # Save the new attendance entry
    new_attendance = Attendance(
        employee_id=employee_id,
        clock_in=clock_in,
        clock_out=clock_out
    )
    db.session.add(new_attendance)
    db.session.commit()

    flash("New attendance entry added successfully.", "success")
    return redirect(url_for('admin.view_user_logs', employee_id=employee_id))

@admin_bp.route('/delete-attendance-entry', methods=['POST'])
@login_required
def delete_attendance_entry():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized Access!", "danger")
        return render_template('auth/admin.html')

    record_id = request.form.get('record_id')
    attendance = Attendance.query.get(record_id)
    if not attendance:
        flash("Attendance entry not found.", "danger")
        return redirect(request.referrer or url_for('admin.admin_employees'))

    try:
        db.session.delete(attendance)
        db.session.commit()

        # Log the deletion
        log_entry = Logs(
            admin_id=current_user.employee_id,
            action=f"Deleted Attendance Record {record_id}",
            details=f"Deleted attendance entry for employee {attendance.employee_id} on {attendance.clock_in.strftime('%Y-%m-%d') if attendance.clock_in else 'N/A'}"
        )
        db.session.add(log_entry)
        db.session.commit()

        flash("Attendance entry deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting attendance entry: {e}", "danger")

    return redirect(request.referrer or url_for('admin.admin_employees'))
  
# Account Settings (Change Password)
@admin_bp.route('/account-settings', methods=['GET', 'POST'])
@login_required
def account_settings():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # Validate current password
        if not check_password_hash(current_user.password, current_password):
            flash("Current password is incorrect!", "danger")
            return redirect(url_for('admin.account_settings'))

        # Check if new passwords match
        if new_password != confirm_password:
            flash("New passwords do not match!", "danger")
            return redirect(url_for('admin.account_settings'))

        # Enforce password strength
        if len(new_password) < 8 or not any(char.isdigit() for char in new_password):
            flash("Password must be at least 8 characters long and contain a number!", "danger")
            return redirect(url_for('admin.account_settings'))

        try:
            # Hash and update password
            current_user.password = generate_password_hash(new_password)
            db.session.commit()

            # Log the password change
            log_entry = Logs(
                admin_id=current_user.employee_id,
                action="Updated Account Password",
                details="Password changed successfully."
            )
            db.session.add(log_entry)
            db.session.commit()

            flash("Password updated successfully!", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating password: {e}", "danger")

    return render_template('admin/account_settings.html')

# Global Settings
@admin_bp.route('/settings', methods=["GET", "POST"])
@login_required
def settings():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Access Denied!", "danger")
        return render_template('auth/admin.html')

    settings = GlobalSettings.query.first()

    if not settings:
        settings = GlobalSettings()
        db.session.add(settings)
        db.session.commit()  # Save new settings immediately

    if request.method == "POST":
        try:
            # Update boolean settings
            settings.enable_strict_schedule = request.form.get("enable_strict_schedule") == "on"
            settings.early_out_allowed = request.form.get("early_out_allowed") == "on"
            settings.overtime_allowed = request.form.get("overtime_allowed") == "on"

            # Update time-based settings
            default_start_time = request.form.get("default_schedule_start")
            default_end_time = request.form.get("default_schedule_end")
            settings.default_schedule_start = datetime.strptime(default_start_time, "%H:%M").time() if default_start_time else None
            settings.default_schedule_end = datetime.strptime(default_end_time, "%H:%M").time() if default_end_time else None

            # Update early-in allowance (ensure it's an integer)
            allowed_early_in = request.form.get("allowed_early_in")
            settings.allowed_early_in = int(allowed_early_in) if allowed_early_in else 0

            db.session.commit()

            # Log the update
            log_entry = Logs(
                admin_id=current_user.employee_id,
                action="Updated Global Settings",
                details=f"Strict Schedule: {settings.enable_strict_schedule}, Early Out: {settings.early_out_allowed}, Overtime: {settings.overtime_allowed}"
            )
            db.session.add(log_entry)
            db.session.commit()

            flash("Settings updated successfully!", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error saving settings: {e}", "danger")

        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", settings=settings)

# Route to View Logs
@admin_bp.route('/logs', methods=['GET', 'POST'])
@login_required
def view_logs():
    if current_user.role not in ["superadmin", "admin"]:
        flash("Unauthorized access!", "danger")
        return render_template('auth/admin.html')

    # Get page and rows_per_page from args or form
    page = int(request.args.get('page', 1))
    if request.method == 'POST':
        rows_per_page = int(request.form.get('rows_per_page', 25))
        log_date = request.form.get('log_date', '')
    else:
        rows_per_page = int(request.args.get('rows_per_page', 25))
        log_date = request.args.get('log_date', '')

    # Join with User model and exclude logs from superadmins
    query = Logs.query.join(User, User.employee_id == Logs.admin_id).filter(User.role != 'superadmin').order_by(Logs.timestamp.desc())

    if log_date:
        try:
            selected_date = datetime.strptime(log_date, "%Y-%m-%d").date()
            query = query.filter(db.func.date(Logs.timestamp) == selected_date)
        except ValueError:
            pass

    total_logs = query.count()
    logs = query.offset((page - 1) * rows_per_page).limit(rows_per_page).all()

    return render_template(
        'admin/system_logs.html',
        logs=logs,
        rows_per_page=rows_per_page,
        page=page,
        total_logs=total_logs,
        log_date=log_date
    )

# DTR Print
@admin_bp.route('/export-pdf')
@login_required
def export_pdf():
    if current_user.role not in ["superadmin", "admin"]:
        return render_template('auth/admin.html')

    # Ensure selected_month is valid, otherwise default to current month
    selected_month = request.args.get('month', '').strip() or datetime.today().strftime('%Y-%m')

    if not selected_month or '-' not in selected_month:
        selected_month = datetime.today().strftime('%Y-%m')  # Default to current month

    try:
        year, month = map(int, selected_month.split('-'))  # Convert to integers
    except ValueError:
        flash("Invalid month format. Defaulting to current month.", "warning")
        return redirect(url_for('admin.export_pdf', month=datetime.today().strftime('%Y-%m')))

    first_day = datetime(year, month, 1)
    last_day = (first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    total_days = last_day.day

    # Exclude "superadmin" and "admin" roles
    users = User.query.filter(User.role.notin_(["superadmin", "admin"])).order_by(User.employee_id).all()

    # Fetch attendance records for the selected month
    attendance_records = Attendance.query.filter(
        Attendance.clock_in >= first_day,
        Attendance.clock_in < (last_day + timedelta(days=1))
    ).order_by(Attendance.clock_in).all()

    # Dictionary to store attendance data
    attendance_dict = defaultdict(lambda: defaultdict(lambda: {
        "shift1": {"in": None, "out": None}, 
        "shift2": {"in": None, "out": None}
    }))
        
    # Dictionary to store total hours per user (initialized to 0 seconds)
    total_hours_dict = {user.employee_id: 0 for user in users}  

    # Populate attendance records
    for record in attendance_records:
        date_key = record.clock_in.date().strftime('%Y-%m-%d')
        employee_id = record.employee_id

        clock_in_time = record.clock_in
        clock_out_time = record.clock_out if record.clock_out else None
            
        if not attendance_dict[employee_id][date_key]["shift1"]["in"]:
            attendance_dict[employee_id][date_key]["shift1"]["in"] = clock_in_time
            attendance_dict[employee_id][date_key]["shift1"]["out"] = clock_out_time
        elif attendance_dict[employee_id][date_key]["shift1"]["out"] is None:
            # If the first shift has an 'in' but no 'out', update 'out'
            attendance_dict[employee_id][date_key]["shift1"]["out"] = clock_out_time
        else:
            attendance_dict[employee_id][date_key]["shift2"]["in"] = clock_in_time
            attendance_dict[employee_id][date_key]["shift2"]["out"] = clock_out_time
        
    # Calculate total hours per user
    for user in users:
        total_seconds = 0
        if user.employee_id in attendance_dict:
            for date, shifts in attendance_dict[user.employee_id].items():
                for shift in ["shift1", "shift2"]:
                    if shifts[shift]["in"] and shifts[shift]["out"]:
                        total_seconds += (shifts[shift]["out"] - shifts[shift]["in"]).total_seconds()

        # Convert total seconds to HH:MM format
        total_hours = int(total_seconds // 3600)
        total_minutes = int((total_seconds % 3600) // 60)
        total_hours_dict[user.employee_id] = f"{total_hours}:{total_minutes:02d}"

    # Pair users (two per page)
    user_pairs = [users[i:i+2] for i in range(0, len(users), 2)]
    
    return render_template(
        'admin/dtr_report.html', 
        user_pairs=user_pairs, 
        month=month, 
        year=year, 
        total_days=total_days, 
        datetime=datetime,
        attendance_dict=attendance_dict,
        total_hours_dict=total_hours_dict  # Pass total hours data to template
    )

@admin_bp.route('/export-excel')
@login_required
def export_excel():
    if current_user.role not in ["superadmin", "admin"]:
        return render_template('auth/admin.html')

    records = Attendance.Session.scalars().all()
    data = [{"Employee ID": record.employee_id, "Clock In": record.clock_in, "Clock Out": record.clock_out or "N/A"} for record in records]

    df = pd.DataFrame(data)
    excel_file = io.BytesIO()
    with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")

    excel_file.seek(0)
    return send_file(excel_file, as_attachment=True, download_name="attendance_report.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
