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

    # Request logging middleware
    @app.before_request
    def log_request():
        from flask import request
        print(f"REQUEST: {request.method} {request.path}", flush=True)

    @app.after_request
    def log_response(response):
        from flask import request
        print(f"RESPONSE: {request.method} {request.path} -> {response.status_code}", flush=True)
        # Prevent browser caching for HTML pages to ensure fresh data
        if response.content_type and 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

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

    @app.errorhandler(404)
    def not_found(e):
        return "Not Found", 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
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

            # Migrations
            try:
                from sqlalchemy import text, inspect
                inspector = inspect(db.engine)

                # Migration 1: Add record_type column to stock_ins
                si_columns = [c['name'] for c in inspector.get_columns('stock_ins')]
                if 'record_type' not in si_columns:
                    print("Migrating stock_ins: adding record_type column...", flush=True)
                    db.session.execute(text(
                        "ALTER TABLE stock_ins ADD COLUMN record_type VARCHAR(20) NOT NULL DEFAULT 'incoming'"
                    ))
                    db.session.execute(text(
                        "UPDATE stock_ins SET record_type = 'transfer' WHERE branch_id IS NOT NULL"
                    ))
                    db.session.commit()
                    print("Migration complete: record_type column added and backfilled", flush=True)

                # Migration 2: Add is_waste column to categories
                cat_columns = [c['name'] for c in inspector.get_columns('categories')]
                if 'is_waste' not in cat_columns:
                    print("Migrating categories: adding is_waste column...", flush=True)
                    db.session.execute(text(
                        "ALTER TABLE categories ADD COLUMN is_waste BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
                    db.session.execute(text(
                        "UPDATE categories SET is_waste = TRUE WHERE name = '폐유'"
                    ))
                    db.session.commit()
                    print("Migration complete: is_waste column added", flush=True)
                # Migration 3: Add payment_type and jungsung_id to payments
                pay_columns = [c['name'] for c in inspector.get_columns('payments')]
                if 'payment_type' not in pay_columns:
                    print("Migrating payments: adding payment_type, jungsung_id columns...", flush=True)
                    db.session.execute(text(
                        "ALTER TABLE payments ADD COLUMN payment_type VARCHAR(20) NOT NULL DEFAULT 'hq_branch'"
                    ))
                    db.session.execute(text(
                        "ALTER TABLE payments ADD COLUMN jungsung_id INTEGER REFERENCES jungsungs(id)"
                    ))
                    db.session.commit()
                    print("Migration complete: payment_type and jungsung_id columns added", flush=True)
                elif 'jungsung_id' not in pay_columns:
                    print("Migrating payments: adding jungsung_id column...", flush=True)
                    db.session.execute(text(
                        "ALTER TABLE payments ADD COLUMN jungsung_id INTEGER REFERENCES jungsungs(id)"
                    ))
                    db.session.commit()
                    print("Migration complete: jungsung_id column added", flush=True)

            except Exception as me:
                print(f"Migration error: {me}", flush=True)
                db.session.rollback()

    except Exception as e:
        print(f"WARNING: Could not create tables on startup: {e}", flush=True)
        print("Tables may already exist or database may not be accessible", flush=True)

    return app
