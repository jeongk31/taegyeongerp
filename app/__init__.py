from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
import os

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database configuration with connection pooling and IPv4 support
    db_url = os.getenv('SUPABASE_DB_URL', 'sqlite:///erp.db')

    # Add connection arguments for PostgreSQL to handle timeouts and pooling
    if db_url.startswith('postgresql://'):
        # Add connection pool settings for better stability
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 5,
            'pool_recycle': 300,
            'pool_pre_ping': True,
            'connect_args': {
                'connect_timeout': 10,
                'options': '-c statement_timeout=60000'
            }
        }

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '로그인이 필요합니다.'

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy', 'message': 'Application is running'}, 200

    # Error handlers
    @app.errorhandler(500)
    def internal_error(error):
        print(f"500 Internal Server Error: {error}", flush=True)
        import traceback
        traceback.print_exc()
        return f"Internal Server Error: {error}", 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        print(f"Unhandled exception: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return f"An error occurred: {e}", 500

    # Create tables (with error handling)
    try:
        with app.app_context():
            print("Attempting to create database tables...", flush=True)
            db.create_all()
            print("Database tables created successfully", flush=True)
    except Exception as e:
        print(f"WARNING: Could not create tables on startup: {e}", flush=True)
        print("Tables may already exist or database may not be accessible", flush=True)

    return app
