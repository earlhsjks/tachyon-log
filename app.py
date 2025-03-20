import os
from datetime import timedelta, datetime, timezone
import logging

from flask import Flask, session, render_template
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from flask_migrate import Migrate
from sqlalchemy.exc import OperationalError
from waitress import serve

from models.models import db, User, GlobalSettings
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Ensure session storage directory exists
os.makedirs("./flask_session", exist_ok=True)
app.config['SESSION_TYPE'] = 'filesystem'  # Store session data in files
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)  # Auto logout after 10 minutes
app.config['SESSION_FILE_DIR'] = "./flask_session"
Session(app)

# Initialize database and migration
db.init_app(app)
migrate = Migrate(app, db)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "main.login_employee"

# Session timeout enforcement
@app.before_request
def session_timeout():
    session.modified = True
    session.permanent = True

    # Ensure session['last_activity'] exists and is stored as an ISO string
    if 'last_activity' not in session or not isinstance(session['last_activity'], str):
        session['last_activity'] = datetime.now(timezone.utc).isoformat()  # Store as ISO string
        return

    try:
        last_activity = datetime.fromisoformat(session['last_activity'])  # Convert back to datetime
        
        # Ensure it's timezone-aware
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)
    
    except (ValueError, TypeError):  # Handle invalid or corrupted session values
        last_activity = datetime.now(timezone.utc)

    elapsed = datetime.now(timezone.utc) - last_activity

    if elapsed > app.config['PERMANENT_SESSION_LIFETIME']:
        session.clear()

    session['last_activity'] = datetime.now(timezone.utc).isoformat()  # Store as ISO string

# Register Blueprints
from routes.main import main_bp
from routes.admin import admin_bp
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp, url_prefix='/admin')

# Error handling
@app.errorhandler(OperationalError)
def maintenance_mode(e):
    logging.error(f"Database Error: {str(e)}")
    return render_template("maintenance.html"), 503

# User loader for Flask-Login
@login_manager.user_loader
def load_user(employee_id):
    return db.session.get(User, employee_id)

# Database initialization (to be run separately in setup scripts)
def initialize_database():
    with app.app_context():
        db.create_all()
        
        existing_admin = db.session.execute(
            db.select(User).filter_by(employee_id="admin")
        ).scalar_one_or_none()
        
        if not existing_admin:
            superadmin = User(
                employee_id="superadmin",
                username="SuperAdmin",
                password=generate_password_hash("letmein"),
                role="superadmin"
            )
            admin = User(
                employee_id="admin",
                username="Admin",
                password=generate_password_hash("admin123"),
                role="admin"
            )
            db.session.add_all([superadmin, admin])
            db.session.commit()
            logging.info("SuperAdmin and Admin accounts created.")

# Run Flask App
if __name__ == '__main__':
    logging.info("Starting Flask App...")
    serve(app, host='0.0.0.0', port=80)
