from flask import Flask, session, render_template
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from models.models import db, User, GlobalSettings
from datetime import timedelta, datetime
from flask_migrate import Migrate
from sqlalchemy.exc import OperationalError
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

app.config['SESSION_TYPE'] = 'filesystem'  # Store session data in files
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)  # Auto logout after 10 minutes
app.config['SESSION_FILE_DIR'] = "./flask_session"  # Ensure session storage

Session(app)

@app.before_request
def session_timeout():
    session.modified = True
    
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "main.login_employee"

from routes.main import main_bp
from routes.admin import admin_bp
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp,  url_prefix='/admin')

@app.errorhandler(OperationalError)
def maintenance_mode(e):
    return render_template("maintenance.html"), 503

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
            role="admin123"
        )

        db.session.add_all([superadmin, admin])
        db.session.commit()

# Load User for Flask-Login
@login_manager.user_loader
def load_user(employee_id):
    return User.query.get(employee_id)

# Run Flask App
if __name__ == '__main__':
    from waitress import serve
    app.run(host='0.0.0.0', port=8443, debug=True)
