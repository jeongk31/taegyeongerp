from functools import wraps
from flask import redirect, url_for, flash, abort
from flask_login import current_user


def role_required(roles):
    """
    Decorator that requires user to have one of the specified roles.
    Usage: @role_required(['admin', 'branch'])
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('로그인이 필요합니다.', 'warning')
                return redirect(url_for('auth.login'))

            if current_user.role not in roles:
                flash('접근 권한이 없습니다.', 'danger')
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """
    Decorator that requires user to be an admin (관리자).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('로그인이 필요합니다.', 'warning')
            return redirect(url_for('auth.login'))

        if not current_user.is_admin():
            flash('관리자 권한이 필요합니다.', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


def branch_required(f):
    """
    Decorator that requires user to be a branch manager (지사) or higher.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('로그인이 필요합니다.', 'warning')
            return redirect(url_for('auth.login'))

        if not (current_user.is_admin() or current_user.is_branch()):
            flash('지사 이상 권한이 필요합니다.', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


def driver_required(f):
    """
    Decorator that requires user to be a driver (배송기사) or higher.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('로그인이 필요합니다.', 'warning')
            return redirect(url_for('auth.login'))

        if not (current_user.is_admin() or current_user.is_branch() or current_user.is_driver()):
            flash('배송기사 이상 권한이 필요합니다.', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


def franchise_required(f):
    """
    Decorator that requires user to be franchise HQ (프랜차이즈 본사).
    Note: Franchise users are separate from the main hierarchy.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('로그인이 필요합니다.', 'warning')
            return redirect(url_for('auth.login'))

        if not (current_user.is_admin() or current_user.is_franchise()):
            flash('프랜차이즈 본사 권한이 필요합니다.', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


def jungsung_required(f):
    """
    Decorator that requires user to be a jungsung (중상).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('로그인이 필요합니다.', 'warning')
            return redirect(url_for('auth.login'))

        if not current_user.is_jungsung():
            flash('중상 권한이 필요합니다.', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function
