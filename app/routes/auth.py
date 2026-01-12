from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Check if password change is required
        if current_user.must_change_password:
            return redirect(url_for('auth.change_password'))
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('아이디와 비밀번호를 입력해주세요.', 'warning')
            return render_template('auth/login.html')

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
            return render_template('auth/login.html')

        if not user.is_active:
            flash('비활성화된 계정입니다. 관리자에게 문의하세요.', 'warning')
            return render_template('auth/login.html')

        login_user(user, remember=request.form.get('remember'))

        # Check if password change is required
        if user.must_change_password:
            flash('첫 로그인입니다. 비밀번호를 변경해주세요.', 'warning')
            return redirect(url_for('auth.change_password'))

        flash(f'{user.get_role_display()}님, 환영합니다!', 'success')

        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)

        return redirect(url_for('dashboard.index'))

    return render_template('auth/login.html')


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_password or not new_password or not confirm_password:
            flash('모든 필드를 입력해주세요.', 'warning')
            return render_template('auth/change_password.html')

        if not current_user.check_password(current_password):
            flash('현재 비밀번호가 올바르지 않습니다.', 'danger')
            return render_template('auth/change_password.html')

        if new_password != confirm_password:
            flash('새 비밀번호가 일치하지 않습니다.', 'danger')
            return render_template('auth/change_password.html')

        if len(new_password) < 4:
            flash('비밀번호는 4자 이상이어야 합니다.', 'danger')
            return render_template('auth/change_password.html')

        current_user.set_password(new_password)
        current_user.must_change_password = False
        db.session.commit()

        flash('비밀번호가 변경되었습니다.', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('로그아웃되었습니다.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page - view info and change password"""
    if request.method == 'POST':
        # Handle password change
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # Validate inputs
        if not all([current_password, new_password, confirm_password]):
            flash('모든 필드를 입력해주세요.', 'danger')
            return redirect(url_for('auth.profile'))

        # Check current password
        if not current_user.check_password(current_password):
            flash('현재 비밀번호가 올바르지 않습니다.', 'danger')
            return redirect(url_for('auth.profile'))

        # Check new passwords match
        if new_password != confirm_password:
            flash('새 비밀번호가 일치하지 않습니다.', 'danger')
            return redirect(url_for('auth.profile'))

        # Check password length
        if len(new_password) < 4:
            flash('비밀번호는 최소 4자 이상이어야 합니다.', 'danger')
            return redirect(url_for('auth.profile'))

        # Update password
        current_user.set_password(new_password)
        current_user.must_change_password = False
        db.session.commit()

        flash('비밀번호가 성공적으로 변경되었습니다.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html')
