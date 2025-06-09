from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash
from datetime import datetime, time

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    employee_id = db.Column(db.String(50), primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    _middle_name = db.Column("middle_name", db.String(50), nullable=True)
    password = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='employee')

    @property
    def middle_name(self):
        return self._middle_name

    @middle_name.setter
    def middle_name(self, value):
        if value:
            value = value.strip()
            if not value.endswith('.'):
                value += '.'
        self._middle_name = value

    def set_password(self, password):
        if password:
            self.password = generate_password_hash(password)

    def get_id(self):
        return str(self.employee_id)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), db.ForeignKey('users.employee_id', ondelete="CASCADE"), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=True)
    clock_out = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='attendance_records')

class Schedule(db.Model):
    __tablename__ = 'schedule'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), db.ForeignKey("users.employee_id", ondelete="CASCADE"), nullable=False)
    day = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_broken = db.Column(db.Boolean, default=False)
    second_start_time = db.Column(db.Time, nullable=True)
    second_end_time = db.Column(db.Time, nullable=True)

class GlobalSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    enable_strict_schedule = db.Column(db.Boolean, default=False)
    auto_clock_out_hours = db.Column(db.Integer, default=10)
    
    early_out_allowed = db.Column(db.Boolean, default=True)
    overtime_allowed = db.Column(db.Boolean, default=False)
    
    default_schedule_start = db.Column(db.Time, default=time(7, 30))
    default_schedule_end = db.Column(db.Time, default=time(20, 30))

    allowed_early_in = db.Column(db.Integer, default=0)
        
    @property
    def default_schedule(self):
        return type('DefaultSchedule', (object,), {
            "start_time": self.default_schedule_start,
            "end_time": self.default_schedule_end
        })()

class AttendanceInconsistency(db.Model):
    __tablename__ = 'attendance_inconsistencies'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), db.ForeignKey("users.employee_id", ondelete="CASCADE"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    issue_type = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)

    user = db.relationship("User", backref="inconsistencies")

class Logs(db.Model):
    __tablename__ = 'logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.String(50), db.ForeignKey('users.employee_id', ondelete="CASCADE"), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False)
    details = db.Column(db.Text, nullable=True)

    admin = db.relationship('User', backref='logs', lazy=True)

    def __repr__(self):
        return f"<Logs {self.action} by {self.admin_id} at {self.timestamp}>"
