from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user import User, Branch, Franchise, Store, Jungsung, Supplier, Product, Shipment, ShipmentItem, StockIn, ERPRegistration, Payment, UserRole, Category
from app.utils.decorators import admin_required, branch_required, jungsung_required, franchise_required
from app.utils.timezone import kst_today, kst_now
from datetime import datetime, date, timedelta
from sqlalchemy import func, extract, or_, and_
from sqlalchemy.orm import joinedload
import json

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def get_waste_category_names():
    """Get waste category names from DB (e.g. 폐유). Never hardcode."""
    waste_cats = Category.query.filter_by(is_waste=True, is_active=True).all()
    return [c.name for c in waste_cats]


def get_non_waste_category_names():
    """Get all non-waste active category names from DB."""
    cats = Category.query.filter(Category.is_active == True, Category.is_waste == False).all()
    return [c.name for c in cats]


def build_month_weeks(year, month):
    """Build Mon-Sun aligned weeks for a month.
    Week 1: 1st of month through first Sunday.
    Subsequent weeks: Monday through Sunday.
    Last week: Last Monday through end of month."""
    from calendar import monthrange
    last_day_num = monthrange(year, month)[1]
    first_day = date(year, month, 1)
    last_day = date(year, month, last_day_num)
    weeks = []
    wn = 1
    # Week 1: 1st to first Sunday
    first_sunday_offset = (6 - first_day.weekday()) % 7
    first_week_end = min(first_day + timedelta(days=first_sunday_offset), last_day)
    weeks.append({'num': wn, 'start': first_day, 'end': first_week_end})
    wn += 1
    # Subsequent weeks: Monday to Sunday
    current = first_week_end + timedelta(days=1)
    while current <= last_day:
        week_end = min(current + timedelta(days=6), last_day)
        weeks.append({'num': wn, 'start': current, 'end': week_end})
        current = week_end + timedelta(days=1)
        wn += 1
    return weeks


# ============================================
# 사용자 관리
# ============================================

@admin_bp.route('/users')
@login_required
@admin_required
def users_list():
    """All user accounts list - admin only"""
    role_filter = request.args.get('role', '')
    query = User.query

    if role_filter:
        query = query.filter(User.role == role_filter)

    users = query.order_by(User.created_at.desc()).all()
    return render_template('admin/users_list.html', users=users, role_filter=role_filter)


# ============================================
# 거래처등록관리 (지사)
# ============================================

@admin_bp.route('/branches')
@login_required
@admin_required
def branches_list():
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'name':
        order_col = Branch.name.desc() if order == 'desc' else Branch.name.asc()
    elif sort == 'created_at':
        order_col = Branch.created_at.desc() if order == 'desc' else Branch.created_at.asc()
    else:  # default: id
        order_col = Branch.id.desc() if order == 'desc' else Branch.id.asc()

    branches = Branch.query.order_by(order_col).all()
    return render_template('admin/branches_list.html', branches=branches, sort=sort, order=order)


@admin_bp.route('/branches/add', methods=['GET', 'POST'])
@login_required
@admin_required
def branches_add():
    if request.method == 'POST':
        name = request.form.get('name')
        contact_person = request.form.get('contact_person')
        phone = request.form.get('phone')
        username = request.form.get('username')
        password = request.form.get('password', '1234')  # Default password

        if not name:
            flash('지사명을 입력해주세요.', 'danger')
            return redirect(url_for('admin.branches_list'))

        if not username:
            flash('아이디를 입력해주세요.', 'danger')
            return redirect(url_for('admin.branches_list'))

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('이미 사용 중인 아이디입니다.', 'danger')
            return redirect(url_for('admin.branches_list'))

        branch = Branch(
            name=name,
            contact_person=contact_person,
            phone=phone
        )
        db.session.add(branch)
        db.session.flush()

        # Create user account for the branch
        user = User(
            username=username,
            name=contact_person or name,
            role=UserRole.BRANCH.value,
            branch_id=branch.id,
            is_active=True,
            must_change_password=True
        )
        user.set_password(password or '1234')
        db.session.add(user)
        db.session.commit()

        flash(f'지사가 등록되었습니다. (아이디: {username}, 임시비밀번호: {password or "1234"})', 'success')
        return redirect(url_for('admin.branches_list'))

    return redirect(url_for('admin.branches_list'))


@admin_bp.route('/branches/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def branches_edit(id):
    branch = Branch.query.get_or_404(id)

    if request.method == 'POST':
        name = request.form.get('name')
        contact_person = request.form.get('contact_person')
        phone = request.form.get('phone')

        if not name:
            flash('지사명을 입력해주세요.', 'danger')
            return redirect(url_for('admin.branches_list'))

        branch.name = name
        branch.contact_person = contact_person
        branch.phone = phone
        db.session.commit()

        flash('지사 정보가 수정되었습니다.', 'success')
        return redirect(url_for('admin.branches_list'))

    return redirect(url_for('admin.branches_list'))


@admin_bp.route('/branches/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def branches_toggle(id):
    branch = Branch.query.get_or_404(id)
    branch.is_active = not branch.is_active
    # Also toggle associated user accounts
    for user in branch.users:
        user.is_active = branch.is_active
    db.session.commit()
    status = '활성화' if branch.is_active else '비활성화'
    flash(f'지사가 {status}되었습니다.', 'success')
    return redirect(url_for('admin.branches_list'))


@admin_bp.route('/branches/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def branches_delete(id):
    branch = Branch.query.get_or_404(id)

    # First, handle jungsungs under this branch (jungsungs have NOT NULL branch_id)
    jungsungs = Jungsung.query.filter_by(branch_id=branch.id).all()
    for jungsung in jungsungs:
        # Update related records to remove jungsung reference
        Store.query.filter_by(jungsung_id=jungsung.id).update({'jungsung_id': None})
        ShipmentItem.query.filter_by(jungsung_id=jungsung.id).update({'jungsung_id': None})
        ERPRegistration.query.filter_by(jungsung_id=jungsung.id).update({'jungsung_id': None})
        # Delete jungsung users
        User.query.filter_by(jungsung_id=jungsung.id, role=UserRole.JUNGSUNG.value).delete()
        db.session.delete(jungsung)

    # Update stores to remove branch reference
    Store.query.filter_by(branch_id=branch.id).update({'branch_id': None})

    # Update shipment items to remove branch reference
    ShipmentItem.query.filter_by(branch_id=branch.id).update({'branch_id': None})

    # Update stock ins to remove branch reference
    StockIn.query.filter_by(branch_id=branch.id).update({'branch_id': None})

    # Delete all users associated with this branch
    User.query.filter_by(branch_id=branch.id).delete()

    db.session.delete(branch)
    db.session.commit()
    flash('지사가 삭제되었습니다.', 'success')
    return redirect(url_for('admin.branches_list'))


@admin_bp.route('/branches/<int:id>/reset-password', methods=['POST'])
@login_required
@admin_required
def branches_reset_password(id):
    branch = Branch.query.get_or_404(id)
    user = User.query.filter_by(branch_id=branch.id, role=UserRole.BRANCH.value).first()
    if user:
        user.set_password('1234')
        user.must_change_password = True
        db.session.commit()
        flash(f'비밀번호가 초기화되었습니다. (임시비밀번호: 1234)', 'success')
    else:
        flash('연결된 계정이 없습니다.', 'warning')
    return redirect(url_for('admin.branches_list'))


# ============================================
# 담당중상 (Admin + Branch users)
# ============================================

@admin_bp.route('/jungsungs')
@login_required
@branch_required
def jungsungs_list():
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'business_name':
        order_col = Jungsung.business_name.desc() if order == 'desc' else Jungsung.business_name.asc()
    elif sort == 'created_at':
        order_col = Jungsung.created_at.desc() if order == 'desc' else Jungsung.created_at.asc()
    else:  # default: id
        order_col = Jungsung.id.desc() if order == 'desc' else Jungsung.id.asc()

    if current_user.is_admin():
        jungsungs = Jungsung.query.order_by(order_col).all()
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    else:
        # Branch users only see their own branch's jungsungs
        jungsungs = Jungsung.query.filter_by(branch_id=current_user.branch_id).order_by(order_col).all()
        branches = [current_user.branch] if current_user.branch else []
    return render_template('admin/jungsungs_list.html', jungsungs=jungsungs, branches=branches, sort=sort, order=order)


@admin_bp.route('/jungsungs/add', methods=['GET', 'POST'])
@login_required
@branch_required
def jungsungs_add():
    if request.method == 'POST':
        if current_user.is_admin():
            branch_id = request.form.get('branch_id')
        else:
            branch_id = current_user.branch_id

        business_name = request.form.get('business_name')
        contact_person = request.form.get('contact_person')
        phone = request.form.get('phone')
        username = request.form.get('username')
        password = request.form.get('password', '1234')  # Default password

        if not branch_id or not business_name:
            flash('소속지사와 사업자명은 필수 입력 항목입니다.', 'danger')
            return redirect(url_for('admin.jungsungs_list'))

        if not username:
            flash('아이디를 입력해주세요.', 'danger')
            return redirect(url_for('admin.jungsungs_list'))

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('이미 사용 중인 아이디입니다.', 'danger')
            return redirect(url_for('admin.jungsungs_list'))

        jungsung = Jungsung(
            branch_id=int(branch_id),
            business_name=business_name,
            contact_person=contact_person,
            phone=phone
        )
        db.session.add(jungsung)
        db.session.flush()

        # Create user account for the jungsung
        user = User(
            username=username,
            name=contact_person or business_name,
            role=UserRole.JUNGSUNG.value,
            branch_id=int(branch_id),
            jungsung_id=jungsung.id,
            is_active=True,
            must_change_password=True
        )
        user.set_password(password or '1234')
        db.session.add(user)
        db.session.commit()

        flash(f'담당중상이 등록되었습니다. (아이디: {username}, 임시비밀번호: {password or "1234"})', 'success')
        return redirect(url_for('admin.jungsungs_list'))

    return redirect(url_for('admin.jungsungs_list'))


@admin_bp.route('/jungsungs/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@branch_required
def jungsungs_edit(id):
    jungsung = Jungsung.query.get_or_404(id)

    # Branch users can only edit their own branch's jungsungs
    if not current_user.is_admin() and jungsung.branch_id != current_user.branch_id:
        flash('접근 권한이 없습니다.', 'danger')
        return redirect(url_for('admin.jungsungs_list'))

    if request.method == 'POST':
        if current_user.is_admin():
            branch_id = request.form.get('branch_id')
        else:
            # For non-admin, keep existing branch_id
            branch_id = jungsung.branch_id

        business_name = request.form.get('business_name')
        contact_person = request.form.get('contact_person')
        phone = request.form.get('phone')

        if not business_name:
            flash('사업자명은 필수 입력 항목입니다.', 'danger')
            return redirect(url_for('admin.jungsungs_list'))

        # For admin, validate branch_id from form
        if current_user.is_admin():
            if not branch_id:
                flash('소속지사를 선택해주세요.', 'danger')
                return redirect(url_for('admin.jungsungs_list'))
            try:
                jungsung.branch_id = int(branch_id)
            except (ValueError, TypeError):
                flash('잘못된 지사 정보입니다.', 'danger')
                return redirect(url_for('admin.jungsungs_list'))
        # For non-admin, branch_id stays the same (not editable)

        jungsung.business_name = business_name
        jungsung.contact_person = contact_person
        jungsung.phone = phone
        db.session.commit()

        flash('담당중상 정보가 수정되었습니다.', 'success')
        return redirect(url_for('admin.jungsungs_list'))

    return redirect(url_for('admin.jungsungs_list'))


@admin_bp.route('/jungsungs/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def jungsungs_toggle(id):
    jungsung = Jungsung.query.get_or_404(id)
    jungsung.is_active = not jungsung.is_active
    # Also toggle associated user accounts
    for user in jungsung.users:
        user.is_active = jungsung.is_active
    db.session.commit()
    status = '활성화' if jungsung.is_active else '비활성화'
    flash(f'담당중상이 {status}되었습니다.', 'success')
    return redirect(url_for('admin.jungsungs_list'))


@admin_bp.route('/jungsungs/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def jungsungs_delete(id):
    jungsung = Jungsung.query.get_or_404(id)

    # Update related records to remove jungsung reference
    Store.query.filter_by(jungsung_id=jungsung.id).update({'jungsung_id': None})
    ShipmentItem.query.filter_by(jungsung_id=jungsung.id).update({'jungsung_id': None})
    ERPRegistration.query.filter_by(jungsung_id=jungsung.id).update({'jungsung_id': None})

    # Delete associated users
    User.query.filter_by(jungsung_id=jungsung.id, role=UserRole.JUNGSUNG.value).delete()

    db.session.delete(jungsung)
    db.session.commit()
    flash('담당중상이 삭제되었습니다.', 'success')
    return redirect(url_for('admin.jungsungs_list'))


@admin_bp.route('/jungsungs/<int:id>/reset-password', methods=['POST'])
@login_required
@admin_required
def jungsungs_reset_password(id):
    jungsung = Jungsung.query.get_or_404(id)
    user = User.query.filter_by(jungsung_id=jungsung.id, role=UserRole.JUNGSUNG.value).first()
    if user:
        user.set_password('1234')
        user.must_change_password = True
        db.session.commit()
        flash(f'비밀번호가 초기화되었습니다. (임시비밀번호: 1234)', 'success')
    else:
        flash('연결된 계정이 없습니다.', 'warning')
    return redirect(url_for('admin.jungsungs_list'))


# ============================================
# 제품입고업체 등록관리
# ============================================

@admin_bp.route('/suppliers')
@login_required
@admin_required
def suppliers_list():
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'company_name':
        order_col = Supplier.company_name.desc() if order == 'desc' else Supplier.company_name.asc()
    elif sort == 'created_at':
        order_col = Supplier.created_at.desc() if order == 'desc' else Supplier.created_at.asc()
    else:  # default: id
        order_col = Supplier.id.desc() if order == 'desc' else Supplier.id.asc()

    suppliers = Supplier.query.order_by(order_col).all()
    return render_template('admin/suppliers_list.html', suppliers=suppliers, sort=sort, order=order)


@admin_bp.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
@admin_required
def suppliers_add():
    if request.method == 'POST':
        company_name = request.form.get('company_name')
        contact_person = request.form.get('contact_person')
        phone = request.form.get('phone')

        if not company_name:
            flash('회사명을 입력해주세요.', 'danger')
            return redirect(url_for('admin.suppliers_list'))

        supplier = Supplier(
            company_name=company_name,
            contact_person=contact_person,
            phone=phone
        )
        db.session.add(supplier)
        db.session.commit()

        flash('제품입고업체가 등록되었습니다.', 'success')
        return redirect(url_for('admin.suppliers_list'))

    return redirect(url_for('admin.suppliers_list'))


@admin_bp.route('/suppliers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def suppliers_edit(id):
    supplier = Supplier.query.get_or_404(id)

    if request.method == 'POST':
        company_name = request.form.get('company_name')
        contact_person = request.form.get('contact_person')
        phone = request.form.get('phone')

        if not company_name:
            flash('회사명을 입력해주세요.', 'danger')
            return redirect(url_for('admin.suppliers_list'))

        supplier.company_name = company_name
        supplier.contact_person = contact_person
        supplier.phone = phone
        db.session.commit()

        flash('제품입고업체 정보가 수정되었습니다.', 'success')
        return redirect(url_for('admin.suppliers_list'))

    return redirect(url_for('admin.suppliers_list'))


@admin_bp.route('/suppliers/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def suppliers_toggle(id):
    supplier = Supplier.query.get_or_404(id)
    supplier.is_active = not supplier.is_active
    db.session.commit()
    status = '활성화' if supplier.is_active else '비활성화'
    flash(f'제품입고업체가 {status}되었습니다.', 'success')
    return redirect(url_for('admin.suppliers_list'))


@admin_bp.route('/suppliers/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def suppliers_delete(id):
    supplier = Supplier.query.get_or_404(id)
    db.session.delete(supplier)
    db.session.commit()
    flash('제품입고업체가 삭제되었습니다.', 'success')
    return redirect(url_for('admin.suppliers_list'))


# ============================================
# 품목 관리
# ============================================

@admin_bp.route('/categories')
@login_required
@admin_required
def categories_list():
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'name':
        order_col = Category.name.desc() if order == 'desc' else Category.name.asc()
    elif sort == 'created_at':
        order_col = Category.created_at.desc() if order == 'desc' else Category.created_at.asc()
    else:  # default: id
        order_col = Category.id.desc() if order == 'desc' else Category.id.asc()

    categories = Category.query.order_by(order_col).all()
    return render_template('admin/categories_list.html', categories=categories, sort=sort, order=order)


@admin_bp.route('/categories/add', methods=['POST'])
@login_required
@admin_required
def categories_add():
    name = request.form.get('name')

    if not name:
        flash('품목명을 입력해주세요.', 'danger')
        return redirect(url_for('admin.categories_list'))

    if Category.query.filter_by(name=name).first():
        flash('이미 등록된 품목입니다.', 'danger')
        return redirect(url_for('admin.categories_list'))

    category = Category(name=name)
    db.session.add(category)
    db.session.commit()

    flash('품목이 등록되었습니다.', 'success')
    return redirect(url_for('admin.categories_list'))


@admin_bp.route('/categories/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def categories_edit(id):
    category = Category.query.get_or_404(id)
    name = request.form.get('name')

    if not name:
        flash('품목명을 입력해주세요.', 'danger')
        return redirect(url_for('admin.categories_list'))

    existing = Category.query.filter_by(name=name).first()
    if existing and existing.id != category.id:
        flash('이미 등록된 품목입니다.', 'danger')
        return redirect(url_for('admin.categories_list'))

    category.name = name
    db.session.commit()

    flash('품목이 수정되었습니다.', 'success')
    return redirect(url_for('admin.categories_list'))


@admin_bp.route('/categories/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def categories_toggle(id):
    category = Category.query.get_or_404(id)
    category.is_active = not category.is_active
    db.session.commit()
    status = '활성화' if category.is_active else '비활성화'
    flash(f'품목이 {status}되었습니다.', 'success')
    return redirect(url_for('admin.categories_list'))


@admin_bp.route('/categories/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def categories_delete(id):
    category = Category.query.get_or_404(id)
    db.session.delete(category)
    db.session.commit()
    flash('품목이 삭제되었습니다.', 'success')
    return redirect(url_for('admin.categories_list'))


# ============================================
# 프랜차이즈 관리
# ============================================

@admin_bp.route('/franchises')
@login_required
@admin_required
def franchises_list():
    """Franchise list - admin only"""
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'name':
        order_col = Franchise.name.desc() if order == 'desc' else Franchise.name.asc()
    elif sort == 'created_at':
        order_col = Franchise.created_at.desc() if order == 'desc' else Franchise.created_at.asc()
    else:  # default: id
        order_col = Franchise.id.desc() if order == 'desc' else Franchise.id.asc()

    # Branch users only see franchises that have stores in their branch
    if current_user.is_branch():
        # Get unique franchise IDs from stores in this branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids]
        franchises = Franchise.query.filter(Franchise.id.in_(franchise_ids)).order_by(order_col).all()
    else:
        franchises = Franchise.query.order_by(order_col).all()

    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    return render_template('admin/franchises_list.html', franchises=franchises, categories=categories, sort=sort, order=order)


@admin_bp.route('/stores')
@login_required
def stores_list():
    """Stores list - accessible by admin and branch users"""
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'name':
        order_col = Store.name.desc() if order == 'desc' else Store.name.asc()
    elif sort == 'franchise':
        order_col = Store.franchise_id.desc() if order == 'desc' else Store.franchise_id.asc()
    elif sort == 'created_at':
        order_col = Store.created_at.desc() if order == 'desc' else Store.created_at.asc()
    else:  # default: id
        order_col = Store.id.desc() if order == 'desc' else Store.id.asc()

    if current_user.is_branch():
        # Branch users only see stores in their branch
        franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
        stores = Store.query.filter_by(branch_id=current_user.branch_id).order_by(order_col).all()
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(
            is_active=True,
            branch_id=current_user.branch_id
        ).order_by(Jungsung.business_name).all()
    else:
        # Admin sees all
        franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
        stores = Store.query.order_by(order_col).all()
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()

    return render_template('admin/stores_list.html',
                           franchises=franchises,
                           stores=stores,
                           branches=branches,
                           jungsungs=jungsungs,
                           sort=sort,
                           order=order)


@admin_bp.route('/franchises/add', methods=['GET', 'POST'])
@login_required
@admin_required
def franchises_add():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        address = request.form.get('address')
        phone = request.form.get('phone')
        contact_person = request.form.get('contact_person')
        username = request.form.get('username')
        password = request.form.get('password', '1234')  # Default password

        if not name:
            flash('프랜차이즈명을 입력해주세요.', 'danger')
            return render_template('admin/franchises_form.html')

        if code and Franchise.query.filter_by(code=code).first():
            flash('이미 사용 중인 코드입니다.', 'danger')
            return render_template('admin/franchises_form.html')

        if not username:
            flash('아이디를 입력해주세요.', 'danger')
            return render_template('admin/franchises_form.html')

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('이미 사용 중인 아이디입니다.', 'danger')
            return render_template('admin/franchises_form.html')

        franchise = Franchise(
            name=name,
            code=code or None,
            address=address or None,
            phone=phone or None,
            contact_person=contact_person or None
        )
        db.session.add(franchise)
        db.session.flush()

        # Create user account for the franchise
        user = User(
            username=username,
            name=contact_person or name,
            role=UserRole.FRANCHISE.value,
            franchise_id=franchise.id,
            is_active=True,
            must_change_password=True
        )
        user.set_password(password or '1234')
        db.session.add(user)
        db.session.commit()

        flash(f'프랜차이즈가 등록되었습니다. (아이디: {username}, 임시비밀번호: {password or "1234"})', 'success')
        return redirect(url_for('admin.franchises_list'))

    return render_template('admin/franchises_form.html')


@admin_bp.route('/franchises/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def franchises_edit(id):
    franchise = Franchise.query.get_or_404(id)

    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        address = request.form.get('address')
        phone = request.form.get('phone')
        contact_person = request.form.get('contact_person')

        if not name:
            flash('프랜차이즈명을 입력해주세요.', 'danger')
            return render_template('admin/franchises_form.html', franchise=franchise)

        existing = Franchise.query.filter_by(code=code).first()
        if code and existing and existing.id != franchise.id:
            flash('이미 사용 중인 코드입니다.', 'danger')
            return render_template('admin/franchises_form.html', franchise=franchise)

        franchise.name = name
        franchise.code = code
        franchise.address = address
        franchise.phone = phone
        franchise.contact_person = contact_person
        db.session.commit()

        flash('프랜차이즈 정보가 수정되었습니다.', 'success')
        return redirect(url_for('admin.franchises_list'))

    return render_template('admin/franchises_form.html', franchise=franchise)


@admin_bp.route('/franchises/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def franchises_toggle(id):
    franchise = Franchise.query.get_or_404(id)
    franchise.is_active = not franchise.is_active
    # Also toggle associated user accounts
    for user in franchise.users:
        user.is_active = franchise.is_active
    db.session.commit()
    status = '활성화' if franchise.is_active else '비활성화'
    flash(f'프랜차이즈가 {status}되었습니다.', 'success')
    return redirect(url_for('admin.franchises_list'))


@admin_bp.route('/franchises/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def franchises_delete(id):
    franchise = Franchise.query.get_or_404(id)
    # Delete associated users
    User.query.filter_by(franchise_id=franchise.id, role=UserRole.FRANCHISE.value).delete()
    db.session.delete(franchise)
    db.session.commit()
    flash('프랜차이즈가 삭제되었습니다.', 'success')
    return redirect(url_for('admin.franchises_list'))


@admin_bp.route('/franchises/<int:id>/reset-password', methods=['POST'])
@login_required
@admin_required
def franchises_reset_password(id):
    franchise = Franchise.query.get_or_404(id)
    user = User.query.filter_by(franchise_id=franchise.id, role=UserRole.FRANCHISE.value).first()
    if user:
        user.set_password('1234')
        user.must_change_password = True
        db.session.commit()
        flash(f'비밀번호가 초기화되었습니다. (임시비밀번호: 1234)', 'success')
    else:
        flash('연결된 계정이 없습니다.', 'warning')
    return redirect(url_for('admin.franchises_list'))


@admin_bp.route('/franchises/add-modal', methods=['POST'])
@login_required
@admin_required
def franchises_add_modal():
    name = request.form.get('name')
    code = request.form.get('code')
    address = request.form.get('address')
    phone = request.form.get('phone')
    contact_person = request.form.get('contact_person')
    username = request.form.get('username')
    password = request.form.get('password', '1234')

    if not name:
        flash('프랜차이즈명을 입력해주세요.', 'danger')
        return redirect(url_for('admin.franchises_list'))

    if code and Franchise.query.filter_by(code=code).first():
        flash('이미 사용 중인 코드입니다.', 'danger')
        return redirect(url_for('admin.franchises_list'))

    if not username:
        flash('아이디를 입력해주세요.', 'danger')
        return redirect(url_for('admin.franchises_list'))

    if User.query.filter_by(username=username).first():
        flash('이미 사용 중인 아이디입니다.', 'danger')
        return redirect(url_for('admin.franchises_list'))

    franchise = Franchise(
        name=name,
        code=code or None,
        address=address or None,
        phone=phone or None,
        contact_person=contact_person or None
    )
    db.session.add(franchise)
    db.session.flush()

    # Save linked categories
    category_ids = request.form.getlist('category_ids')
    for cat_id in category_ids:
        try:
            category = Category.query.get(int(cat_id))
            if category:
                franchise.categories.append(category)
        except (ValueError, TypeError):
            pass

    user = User(
        username=username,
        name=contact_person or name,
        role=UserRole.FRANCHISE.value,
        franchise_id=franchise.id,
        is_active=True,
        must_change_password=True
    )
    user.set_password(password or '1234')
    db.session.add(user)
    db.session.commit()

    flash(f'프랜차이즈가 등록되었습니다. (아이디: {username}, 임시비밀번호: {password or "1234"})', 'success')
    return redirect(url_for('admin.franchises_list'))


@admin_bp.route('/franchises/<int:id>/edit-modal', methods=['POST'])
@login_required
@admin_required
def franchises_edit_modal(id):
    franchise = Franchise.query.get_or_404(id)

    name = request.form.get('name')
    code = request.form.get('code')
    address = request.form.get('address')
    phone = request.form.get('phone')
    contact_person = request.form.get('contact_person')

    if not name:
        flash('프랜차이즈명을 입력해주세요.', 'danger')
        return redirect(url_for('admin.franchises_list'))

    existing = Franchise.query.filter_by(code=code).first()
    if code and existing and existing.id != franchise.id:
        flash('이미 사용 중인 코드입니다.', 'danger')
        return redirect(url_for('admin.franchises_list'))

    franchise.name = name
    franchise.code = code
    franchise.address = address
    franchise.phone = phone
    franchise.contact_person = contact_person

    # Update linked categories
    franchise.categories = []
    category_ids = request.form.getlist('category_ids')
    for cat_id in category_ids:
        try:
            category = Category.query.get(int(cat_id))
            if category:
                franchise.categories.append(category)
        except (ValueError, TypeError):
            pass

    db.session.commit()

    flash('프랜차이즈 정보가 수정되었습니다.', 'success')
    return redirect(url_for('admin.franchises_list'))


@admin_bp.route('/franchises/<int:franchise_id>')
@login_required
@admin_required
def franchises_detail(franchise_id):
    franchise = Franchise.query.get_or_404(franchise_id)
    stores = Store.query.filter_by(franchise_id=franchise_id, is_active=True).order_by(Store.created_at.desc()).all()
    return render_template('admin/franchises_detail.html', franchise=franchise, stores=stores)


@admin_bp.route('/franchises/<int:franchise_id>/stores/add', methods=['GET', 'POST'])
@login_required
@admin_required
def stores_add(franchise_id):
    franchise = Franchise.query.get_or_404(franchise_id)

    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        address = request.form.get('address')
        phone = request.form.get('phone')
        contact_person = request.form.get('contact_person')

        if not name:
            flash('매장명을 입력해주세요.', 'danger')
            return render_template('admin/stores_form.html', franchise=franchise)

        if code and Store.query.filter_by(code=code).first():
            flash('이미 사용 중인 코드입니다.', 'danger')
            return render_template('admin/stores_form.html', franchise=franchise)

        store = Store(
            name=name,
            code=code,
            address=address,
            phone=phone,
            contact_person=contact_person,
            franchise_id=franchise_id
        )
        db.session.add(store)
        db.session.commit()

        flash('매장이 등록되었습니다.', 'success')
        return redirect(url_for('admin.franchises_detail', franchise_id=franchise_id))

    return render_template('admin/stores_form.html', franchise=franchise)


@admin_bp.route('/franchises/<int:franchise_id>/stores/<int:store_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def stores_edit(franchise_id, store_id):
    franchise = Franchise.query.get_or_404(franchise_id)
    store = Store.query.get_or_404(store_id)

    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        address = request.form.get('address')
        phone = request.form.get('phone')
        contact_person = request.form.get('contact_person')

        if not name:
            flash('매장명을 입력해주세요.', 'danger')
            return render_template('admin/stores_form.html', franchise=franchise, store=store)

        existing = Store.query.filter_by(code=code).first()
        if code and existing and existing.id != store.id:
            flash('이미 사용 중인 코드입니다.', 'danger')
            return render_template('admin/stores_form.html', franchise=franchise, store=store)

        store.name = name
        store.code = code
        store.address = address
        store.phone = phone
        store.contact_person = contact_person
        db.session.commit()

        flash('매장 정보가 수정되었습니다.', 'success')
        return redirect(url_for('admin.franchises_detail', franchise_id=franchise_id))

    return render_template('admin/stores_form.html', franchise=franchise, store=store)


# ============================================
# 프랜차이즈 매장 관리 (Inline from stores_list)
# ============================================

@admin_bp.route('/stores/add-inline', methods=['POST'])
@login_required
@admin_required
def stores_add_inline():
    franchise_id = request.form.get('franchise_id')
    name = request.form.get('name')
    branch_id = request.form.get('branch_id') or None
    jungsung_id = request.form.get('jungsung_id') or None
    owner_name = request.form.get('owner_name')
    owner_phone = request.form.get('owner_phone')
    address = request.form.get('address')

    if not franchise_id or not name:
        flash('프랜차이즈와 매장명은 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.stores_list'))

    # Force branch users to use their own branch
    if current_user.is_branch():
        branch_id = current_user.branch_id

    store = Store(
        franchise_id=int(franchise_id),
        name=name,
        branch_id=int(branch_id) if branch_id else None,
        jungsung_id=int(jungsung_id) if jungsung_id else None,
        owner_name=owner_name,
        owner_phone=owner_phone,
        address=address
    )
    db.session.add(store)
    db.session.commit()

    flash('매장이 등록되었습니다.', 'success')
    return redirect(url_for('admin.stores_list'))


@admin_bp.route('/stores/<int:store_id>/edit-inline', methods=['POST'])
@login_required
@admin_required
def stores_edit_inline(store_id):
    store = Store.query.get_or_404(store_id)

    franchise_id = request.form.get('franchise_id')
    name = request.form.get('name')
    branch_id = request.form.get('branch_id') or None
    jungsung_id = request.form.get('jungsung_id') or None
    owner_name = request.form.get('owner_name')
    owner_phone = request.form.get('owner_phone')
    address = request.form.get('address')

    if not franchise_id or not name:
        flash('프랜차이즈와 매장명은 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.stores_list'))

    # Force branch users to use their own branch
    if current_user.is_branch():
        branch_id = current_user.branch_id

    store.franchise_id = int(franchise_id)
    store.name = name
    store.branch_id = int(branch_id) if branch_id else None
    store.jungsung_id = int(jungsung_id) if jungsung_id else None
    store.owner_name = owner_name
    store.owner_phone = owner_phone
    store.address = address
    db.session.commit()

    flash('매장 정보가 수정되었습니다.', 'success')
    return redirect(url_for('admin.stores_list'))


@admin_bp.route('/stores/<int:store_id>')
@login_required
@admin_required
def stores_detail(store_id):
    store = Store.query.get_or_404(store_id)
    return render_template('admin/stores_detail.html', store=store)


@admin_bp.route('/stores/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def stores_toggle(id):
    store = Store.query.get_or_404(id)
    store.is_active = not store.is_active
    db.session.commit()
    status = '활성화' if store.is_active else '비활성화'
    flash(f'매장이 {status}되었습니다.', 'success')
    return redirect(url_for('admin.stores_list'))


@admin_bp.route('/stores/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def stores_delete(id):
    store = Store.query.get_or_404(id)
    db.session.delete(store)
    db.session.commit()
    flash('매장이 삭제되었습니다.', 'success')
    return redirect(url_for('admin.stores_list'))


# ============================================
# 제품 관리
# ============================================

@admin_bp.route('/products')
@login_required
@admin_required
def products_list():
    """Products list - admin only"""
    sort = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    if sort == 'franchise':
        # Join with Franchise to sort by franchise name
        query = Product.query.join(Franchise, Product.franchise_id == Franchise.id, isouter=True)
        order_col = Franchise.name.desc() if order == 'desc' else Franchise.name.asc()
    elif sort == 'category':
        query = Product.query
        order_col = Product.category.desc() if order == 'desc' else Product.category.asc()
    elif sort == 'created_at':
        query = Product.query
        order_col = Product.created_at.desc() if order == 'desc' else Product.created_at.asc()
    else:  # default: id
        query = Product.query
        order_col = Product.id.desc() if order == 'desc' else Product.id.asc()

    if current_user.is_branch():
        # Branch users only see products from franchises that have stores in their branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids if f[0] is not None]
        if franchise_ids:
            query = query.filter(Product.franchise_id.in_(franchise_ids))
            franchises = Franchise.query.filter(Franchise.id.in_(franchise_ids)).order_by(Franchise.name).all()
        else:
            franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    else:
        franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()

    products = query.order_by(order_col).all()
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    return render_template('admin/products_list.html', products=products, franchises=franchises, categories=categories, sort=sort, order=order)


@admin_bp.route('/products/add', methods=['POST'])
@login_required
@admin_required
def products_add():
    category = request.form.get('category')
    unit_price = request.form.get('unit_price')
    franchise_id = request.form.get('franchise_id')

    if not category or not unit_price or not franchise_id:
        flash('품목, 프랜차이즈, 단가는 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.products_list'))

    try:
        unit_price = int(unit_price)
        franchise_id = int(franchise_id)
    except ValueError:
        flash('잘못된 입력값입니다.', 'danger')
        return redirect(url_for('admin.products_list'))

    # Get franchise name for product name
    franchise = Franchise.query.get(franchise_id)
    if not franchise:
        flash('프랜차이즈를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('admin.products_list'))

    # Auto-generate product name from franchise name and category
    name = f"{franchise.name} {category}"

    product = Product(
        name=name,
        category=category,
        unit_price=unit_price,
        franchise_id=franchise_id
    )
    db.session.add(product)
    db.session.commit()

    flash('제품이 등록되었습니다.', 'success')
    return redirect(url_for('admin.products_list'))


@admin_bp.route('/products/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def products_edit(id):
    product = Product.query.get_or_404(id)

    category = request.form.get('category')
    unit_price = request.form.get('unit_price')
    franchise_id = request.form.get('franchise_id')

    if not category or not unit_price or not franchise_id:
        flash('품목, 프랜차이즈, 단가는 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.products_list'))

    try:
        unit_price = int(unit_price)
        franchise_id = int(franchise_id)
    except ValueError:
        flash('잘못된 입력값입니다.', 'danger')
        return redirect(url_for('admin.products_list'))

    # Get franchise name for product name
    franchise = Franchise.query.get(franchise_id)
    if not franchise:
        flash('프랜차이즈를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('admin.products_list'))

    # Auto-generate product name from franchise name and category
    product.name = f"{franchise.name} {category}"
    product.category = category
    product.unit_price = unit_price
    product.franchise_id = franchise_id
    db.session.commit()

    flash('제품 정보가 수정되었습니다.', 'success')
    return redirect(url_for('admin.products_list'))


@admin_bp.route('/products/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def products_toggle(id):
    product = Product.query.get_or_404(id)
    product.is_active = not product.is_active
    db.session.commit()
    status = '활성화' if product.is_active else '비활성화'
    flash(f'제품이 {status}되었습니다.', 'success')
    return redirect(url_for('admin.products_list'))


@admin_bp.route('/products/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def products_delete(id):
    product = Product.query.get_or_404(id)
    try:
        # Delete related records first (FK constraints)
        StockIn.query.filter_by(product_id=id).delete()
        ShipmentItem.query.filter_by(product_id=id).delete()
        Payment.query.filter_by(product_id=id).delete()
        db.session.delete(product)
        db.session.commit()
        flash('제품이 삭제되었습니다.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'삭제 중 오류가 발생했습니다: {str(e)}', 'danger')
    return redirect(url_for('admin.products_list'))


# ============================================
# 출고 관리 (Shipments) - Admin + Branch users
# ============================================

@admin_bp.route('/shipments')
@login_required
@branch_required
def shipments_list():
    # Get filter parameters
    category = request.args.get('category')
    franchise_id = request.args.get('franchise_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    jungsung_id = request.args.get('jungsung_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Parse date filters once
    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None

    if current_user.is_admin():
        # Admin 출고 = StockIn records with record_type='transfer' (admin shipped to branches)
        query = StockIn.query.filter(StockIn.is_active == True, StockIn.record_type == 'transfer')
        if branch_id:
            query = query.filter(StockIn.branch_id == branch_id)
        if category or franchise_id:
            query = query.join(Product)
            if category:
                query = query.filter(Product.category == category)
            if franchise_id:
                query = query.filter(Product.franchise_id == franchise_id)
        if date_from_parsed:
            query = query.filter(StockIn.stock_date >= date_from_parsed)
        if date_to_parsed:
            query = query.filter(StockIn.stock_date <= date_to_parsed)
        items = query.options(
            joinedload(StockIn.product).joinedload(Product.franchise),
            joinedload(StockIn.branch),
            joinedload(StockIn.creator)
        ).order_by(StockIn.stock_date.desc(), StockIn.id.desc()).all()

        # Stats use StockIn for admin
        today = kst_today()
        first_of_month = today.replace(day=1)
        first_of_prev_month = (first_of_month - timedelta(days=1)).replace(day=1)

        products_query = Product.query.filter_by(is_active=True)
        if category:
            products_query = products_query.filter(Product.category == category)
        if franchise_id:
            products_query = products_query.filter(Product.franchise_id == franchise_id)
        products_for_stats = products_query.all()

        product_stats = []
        for product in products_for_stats:
            base_filter = [
                StockIn.product_id == product.id,
                StockIn.is_active == True,
                StockIn.record_type == 'transfer'
            ]
            if branch_id:
                base_filter.append(StockIn.branch_id == branch_id)

            if date_from_parsed or date_to_parsed:
                filtered_qty = db.session.query(func.sum(StockIn.quantity)).filter(*base_filter)
                if date_from_parsed:
                    filtered_qty = filtered_qty.filter(StockIn.stock_date >= date_from_parsed)
                if date_to_parsed:
                    filtered_qty = filtered_qty.filter(StockIn.stock_date <= date_to_parsed)
                filtered_qty = filtered_qty.scalar() or 0
                product_stats.append({'product': product, 'today': 0, 'this_month': filtered_qty, 'prev_month': 0})
            else:
                today_qty = db.session.query(func.sum(StockIn.quantity)).filter(*base_filter, StockIn.stock_date == today).scalar() or 0
                month_qty = db.session.query(func.sum(StockIn.quantity)).filter(*base_filter, StockIn.stock_date >= first_of_month, StockIn.stock_date <= today).scalar() or 0
                prev_month_qty = db.session.query(func.sum(StockIn.quantity)).filter(*base_filter, StockIn.stock_date >= first_of_prev_month, StockIn.stock_date < first_of_month).scalar() or 0
                product_stats.append({'product': product, 'today': today_qty, 'this_month': month_qty, 'prev_month': prev_month_qty})

    else:
        # Branch 출고 = ShipmentItem records
        query = ShipmentItem.query.filter(ShipmentItem.is_active == True)
        query = query.filter(ShipmentItem.branch_id == current_user.branch_id)
        if category or franchise_id:
            query = query.join(Product)
            if category:
                query = query.filter(Product.category == category)
            if franchise_id:
                query = query.filter(Product.franchise_id == franchise_id)
        if jungsung_id:
            query = query.filter(ShipmentItem.jungsung_id == jungsung_id)
        if date_from_parsed:
            query = query.filter(ShipmentItem.shipment_date >= date_from_parsed)
        if date_to_parsed:
            query = query.filter(ShipmentItem.shipment_date <= date_to_parsed)
        items = query.options(
            joinedload(ShipmentItem.product).joinedload(Product.franchise),
            joinedload(ShipmentItem.branch),
            joinedload(ShipmentItem.jungsung),
            joinedload(ShipmentItem.creator)
        ).order_by(ShipmentItem.shipment_date.desc(), ShipmentItem.id.desc()).all()

        # Stats use ShipmentItem for branch
        today = kst_today()
        first_of_month = today.replace(day=1)
        first_of_prev_month = (first_of_month - timedelta(days=1)).replace(day=1)

        products_query = Product.query.filter_by(is_active=True)
        if category:
            products_query = products_query.filter(Product.category == category)
        if franchise_id:
            products_query = products_query.filter(Product.franchise_id == franchise_id)
        products_for_stats = products_query.all()

        product_stats = []
        for product in products_for_stats:
            base_filter = [
                ShipmentItem.product_id == product.id,
                ShipmentItem.is_active == True,
                ShipmentItem.branch_id == current_user.branch_id
            ]
            if jungsung_id:
                base_filter.append(ShipmentItem.jungsung_id == jungsung_id)

            if date_from_parsed or date_to_parsed:
                filtered_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(*base_filter)
                if date_from_parsed:
                    filtered_qty = filtered_qty.filter(ShipmentItem.shipment_date >= date_from_parsed)
                if date_to_parsed:
                    filtered_qty = filtered_qty.filter(ShipmentItem.shipment_date <= date_to_parsed)
                filtered_qty = filtered_qty.scalar() or 0
                product_stats.append({'product': product, 'today': 0, 'this_month': filtered_qty, 'prev_month': 0})
            else:
                today_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(*base_filter, ShipmentItem.shipment_date == today).scalar() or 0
                month_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(*base_filter, ShipmentItem.shipment_date >= first_of_month, ShipmentItem.shipment_date <= today).scalar() or 0
                prev_month_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(*base_filter, ShipmentItem.shipment_date >= first_of_prev_month, ShipmentItem.shipment_date < first_of_month).scalar() or 0
                product_stats.append({'product': product, 'today': today_qty, 'this_month': month_qty, 'prev_month': prev_month_qty})

    # Get data for filters
    categories = db.session.query(Product.category).filter(Product.is_active == True).distinct().all()
    categories = [c[0] for c in categories]

    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = []
        stores = []
        all_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()
        stores = Store.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Store.name).all()

        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids if f[0] is not None]
        if franchise_ids:
            all_products = Product.query.filter(
                Product.is_active == True,
                Product.franchise_id.in_(franchise_ids)
            ).order_by(Product.name).all()
        else:
            all_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    # Build unique franchise list and franchise-category data for JS filtering
    all_franchises = Franchise.query.filter_by(is_active=True).options(
        joinedload(Franchise.categories)
    ).order_by(Franchise.name).all()
    franchise_category_data = []
    for f in all_franchises:
        franchise_category_data.append({
            'id': f.id,
            'name': f.name,
            'categories': [c.name for c in f.categories]
        })

    return render_template('admin/shipments_list.html',
                           items=items,
                           product_stats=product_stats,
                           products=all_products,
                           franchises=all_franchises,
                           franchise_category_data=franchise_category_data,
                           categories=categories,
                           branches=branches,
                           jungsungs=jungsungs,
                           stores=stores,
                           filters={
                               'category': category,
                               'franchise_id': franchise_id,
                               'branch_id': branch_id,
                               'jungsung_id': jungsung_id,
                               'date_from': date_from,
                               'date_to': date_to
                           })


@admin_bp.route('/shipments/create')
@login_required
@branch_required
def shipments_create():
    """Page to create a new shipment with multiple items"""
    categories = db.session.query(Product.category).filter(Product.is_active == True).distinct().all()
    categories = [c[0] for c in categories]

    # For branch users, only show their branch's data
    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()
        stores = Store.query.filter_by(is_active=True).order_by(Store.name).all()
        products = Product.query.filter_by(is_active=True).order_by(Product.category, Product.name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()
        stores = Store.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Store.name).all()

        # Get products from franchises that have stores in this branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids if f[0] is not None]
        if franchise_ids:
            products = Product.query.filter(
                Product.is_active == True,
                Product.franchise_id.in_(franchise_ids)
            ).order_by(Product.category, Product.name).all()
        else:
            # Fallback: show all active products if no franchise match
            products = Product.query.filter_by(is_active=True).order_by(Product.category, Product.name).all()

    all_franchises = Franchise.query.filter_by(is_active=True).options(
        joinedload(Franchise.categories)
    ).order_by(Franchise.name).all()
    franchise_category_data = []
    for f in all_franchises:
        franchise_category_data.append({
            'id': f.id,
            'name': f.name,
            'categories': [c.name for c in f.categories]
        })

    return render_template('admin/shipments_create.html',
                           branches=branches,
                           jungsungs=jungsungs,
                           stores=stores,
                           products=products,
                           categories=categories,
                           franchises=all_franchises,
                           franchise_category_data=franchise_category_data,
                           today=kst_today().strftime('%Y-%m-%d'))


@admin_bp.route('/shipments/submit', methods=['POST'])
@login_required
@branch_required
def shipments_submit():
    """Submit a new shipment with items (each item has its own date)"""
    memo = request.form.get('memo')

    # Get items from form (multiple items with per-item dates)
    shipment_dates = request.form.getlist('shipment_date[]')
    branch_ids = request.form.getlist('branch_id[]')
    jungsung_ids = request.form.getlist('jungsung_id[]')
    product_ids = request.form.getlist('product_id[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')

    if not product_ids or len(product_ids) == 0:
        flash('출고 항목을 추가해주세요.', 'danger')
        return redirect(url_for('admin.shipments_create'))

    # Separate admin→지사 items (save as 입고 only) from regular shipments
    shipment = None
    total = 0
    stockin_count = 0
    shipment_count = 0

    for i in range(len(product_ids)):
        if not product_ids[i] or not quantities[i] or not unit_prices[i]:
            continue

        item_date = datetime.strptime(shipment_dates[i], '%Y-%m-%d').date() if i < len(shipment_dates) and shipment_dates[i] else kst_today()
        qty = int(quantities[i])
        price = int(unit_prices[i])
        item_total = qty * price
        total += item_total

        # For branch users, use their branch_id if not specified
        item_branch_id = int(branch_ids[i]) if branch_ids[i] else None
        if not item_branch_id and not current_user.is_admin():
            item_branch_id = current_user.branch_id

        # Get jungsung_id if specified
        item_jungsung_id = int(jungsung_ids[i]) if i < len(jungsung_ids) and jungsung_ids[i] else None

        if current_user.is_admin() and item_branch_id:
            # Admin 출고 to 지사 → save as StockIn with record_type='transfer'
            branch_stockin = StockIn(
                stock_date=item_date,
                record_type='transfer',
                branch_id=item_branch_id,
                product_id=int(product_ids[i]),
                quantity=qty,
                unit_price=price,
                total_price=item_total,
                created_by=current_user.id
            )
            db.session.add(branch_stockin)
            stockin_count += 1
        else:
            # Regular shipment (지사 출고)
            if not shipment:
                first_date = datetime.strptime(shipment_dates[0], '%Y-%m-%d').date() if shipment_dates else kst_today()
                shipment = Shipment(
                    shipment_date=first_date,
                    memo=memo
                )
                db.session.add(shipment)
                db.session.flush()

            item = ShipmentItem(
                shipment_id=shipment.id,
                shipment_date=item_date,
                branch_id=item_branch_id,
                jungsung_id=item_jungsung_id,
                product_id=int(product_ids[i]),
                quantity=qty,
                unit_price=price,
                total_price=item_total,
                created_by=current_user.id
            )
            db.session.add(item)
            shipment_count += 1

    if shipment:
        shipment.total_amount = total

    db.session.commit()

    if stockin_count > 0 and shipment_count > 0:
        flash(f'출고 {stockin_count + shipment_count}건이 등록되었습니다.', 'success')
    elif stockin_count > 0:
        flash(f'출고 {stockin_count}건이 등록되었습니다.', 'success')
    else:
        flash('출고가 등록되었습니다.', 'success')

    return redirect(url_for('admin.shipments_list'))


@admin_bp.route('/shipments/delete', methods=['POST'])
@login_required
@branch_required
def shipments_delete():
    """Delete selected shipment items"""
    data = request.get_json()
    item_ids = data.get('item_ids', [])

    if not item_ids:
        return jsonify({'success': False, 'message': '삭제할 항목을 선택해주세요.'}), 400

    try:
        # Soft delete by setting is_active to False
        deleted_count = 0
        for item_id in item_ids:
            item = ShipmentItem.query.get(item_id)
            if item:
                # Check if user has permission to delete this item
                if current_user.is_admin() or item.branch_id == current_user.branch_id:
                    item.is_active = False
                    deleted_count += 1

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'{deleted_count}개의 항목이 삭제되었습니다.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': '삭제 중 오류가 발생했습니다.'}), 500


@admin_bp.route('/shipments/<int:id>/edit', methods=['POST'])
@login_required
@branch_required
def shipments_edit(id):
    """Edit a shipment item"""
    item = ShipmentItem.query.get_or_404(id)

    # Check permission
    if not current_user.is_admin() and item.branch_id != current_user.branch_id:
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('admin.shipments_list'))

    shipment_date_str = request.form.get('shipment_date')
    branch_id = request.form.get('branch_id') or None
    jungsung_id = request.form.get('jungsung_id') or None
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity')
    unit_price = request.form.get('unit_price')

    if not shipment_date_str or not product_id or not quantity or not unit_price:
        flash('출고일, 제품, 수량, 단가는 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.shipments_list'))

    try:
        shipment_date = datetime.strptime(shipment_date_str, '%Y-%m-%d').date()
        qty = int(quantity)
        price = int(unit_price)
    except ValueError:
        flash('올바른 값을 입력해주세요.', 'danger')
        return redirect(url_for('admin.shipments_list'))

    item.shipment_date = shipment_date
    if current_user.is_admin():
        item.branch_id = int(branch_id) if branch_id else None
    item.jungsung_id = int(jungsung_id) if jungsung_id else None
    item.product_id = int(product_id)
    item.quantity = qty
    item.unit_price = price
    item.total_price = qty * price
    db.session.commit()

    flash('출고 정보가 수정되었습니다.', 'success')
    return redirect(url_for('admin.shipments_list'))


@admin_bp.route('/api/product/<int:product_id>')
@login_required
@branch_required
def api_product_detail(product_id):
    """API to get product details including unit price"""
    product = Product.query.get_or_404(product_id)
    return jsonify({
        'id': product.id,
        'name': product.name,
        'category': product.category,
        'unit_price': product.unit_price
    })


@admin_bp.route('/api/stores-by-branch/<int:branch_id>')
@login_required
@branch_required
def api_stores_by_branch(branch_id):
    """API to get stores filtered by branch"""
    # Branch users can only access their own branch's stores
    if not current_user.is_admin() and branch_id != current_user.branch_id:
        return jsonify([])

    stores = Store.query.filter_by(branch_id=branch_id, is_active=True).order_by(Store.name).all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'franchise_name': s.franchise.name if s.franchise else ''
    } for s in stores])


@admin_bp.route('/api/jungsungs-by-branch/<int:branch_id>')
@login_required
@branch_required
def api_jungsungs_by_branch(branch_id):
    """API to get jungsungs filtered by branch"""
    # Branch users can only access their own branch's jungsungs
    if not current_user.is_admin() and branch_id != current_user.branch_id:
        return jsonify([])

    jungsungs = Jungsung.query.filter_by(branch_id=branch_id, is_active=True).order_by(Jungsung.business_name).all()
    return jsonify([{
        'id': j.id,
        'business_name': j.business_name
    } for j in jungsungs])


# ============================================
# 입고 관리 (Stock In) - Admin + Branch users
# ============================================

@admin_bp.route('/stockins')
@login_required
@branch_required
def stockins_list():
    # Get filter parameters
    category = request.args.get('category')
    franchise_id = request.args.get('franchise_id', type=int)
    supplier_id = request.args.get('supplier_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Base query
    query = StockIn.query.filter_by(is_active=True)

    # Admin sees only incoming stock (record_type='incoming'), branch users see transfers to their branch
    if current_user.is_admin():
        if branch_id:
            query = query.filter(StockIn.branch_id == branch_id)
        else:
            query = query.filter(StockIn.record_type == 'incoming')
    elif current_user.is_branch() and current_user.branch_id:
        query = query.filter(StockIn.record_type == 'transfer', StockIn.branch_id == current_user.branch_id)

    # Apply filters (join Product once if needed)
    if category or franchise_id:
        query = query.join(Product)
        if category:
            query = query.filter(Product.category == category)
        if franchise_id:
            query = query.filter(Product.franchise_id == franchise_id)
    if supplier_id:
        query = query.filter(StockIn.supplier_id == supplier_id)
    if date_from:
        query = query.filter(StockIn.stock_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(StockIn.stock_date <= datetime.strptime(date_to, '%Y-%m-%d').date())

    stockins = query.options(
        joinedload(StockIn.product).joinedload(Product.franchise),
        joinedload(StockIn.supplier),
        joinedload(StockIn.branch),
        joinedload(StockIn.creator)
    ).order_by(StockIn.stock_date.desc(), StockIn.id.desc()).all()

    # Get data for filters
    categories = db.session.query(Product.category).filter(Product.is_active == True).distinct().all()
    categories = [c[0] for c in categories]

    if current_user.is_admin():
        # Admin sees all
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
        products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    else:
        # Branch users only see their branch and products from their franchises
        branches = [current_user.branch] if current_user.branch else []
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()

        # Get products from franchises that have stores in this branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids if f[0] is not None]
        if franchise_ids:
            products = Product.query.filter(
                Product.is_active == True,
                Product.franchise_id.in_(franchise_ids)
            ).order_by(Product.name).all()
        else:
            products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    # Build unique franchise list and franchise-category data for JS filtering
    all_franchises = Franchise.query.filter_by(is_active=True).options(
        joinedload(Franchise.categories)
    ).order_by(Franchise.name).all()
    franchise_category_data = []
    for f in all_franchises:
        franchise_category_data.append({
            'id': f.id,
            'name': f.name,
            'categories': [c.name for c in f.categories]
        })

    return render_template('admin/stockins_list.html',
                           stockins=stockins,
                           products=products,
                           franchises=all_franchises,
                           franchise_category_data=franchise_category_data,
                           suppliers=suppliers,
                           branches=branches,
                           categories=categories,
                           filters={
                               'category': category,
                               'franchise_id': franchise_id,
                               'supplier_id': supplier_id,
                               'branch_id': branch_id,
                               'date_from': date_from,
                               'date_to': date_to
                           })


@admin_bp.route('/stockins/create')
@login_required
@branch_required
def stockins_create():
    """입고하기 페이지 - 여러 항목을 한번에 입고"""
    categories = db.session.query(Product.category).filter(Product.is_active == True).distinct().all()
    categories = [c[0] for c in categories]
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()

    if current_user.is_admin():
        # Admin sees all
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        products = Product.query.filter_by(is_active=True).order_by(Product.category, Product.name).all()
    else:
        # Branch users only see their branch and products from their franchises
        branches = [current_user.branch] if current_user.branch else []

        # Get products from franchises that have stores in this branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids if f[0] is not None]
        if franchise_ids:
            products = Product.query.filter(
                Product.is_active == True,
                Product.franchise_id.in_(franchise_ids)
            ).order_by(Product.category, Product.name).all()
        else:
            # Fallback: show all active products if no franchise match
            products = Product.query.filter_by(is_active=True).order_by(Product.category, Product.name).all()

    return render_template('admin/stockins_create.html',
                           products=products,
                           suppliers=suppliers,
                           branches=branches,
                           categories=categories,
                           today=kst_today().isoformat())


@admin_bp.route('/stockins/submit', methods=['POST'])
@login_required
@branch_required
def stockins_submit():
    """입고 항목들을 한번에 저장"""
    stock_dates = request.form.getlist('stock_date[]')
    branch_ids = request.form.getlist('branch_id[]')
    supplier_ids = request.form.getlist('supplier_id[]')
    product_ids = request.form.getlist('product_id[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')

    if not product_ids:
        flash('입고할 항목을 추가해주세요.', 'danger')
        return redirect(url_for('admin.stockins_create'))

    try:
        for i in range(len(product_ids)):
            stock_date = datetime.strptime(stock_dates[i], '%Y-%m-%d').date()
            # Admin 입고 has no branch; branch users use their own branch
            if current_user.is_admin():
                branch_id = None
                record_type = 'incoming'
            elif branch_ids and branch_ids[i]:
                branch_id = int(branch_ids[i])
                record_type = 'transfer'
            else:
                branch_id = current_user.branch_id
                record_type = 'transfer'
            supplier_id = int(supplier_ids[i]) if supplier_ids[i] else None
            product_id = int(product_ids[i])
            qty = int(quantities[i])
            price = int(unit_prices[i])

            stockin = StockIn(
                stock_date=stock_date,
                record_type=record_type,
                branch_id=branch_id,
                supplier_id=supplier_id,
                product_id=product_id,
                quantity=qty,
                unit_price=price,
                total_price=qty * price,
                created_by=current_user.id
            )
            db.session.add(stockin)

        db.session.commit()
        flash(f'{len(product_ids)}건의 입고가 등록되었습니다.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'입고 등록 중 오류가 발생했습니다: {str(e)}', 'danger')
        return redirect(url_for('admin.stockins_create'))

    return redirect(url_for('admin.stockins_list'))


@admin_bp.route('/stockins/add', methods=['POST'])
@login_required
@branch_required
def stockins_add():
    stock_date_str = request.form.get('stock_date')
    branch_id = request.form.get('branch_id') or None
    supplier_id = request.form.get('supplier_id') or None
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity')
    unit_price = request.form.get('unit_price')
    memo = request.form.get('memo')

    if not stock_date_str or not product_id or not quantity or not unit_price:
        flash('입고일, 제품, 수량, 단가는 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.stockins_list'))

    try:
        stock_date = datetime.strptime(stock_date_str, '%Y-%m-%d').date()
        qty = int(quantity)
        price = int(unit_price)
    except ValueError:
        flash('올바른 값을 입력해주세요.', 'danger')
        return redirect(url_for('admin.stockins_list'))

    # Admin 입고 has no branch; branch users use their own branch
    if current_user.is_admin():
        branch_id = None
        record_type = 'incoming'
    elif current_user.is_branch() and current_user.branch_id:
        branch_id = current_user.branch_id
        record_type = 'transfer'
    elif branch_id:
        branch_id = int(branch_id)
        record_type = 'transfer'
    else:
        record_type = 'incoming'

    stockin = StockIn(
        stock_date=stock_date,
        record_type=record_type,
        branch_id=branch_id,
        supplier_id=int(supplier_id) if supplier_id else None,
        product_id=int(product_id),
        quantity=qty,
        unit_price=price,
        total_price=qty * price,
        memo=memo,
        created_by=current_user.id
    )
    db.session.add(stockin)
    db.session.commit()

    flash('입고가 등록되었습니다.', 'success')
    return redirect(url_for('admin.stockins_list'))


@admin_bp.route('/stockins/<int:id>/edit', methods=['POST'])
@login_required
@branch_required
def stockins_edit(id):
    stockin = StockIn.query.get_or_404(id)

    stock_date_str = request.form.get('stock_date')
    branch_id = request.form.get('branch_id') or None
    supplier_id = request.form.get('supplier_id') or None
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity')
    unit_price = request.form.get('unit_price')
    memo = request.form.get('memo')

    if not stock_date_str or not product_id or not quantity or not unit_price:
        flash('입고일, 제품, 수량, 단가는 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.stockins_list'))

    try:
        stock_date = datetime.strptime(stock_date_str, '%Y-%m-%d').date()
        qty = int(quantity)
        price = int(unit_price)
    except ValueError:
        flash('올바른 값을 입력해주세요.', 'danger')
        return redirect(url_for('admin.stockins_list'))

    stockin.stock_date = stock_date
    # 관리자만 지사 변경 가능, 지사 사용자는 본인 지사 유지
    if current_user.is_admin():
        stockin.branch_id = int(branch_id) if branch_id else None
    stockin.supplier_id = int(supplier_id) if supplier_id else None
    stockin.product_id = int(product_id)
    stockin.quantity = qty
    stockin.unit_price = price
    stockin.total_price = qty * price
    stockin.memo = memo
    db.session.commit()

    # Redirect to correct page based on context
    if stockin.branch_id and current_user.is_admin():
        flash('출고 정보가 수정되었습니다.', 'success')
        return redirect(url_for('admin.shipments_list'))
    flash('입고 정보가 수정되었습니다.', 'success')
    return redirect(url_for('admin.stockins_list'))


@admin_bp.route('/stockins/delete', methods=['POST'])
@login_required
@branch_required
def stockins_delete():
    """Delete selected stock in items"""
    data = request.get_json()
    item_ids = data.get('item_ids', [])

    if not item_ids:
        return jsonify({'success': False, 'message': '삭제할 항목을 선택해주세요.'}), 400

    try:
        # Soft delete by setting is_active to False
        deleted_count = 0
        for item_id in item_ids:
            item = StockIn.query.get(item_id)
            if item:
                # Check if user has permission to delete this item
                if current_user.is_admin() or item.branch_id == current_user.branch_id:
                    item.is_active = False
                    deleted_count += 1

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'{deleted_count}개의 항목이 삭제되었습니다.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': '삭제 중 오류가 발생했습니다.'}), 500


# ============================================
# Helper: parse inventory period parameters
# ============================================
def _parse_inventory_period(args):
    """Parse common period parameters for inventory pages"""
    from calendar import monthrange
    today = kst_today()
    current_year = today.year
    current_month = today.month

    period_type = args.get('period_type', 'month')
    year = args.get('year', type=int) or current_year
    month = args.get('month', type=int) or current_month
    date_from = args.get('date_from')
    date_to = args.get('date_to')

    if period_type == 'range' and date_from and date_to:
        date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
        date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
    else:
        period_type = 'month'
        _, last_day = monthrange(year, month)
        date_from_parsed = date(year, month, 1)
        date_to_parsed = date(year, month, last_day)

    return {
        'period_type': period_type, 'year': year, 'month': month,
        'date_from': date_from, 'date_to': date_to,
        'date_from_parsed': date_from_parsed, 'date_to_parsed': date_to_parsed,
        'current_year': current_year
    }


def _get_valid_product_ids():
    """Get product IDs whose category matches their franchise's franchise_categories"""
    all_franchises_for_map = Franchise.query.filter_by(is_active=True).all()
    franchise_cat_map = {}
    for f in all_franchises_for_map:
        franchise_cat_map[f.id] = [c.name for c in f.categories] if f.categories else []

    all_valid_products = Product.query.filter_by(is_active=True).all()
    return [p.id for p in all_valid_products if (
        not p.franchise_id or
        not franchise_cat_map.get(p.franchise_id) or
        p.category in franchise_cat_map.get(p.franchise_id, [])
    )]


def _get_cat_franchise_map():
    """Build category→franchises map and all_category_names for cascading filter"""
    franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    cat_franchise_map = {}
    all_category_names = set()
    for f in franchises:
        for c in f.categories:
            all_category_names.add(c.name)
            if c.name not in cat_franchise_map:
                cat_franchise_map[c.name] = []
            cat_franchise_map[c.name].append({'id': f.id, 'name': f.name})
    return cat_franchise_map, sorted(all_category_names), franchises


# ============================================
# 본사 재고현황 (HQ Inventory Status) - Admin only
# ============================================

@admin_bp.route('/inventory')
@login_required
@branch_required
def inventory_status():
    """Redirect to appropriate inventory page"""
    if current_user.is_admin():
        return redirect(url_for('admin.hq_inventory', **request.args))
    else:
        return redirect(url_for('admin.branch_inventory', **request.args))


@admin_bp.route('/inventory/hq')
@login_required
@admin_required
def hq_inventory():
    """본사 재고현황 - HQ Inventory Status (Admin only)"""
    period = _parse_inventory_period(request.args)
    date_from_parsed = period['date_from_parsed']
    date_to_parsed = period['date_to_parsed']
    valid_product_ids = _get_valid_product_ids()

    # Filters
    franchise_id = request.args.get('franchise_id', type=int)
    franchise_category = request.args.get('franchise_category')
    supplier_id = request.args.get('supplier_id', type=int)
    supplier_category = request.args.get('supplier_category')
    supplier_franchise_id = request.args.get('supplier_franchise_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    branch_category = request.args.get('branch_category')
    branch_franchise_id = request.args.get('branch_franchise_id', type=int)
    cat_search = request.args.get('cat_search')
    cat_search_franchise_id = request.args.get('cat_search_franchise_id', type=int)

    # ========================================
    # 본사 전체 재고 요약: 입고(incoming) / 출고(transfer) / 재고
    # ========================================
    total_stockin = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.product_id.in_(valid_product_ids) if valid_product_ids else False,
        StockIn.record_type == 'incoming',
        StockIn.stock_date >= date_from_parsed,
        StockIn.stock_date <= date_to_parsed
    ).scalar() or 0

    total_shipment = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.product_id.in_(valid_product_ids) if valid_product_ids else False,
        StockIn.record_type == 'transfer',
        StockIn.stock_date >= date_from_parsed,
        StockIn.stock_date <= date_to_parsed
    ).scalar() or 0

    total_stats = {
        'stockin': total_stockin,
        'shipment': total_shipment,
        'stock': total_stockin - total_shipment
    }

    # Get data for filter dropdowns (needed by all sections)
    cat_franchise_map, all_category_names, franchises = _get_cat_franchise_map()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    # ========================================
    # 프랜차이즈별검색 (Franchise Search) - HQ perspective
    # Groups by franchise, each with category rows + subtotal
    # ========================================
    if franchise_id:
        target_franchises_f = [f for f in franchises if f.id == franchise_id]
    else:
        target_franchises_f = franchises

    franchise_groups = []
    for franchise_obj in target_franchises_f:
        franchise_cat_names = [c.name for c in franchise_obj.categories] if franchise_obj.categories else []
        if franchise_category:
            franchise_cat_names = [c for c in franchise_cat_names if c == franchise_category]

        product_stats = []
        group_stockin = 0
        group_shipment = 0
        for cat_name in sorted(franchise_cat_names):
            product_ids = [p.id for p in Product.query.filter_by(
                is_active=True, franchise_id=franchise_obj.id, category=cat_name
            ).all()]

            stockin_qty = 0
            shipment_qty = 0
            if product_ids:
                stockin_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                    StockIn.record_type == 'incoming',
                    StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                ).scalar() or 0

                shipment_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                    StockIn.record_type == 'transfer',
                    StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                ).scalar() or 0

            if stockin_qty == 0 and shipment_qty == 0:
                continue

            product_stats.append({
                'category': cat_name,
                'stockin': stockin_qty,
                'shipment': shipment_qty,
                'stock': stockin_qty - shipment_qty
            })
            group_stockin += stockin_qty
            group_shipment += shipment_qty

        if product_stats:
            franchise_groups.append({
                'franchise': franchise_obj,
                'products': product_stats,
                'total_stockin': group_stockin,
                'total_shipment': group_shipment,
                'total_stock': group_stockin - group_shipment
            })

    # ========================================
    # 품목별 검색 (Category Search) - HQ perspective
    # Groups by category, each with franchise rows + subtotal
    # ========================================
    if cat_search:
        target_cats = [cat_search]
    else:
        target_cats = all_category_names

    cat_groups = []
    for cat_name in sorted(target_cats):
        if cat_search_franchise_id:
            target_franchises_c = [f for f in franchises if f.id == cat_search_franchise_id]
        else:
            target_franchises_c = [f for f in franchises if cat_name in [c.name for c in f.categories]]

        cat_rows = []
        cat_stockin = 0
        cat_shipment = 0
        for franchise in target_franchises_c:
            product_ids = [p.id for p in Product.query.filter_by(
                is_active=True, franchise_id=franchise.id, category=cat_name
            ).all()]

            stockin_qty = 0
            shipment_qty = 0
            if product_ids:
                stockin_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                    StockIn.record_type == 'incoming',
                    StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                ).scalar() or 0

                shipment_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                    StockIn.record_type == 'transfer',
                    StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                ).scalar() or 0

            if stockin_qty == 0 and shipment_qty == 0:
                continue

            cat_rows.append({
                'franchise': franchise,
                'stockin': stockin_qty,
                'shipment': shipment_qty,
                'stock': stockin_qty - shipment_qty
            })
            cat_stockin += stockin_qty
            cat_shipment += shipment_qty

        if cat_rows:
            cat_groups.append({
                'category': cat_name,
                'rows': cat_rows,
                'total_stockin': cat_stockin,
                'total_shipment': cat_shipment,
                'total_stock': cat_stockin - cat_shipment
            })

    # ========================================
    # 지사별 검색 (Branch Search) - Branch perspective
    # 입고 = transfer records to this branch
    # 출고 = ShipmentItem from this branch
    # Groups by branch, each with franchise/category rows + subtotal
    # ========================================
    if branch_id:
        target_branches = [b for b in branches if b.id == branch_id]
    else:
        target_branches = branches

    branch_groups = []
    for branch_obj in target_branches:
        if branch_franchise_id:
            target_franchises_b = [f for f in franchises if f.id == branch_franchise_id]
        else:
            target_franchises_b = franchises

        branch_rows = []
        br_stockin = 0
        br_shipment = 0
        for franchise in target_franchises_b:
            cat_names = [c.name for c in franchise.categories] if franchise.categories else []
            if branch_category:
                cat_names = [c for c in cat_names if c == branch_category]

            for cat_name in sorted(cat_names):
                product_ids = [p.id for p in Product.query.filter_by(
                    is_active=True, franchise_id=franchise.id, category=cat_name
                ).all()]

                stockin_qty = 0
                shipment_qty = 0
                if product_ids:
                    # 입고: transfer records to this branch
                    stockin_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                        StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                        StockIn.record_type == 'transfer', StockIn.branch_id == branch_obj.id,
                        StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                    ).scalar() or 0

                    # 출고: shipment items from this branch
                    shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                        ShipmentItem.is_active == True, ShipmentItem.product_id.in_(product_ids),
                        ShipmentItem.branch_id == branch_obj.id,
                        ShipmentItem.shipment_date >= date_from_parsed,
                        ShipmentItem.shipment_date <= date_to_parsed
                    ).scalar() or 0

                if stockin_qty == 0 and shipment_qty == 0:
                    continue

                branch_rows.append({
                    'franchise': franchise,
                    'category': cat_name,
                    'stockin': stockin_qty,
                    'shipment': shipment_qty,
                    'stock': stockin_qty - shipment_qty
                })
                br_stockin += stockin_qty
                br_shipment += shipment_qty

        if branch_rows:
            branch_groups.append({
                'branch': branch_obj,
                'rows': branch_rows,
                'total_stockin': br_stockin,
                'total_shipment': br_shipment,
                'total_stock': br_stockin - br_shipment
            })

    # ========================================
    # 입고사 검색 (Supplier Search) - HQ perspective
    # ========================================
    if supplier_id:
        target_suppliers = [s for s in suppliers if s.id == supplier_id]
    else:
        target_suppliers = suppliers

    supplier_groups = []
    for supplier_obj in target_suppliers:
        if supplier_franchise_id:
            target_franchises_s = [f for f in franchises if f.id == supplier_franchise_id]
        else:
            target_franchises_s = franchises

        supplier_rows = []
        group_stockin = 0
        for franchise in target_franchises_s:
            cat_names = [c.name for c in franchise.categories] if franchise.categories else []
            if supplier_category:
                cat_names = [c for c in cat_names if c == supplier_category]

            for cat_name in sorted(cat_names):
                product_ids = [p.id for p in Product.query.filter_by(
                    is_active=True, franchise_id=franchise.id, category=cat_name
                ).all()]

                stockin_qty = 0
                if product_ids:
                    stockin_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                        StockIn.is_active == True, StockIn.supplier_id == supplier_obj.id,
                        StockIn.product_id.in_(product_ids), StockIn.record_type == 'incoming',
                        StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                    ).scalar() or 0

                if stockin_qty == 0:
                    continue

                supplier_rows.append({
                    'franchise': franchise,
                    'category': cat_name,
                    'stockin': stockin_qty,
                })
                group_stockin += stockin_qty

        if supplier_rows:
            supplier_groups.append({
                'supplier': supplier_obj,
                'rows': supplier_rows,
                'total_stockin': group_stockin,
            })

    return render_template('admin/hq_inventory.html',
                           year=period['year'], month=period['month'],
                           current_year=period['current_year'],
                           period_type=period['period_type'],
                           total_stats=total_stats,
                           franchise_groups=franchise_groups,
                           cat_groups=cat_groups,
                           branch_groups=branch_groups,
                           supplier_groups=supplier_groups,
                           franchises=franchises,
                           branches=branches,
                           suppliers=suppliers,
                           cat_franchise_map_json=json.dumps(cat_franchise_map),
                           all_category_names=all_category_names,
                           filters={
                               'date_from': period['date_from'],
                               'date_to': period['date_to'],
                               'franchise_id': franchise_id,
                               'franchise_category': franchise_category,
                               'branch_id': branch_id,
                               'branch_category': branch_category,
                               'branch_franchise_id': branch_franchise_id,
                               'cat_search': cat_search,
                               'cat_search_franchise_id': cat_search_franchise_id,
                               'supplier_id': supplier_id,
                               'supplier_category': supplier_category,
                               'supplier_franchise_id': supplier_franchise_id,
                           })


# ============================================
# 지사 재고현황 (Branch Inventory Status) - Admin + Branch users
# ============================================

@admin_bp.route('/inventory/branch')
@login_required
@branch_required
def branch_inventory():
    """지사 재고현황 - Branch Inventory Status (Admin + Branch users)"""
    period = _parse_inventory_period(request.args)
    date_from_parsed = period['date_from_parsed']
    date_to_parsed = period['date_to_parsed']
    valid_product_ids = _get_valid_product_ids()

    # Determine which branch to view
    if current_user.is_admin():
        view_branch_id = request.args.get('view_branch_id', type=int)
    else:
        view_branch_id = current_user.branch_id

    # Filters
    franchise_id = request.args.get('franchise_id', type=int)
    franchise_category = request.args.get('franchise_category')
    cat_search = request.args.get('cat_search')
    cat_search_franchise_id = request.args.get('cat_search_franchise_id', type=int)
    jungsung_id = request.args.get('jungsung_id', type=int)
    jungsung_franchise_id = request.args.get('jungsung_franchise_id', type=int)
    jungsung_category = request.args.get('jungsung_category')

    # ========================================
    # 지사 전체 재고 요약: 입고(transfer to branch) / 출고(shipment) / 재고
    # ========================================
    total_stats = {'stockin': 0, 'shipment': 0, 'stock': 0}
    if view_branch_id:
        total_stockin = db.session.query(func.sum(StockIn.quantity)).filter(
            StockIn.is_active == True,
            StockIn.product_id.in_(valid_product_ids) if valid_product_ids else False,
            StockIn.record_type == 'transfer',
            StockIn.branch_id == view_branch_id,
            StockIn.stock_date >= date_from_parsed,
            StockIn.stock_date <= date_to_parsed
        ).scalar() or 0

        total_shipment = db.session.query(func.sum(ShipmentItem.quantity)).filter(
            ShipmentItem.is_active == True,
            ShipmentItem.product_id.in_(valid_product_ids) if valid_product_ids else False,
            ShipmentItem.branch_id == view_branch_id,
            ShipmentItem.shipment_date >= date_from_parsed,
            ShipmentItem.shipment_date <= date_to_parsed
        ).scalar() or 0

        total_stats = {
            'stockin': total_stockin,
            'shipment': total_shipment,
            'stock': total_stockin - total_shipment
        }

    # Get data for filter dropdowns (needed by all sections)
    cat_franchise_map, all_category_names, franchises = _get_cat_franchise_map()

    # ========================================
    # 프랜차이즈별검색 (Franchise Search) - Branch perspective
    # Groups by franchise, each with category rows + subtotal
    # ========================================
    franchise_groups = []
    if view_branch_id:
        if franchise_id:
            target_franchises_f = [f for f in franchises if f.id == franchise_id]
        else:
            target_franchises_f = franchises

        for franchise_obj in target_franchises_f:
            franchise_cat_names = [c.name for c in franchise_obj.categories] if franchise_obj.categories else []
            if franchise_category:
                franchise_cat_names = [c for c in franchise_cat_names if c == franchise_category]

            product_stats = []
            group_stockin = 0
            group_shipment = 0
            for cat_name in sorted(franchise_cat_names):
                product_ids = [p.id for p in Product.query.filter_by(
                    is_active=True, franchise_id=franchise_obj.id, category=cat_name
                ).all()]

                stockin_qty = 0
                shipment_qty = 0
                if product_ids:
                    stockin_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                        StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                        StockIn.record_type == 'transfer', StockIn.branch_id == view_branch_id,
                        StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                    ).scalar() or 0

                    shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                        ShipmentItem.is_active == True, ShipmentItem.product_id.in_(product_ids),
                        ShipmentItem.branch_id == view_branch_id,
                        ShipmentItem.shipment_date >= date_from_parsed, ShipmentItem.shipment_date <= date_to_parsed
                    ).scalar() or 0

                if stockin_qty == 0 and shipment_qty == 0:
                    continue

                product_stats.append({
                    'category': cat_name,
                    'stockin': stockin_qty,
                    'shipment': shipment_qty,
                    'stock': stockin_qty - shipment_qty
                })
                group_stockin += stockin_qty
                group_shipment += shipment_qty

            if product_stats:
                franchise_groups.append({
                    'franchise': franchise_obj,
                    'products': product_stats,
                    'total_stockin': group_stockin,
                    'total_shipment': group_shipment,
                    'total_stock': group_stockin - group_shipment
                })

    # ========================================
    # 품목별검색 (Category Search) - Branch perspective
    # Groups by category, each with franchise rows + subtotal
    # ========================================
    cat_groups = []
    if view_branch_id:
        if cat_search:
            target_cats = [cat_search]
        else:
            target_cats = all_category_names

        for cat_name in sorted(target_cats):
            if cat_search_franchise_id:
                target_franchises_c = [f for f in franchises if f.id == cat_search_franchise_id]
            else:
                target_franchises_c = [f for f in franchises if cat_name in [c.name for c in f.categories]]

            cat_rows = []
            cat_stockin = 0
            cat_shipment = 0
            for franchise in target_franchises_c:
                product_ids = [p.id for p in Product.query.filter_by(
                    is_active=True, franchise_id=franchise.id, category=cat_name
                ).all()]

                stockin_qty = 0
                shipment_qty = 0
                if product_ids:
                    stockin_qty = db.session.query(func.sum(StockIn.quantity)).filter(
                        StockIn.is_active == True, StockIn.product_id.in_(product_ids),
                        StockIn.record_type == 'transfer', StockIn.branch_id == view_branch_id,
                        StockIn.stock_date >= date_from_parsed, StockIn.stock_date <= date_to_parsed
                    ).scalar() or 0

                    shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                        ShipmentItem.is_active == True, ShipmentItem.product_id.in_(product_ids),
                        ShipmentItem.branch_id == view_branch_id,
                        ShipmentItem.shipment_date >= date_from_parsed, ShipmentItem.shipment_date <= date_to_parsed
                    ).scalar() or 0

                if stockin_qty == 0 and shipment_qty == 0:
                    continue

                cat_rows.append({
                    'franchise': franchise,
                    'stockin': stockin_qty,
                    'shipment': shipment_qty,
                    'stock': stockin_qty - shipment_qty
                })
                cat_stockin += stockin_qty
                cat_shipment += shipment_qty

            if cat_rows:
                cat_groups.append({
                    'category': cat_name,
                    'rows': cat_rows,
                    'total_stockin': cat_stockin,
                    'total_shipment': cat_shipment,
                    'total_stock': cat_stockin - cat_shipment
                })

    # ========================================
    # 중상 검색 (Jungsung Search)
    # ========================================
    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()

    jungsung_groups = []
    if view_branch_id:
        if jungsung_id:
            target_jungsungs = [j for j in jungsungs if j.id == jungsung_id]
        else:
            target_jungsungs = jungsungs

        waste_cats = get_waste_category_names()

        for jungsung_obj in target_jungsungs:
            stores_query = Store.query.filter_by(jungsung_id=jungsung_obj.id, is_active=True)
            if jungsung_franchise_id:
                stores_query = stores_query.filter_by(franchise_id=jungsung_franchise_id)
            stores = stores_query.all()

            if jungsung_franchise_id:
                target_franchises = [f for f in franchises if f.id == jungsung_franchise_id]
            else:
                target_franchises = franchises

            j_rows = []
            j_shipment = 0
            j_erp = 0
            for franchise in target_franchises:
                cat_names = [c.name for c in franchise.categories] if franchise.categories else []
                if jungsung_category:
                    cat_names = [c for c in cat_names if c == jungsung_category]

                franchise_store_ids = [s.id for s in stores if s.franchise_id == franchise.id]

                for cat_name in sorted(cat_names):
                    product_ids = [p.id for p in Product.query.filter_by(
                        is_active=True, franchise_id=franchise.id, category=cat_name
                    ).all()]

                    shipment_qty = 0
                    if product_ids:
                        shipment_filters = [
                            ShipmentItem.is_active == True,
                            ShipmentItem.product_id.in_(product_ids),
                            ShipmentItem.branch_id == view_branch_id
                        ]
                        if franchise_store_ids:
                            shipment_filters.append(
                                or_(
                                    ShipmentItem.store_id.in_(franchise_store_ids),
                                    and_(ShipmentItem.jungsung_id == jungsung_obj.id, ShipmentItem.store_id == None)
                                )
                            )
                        else:
                            shipment_filters.append(
                                and_(ShipmentItem.jungsung_id == jungsung_obj.id, ShipmentItem.store_id == None)
                            )
                        shipment_query = db.session.query(func.sum(ShipmentItem.quantity)).filter(*shipment_filters)
                        shipment_query = shipment_query.filter(
                            ShipmentItem.shipment_date >= date_from_parsed,
                            ShipmentItem.shipment_date <= date_to_parsed
                        )
                        shipment_qty = shipment_query.scalar() or 0

                    erp_registered = 0
                    if franchise_store_ids and cat_name not in waste_cats:
                        erp_query = ERPRegistration.query.filter(
                            ERPRegistration.store_id.in_(franchise_store_ids),
                            ERPRegistration.is_return == False,
                            ERPRegistration.registration_date >= date_from_parsed,
                            ERPRegistration.registration_date <= date_to_parsed
                        )
                        for erp_reg in erp_query.all():
                            qty_dict = erp_reg.get_category_quantities()
                            if qty_dict and cat_name in qty_dict:
                                erp_registered += qty_dict[cat_name]

                    if shipment_qty == 0 and erp_registered == 0:
                        continue

                    j_rows.append({
                        'franchise': franchise,
                        'category': cat_name,
                        'shipment': shipment_qty,
                        'erp_registered': erp_registered,
                        'erp_unregistered': shipment_qty - erp_registered
                    })
                    j_shipment += shipment_qty
                    j_erp += erp_registered

            if j_rows:
                jungsung_groups.append({
                    'jungsung': jungsung_obj,
                    'rows': j_rows,
                    'total_shipment': j_shipment,
                    'total_erp': j_erp,
                    'total_unregistered': j_shipment - j_erp,
                })

    view_branch_obj = Branch.query.get(view_branch_id) if view_branch_id else None

    return render_template('admin/branch_inventory.html',
                           year=period['year'], month=period['month'],
                           current_year=period['current_year'],
                           period_type=period['period_type'],
                           total_stats=total_stats,
                           view_branch_id=view_branch_id,
                           view_branch_obj=view_branch_obj,
                           franchise_groups=franchise_groups,
                           cat_groups=cat_groups,
                           jungsung_groups=jungsung_groups,
                           franchises=franchises,
                           branches=branches,
                           jungsungs=jungsungs,
                           cat_franchise_map_json=json.dumps(cat_franchise_map),
                           all_category_names=all_category_names,
                           filters={
                               'date_from': period['date_from'],
                               'date_to': period['date_to'],
                               'view_branch_id': view_branch_id,
                               'franchise_id': franchise_id,
                               'franchise_category': franchise_category,
                               'cat_search': cat_search,
                               'cat_search_franchise_id': cat_search_franchise_id,
                               'jungsung_id': jungsung_id,
                               'jungsung_franchise_id': jungsung_franchise_id,
                               'jungsung_category': jungsung_category,
                           })


# ============================================
# 미수금 관리 (Accounts Receivable Management)
# ============================================

@admin_bp.route('/receivables')
@login_required
@branch_required
def receivables():
    """미수금 관리 - redirect to appropriate page"""
    return redirect(url_for('admin.receivables_hq'))


# ------------------------------------------
# 본사-지사 미수금 (HQ-Branch Receivables)
# ------------------------------------------

@admin_bp.route('/receivables/hq')
@login_required
@branch_required
def receivables_hq():
    """본사-지사 미수금 - Admin + Branch can view, Admin only can add payments"""
    view_mode = request.args.get('view_mode', 'branch')  # 'branch' (default) or 'franchise'
    franchise_id = request.args.get('franchise_id', type=int)
    product_id = request.args.get('product_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    filter_branch_id = request.args.get('branch_id', type=int)

    date_from_parsed = None
    date_to_parsed = None
    if date_from:
        try:
            date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    if date_to:
        try:
            date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Always get all branches and franchises
    if current_user.is_admin():
        all_branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    else:
        all_branches = [current_user.branch] if current_user.branch else []

    all_franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    all_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    # Determine branches for data query
    if view_mode == 'branch':
        if filter_branch_id:
            branches = [b for b in all_branches if b.id == filter_branch_id]
        else:
            branches = all_branches
    else:
        if current_user.is_admin():
            if filter_branch_id:
                branches = [Branch.query.get(filter_branch_id)]
                branches = [b for b in branches if b]
            else:
                branches = all_branches
        else:
            branches = [current_user.branch] if current_user.branch else []

    # Determine franchises for data query
    if franchise_id:
        franchises = Franchise.query.filter_by(is_active=True, id=franchise_id).order_by(Franchise.name).all()
    else:
        franchises = all_franchises

    # Build receivables data (franchise × product rows, branch columns)
    receivables_data = []
    branch_total_payments = {}

    for branch in branches:
        pq = db.session.query(func.sum(Payment.amount)).filter(
            Payment.is_active == True, Payment.payment_type == 'hq_branch',
            Payment.branch_id == branch.id
        )
        if date_from_parsed:
            pq = pq.filter(Payment.payment_date >= date_from_parsed)
        if date_to_parsed:
            pq = pq.filter(Payment.payment_date <= date_to_parsed)
        branch_total_payments[branch.id] = pq.scalar() or 0

    for franchise in franchises:
        products_query = Product.query.filter_by(is_active=True, franchise_id=franchise.id)
        if product_id:
            products_query = products_query.filter_by(id=product_id)
        products = products_query.order_by(Product.name).all()

        for product in products:
            row_data = {'franchise': franchise, 'product': product, 'branches': {}}
            total_qty = 0
            total_amount = 0
            total_paid = 0

            for branch in branches:
                stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True,
                    StockIn.record_type == 'transfer',
                    StockIn.branch_id == branch.id,
                    StockIn.product_id == product.id
                )
                if date_from_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date >= date_from_parsed)
                if date_to_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date <= date_to_parsed)
                qty = stockin_query.scalar() or 0

                amount = qty * product.unit_price if qty > 0 else 0

                payment_query = db.session.query(func.sum(Payment.amount)).filter(
                    Payment.is_active == True, Payment.payment_type == 'hq_branch',
                    Payment.branch_id == branch.id,
                    Payment.franchise_id == franchise.id,
                    Payment.product_id == product.id
                )
                if date_from_parsed:
                    payment_query = payment_query.filter(Payment.payment_date >= date_from_parsed)
                if date_to_parsed:
                    payment_query = payment_query.filter(Payment.payment_date <= date_to_parsed)
                paid = payment_query.scalar() or 0

                row_data['branches'][branch.id] = {
                    'qty': qty, 'amount': amount, 'paid': paid, 'unpaid': amount - paid
                }
                total_qty += qty
                total_amount += amount
                total_paid += paid

            row_data['total_qty'] = total_qty
            row_data['total_amount'] = total_amount
            row_data['total_paid'] = total_paid
            row_data['total_unpaid'] = total_amount - total_paid

            if total_qty > 0 or total_paid > 0:
                receivables_data.append(row_data)

    grand_total_unpaid = sum(row['total_unpaid'] for row in receivables_data)

    # Build branch-grouped data for 지사별 view (rows=branch, columns=franchise)
    branch_grouped_data = []
    if view_mode == 'branch':
        for branch in branches:
            row_data = {'branch': branch, 'franchises': {}}
            total_qty = 0
            total_amount = 0
            total_paid = 0
            for fobj in all_franchises:
                f_qty = 0
                f_amount = 0
                for row in receivables_data:
                    if row['franchise'].id == fobj.id:
                        bd = row['branches'].get(branch.id, {})
                        f_qty += bd.get('qty', 0)
                        f_amount += bd.get('amount', 0)
                # Query payments directly per branch+franchise (includes all payments)
                f_paid_q = db.session.query(func.sum(Payment.amount)).filter(
                    Payment.is_active == True, Payment.payment_type == 'hq_branch',
                    Payment.branch_id == branch.id, Payment.franchise_id == fobj.id
                )
                if date_from_parsed:
                    f_paid_q = f_paid_q.filter(Payment.payment_date >= date_from_parsed)
                if date_to_parsed:
                    f_paid_q = f_paid_q.filter(Payment.payment_date <= date_to_parsed)
                f_paid = f_paid_q.scalar() or 0
                row_data['franchises'][fobj.id] = {
                    'qty': f_qty, 'amount': f_amount, 'paid': f_paid, 'unpaid': f_amount - f_paid
                }
                total_qty += f_qty
                total_amount += f_amount
                total_paid += f_paid
            # Also include payments without franchise_id
            no_fran_paid_q = db.session.query(func.sum(Payment.amount)).filter(
                Payment.is_active == True, Payment.payment_type == 'hq_branch',
                Payment.branch_id == branch.id, Payment.franchise_id == None
            )
            if date_from_parsed:
                no_fran_paid_q = no_fran_paid_q.filter(Payment.payment_date >= date_from_parsed)
            if date_to_parsed:
                no_fran_paid_q = no_fran_paid_q.filter(Payment.payment_date <= date_to_parsed)
            total_paid += no_fran_paid_q.scalar() or 0
            row_data['total_qty'] = total_qty
            row_data['total_amount'] = total_amount
            row_data['total_paid'] = total_paid
            row_data['total_unpaid'] = total_amount - total_paid
            branch_grouped_data.append(row_data)

    return render_template('admin/receivables_hq.html',
                           branches=branches,
                           all_branches=all_branches,
                           receivables_data=receivables_data,
                           branch_grouped_data=branch_grouped_data,
                           grand_total_unpaid=grand_total_unpaid,
                           branch_total_payments=branch_total_payments,
                           all_franchises=all_franchises,
                           all_products=all_products,
                           view_mode=view_mode,
                           filters={
                               'franchise_id': franchise_id,
                               'product_id': product_id,
                               'date_from': date_from,
                               'date_to': date_to,
                               'branch_id': filter_branch_id,
                           })


# ------------------------------------------
# 본사-입고사 미수금
# ------------------------------------------

@admin_bp.route('/receivables/supplier')
@login_required
@admin_required
def receivables_supplier():
    """본사-입고사 미수금 - Admin only"""
    supplier_id = request.args.get('supplier_id', type=int)
    franchise_id = request.args.get('franchise_id', type=int)
    product_id = request.args.get('product_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    date_from_parsed = None
    date_to_parsed = None
    if date_from:
        try:
            date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    if date_to:
        try:
            date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            pass

    all_suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    all_franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    all_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    # Determine suppliers for data query
    if supplier_id:
        suppliers = [s for s in all_suppliers if s.id == supplier_id]
    else:
        suppliers = all_suppliers

    # Determine franchises for data query
    if franchise_id:
        franchises = [f for f in all_franchises if f.id == franchise_id]
    else:
        franchises = all_franchises

    # Build receivables data: supplier × franchise × product rows
    receivables_data = []

    for sup in suppliers:
        sup_total_qty = 0
        sup_total_amount = 0
        sup_total_paid = 0
        sup_rows = []

        for franchise in franchises:
            products_query = Product.query.filter_by(is_active=True, franchise_id=franchise.id)
            if product_id:
                products_query = products_query.filter_by(id=product_id)
            products = products_query.order_by(Product.name).all()

            for product in products:
                # incoming StockIn (입고사→본사)
                stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True,
                    StockIn.record_type == 'incoming',
                    StockIn.supplier_id == sup.id,
                    StockIn.product_id == product.id
                )
                if date_from_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date >= date_from_parsed)
                if date_to_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date <= date_to_parsed)
                qty = stockin_query.scalar() or 0

                amount = qty * product.unit_price if qty > 0 else 0

                # Payments from 본사 to 입고사
                payment_query = db.session.query(func.sum(Payment.amount)).filter(
                    Payment.is_active == True,
                    Payment.payment_type == 'hq_supplier',
                    Payment.supplier_id == sup.id,
                    Payment.franchise_id == franchise.id,
                    Payment.product_id == product.id
                )
                if date_from_parsed:
                    payment_query = payment_query.filter(Payment.payment_date >= date_from_parsed)
                if date_to_parsed:
                    payment_query = payment_query.filter(Payment.payment_date <= date_to_parsed)
                paid = payment_query.scalar() or 0

                if qty > 0 or paid > 0:
                    sup_rows.append({
                        'franchise': franchise,
                        'product': product,
                        'qty': qty,
                        'amount': amount,
                        'paid': paid,
                        'unpaid': amount - paid
                    })
                    sup_total_qty += qty
                    sup_total_amount += amount
                    sup_total_paid += paid

        if sup_rows:
            receivables_data.append({
                'supplier': sup,
                'rows': sup_rows,
                'total_qty': sup_total_qty,
                'total_amount': sup_total_amount,
                'total_paid': sup_total_paid,
                'total_unpaid': sup_total_amount - sup_total_paid
            })

    grand_total_unpaid = sum(g['total_unpaid'] for g in receivables_data)

    return render_template('admin/receivables_supplier.html',
                           receivables_data=receivables_data,
                           all_suppliers=all_suppliers,
                           all_franchises=all_franchises,
                           all_products=all_products,
                           grand_total_unpaid=grand_total_unpaid,
                           filters={
                               'supplier_id': supplier_id,
                               'franchise_id': franchise_id,
                               'product_id': product_id,
                               'date_from': date_from,
                               'date_to': date_to,
                           })


# ------------------------------------------
# Payment APIs
# ------------------------------------------

@admin_bp.route('/api/payments/add', methods=['POST'])
@login_required
@branch_required
def add_payment():
    """Add a new payment entry"""
    try:
        data = request.get_json()
        payment_type = data.get('payment_type', 'hq_branch')

        # 본사-지사, 본사-입고사: admin only
        if payment_type in ('hq_branch', 'hq_supplier') and not current_user.is_admin():
            return jsonify({'success': False, 'message': '관리자만 입금 등록이 가능합니다.'}), 403

        payment = Payment(
            payment_type=payment_type,
            payment_date=datetime.strptime(data['payment_date'], '%Y-%m-%d').date(),
            branch_id=data.get('branch_id'),
            jungsung_id=data.get('jungsung_id'),
            franchise_id=data.get('franchise_id'),
            product_id=data.get('product_id'),
            supplier_id=data.get('supplier_id'),
            amount=int(data['amount']),
            memo=data.get('memo'),
            created_by=current_user.id
        )

        db.session.add(payment)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '입금이 등록되었습니다.',
            'payment': {
                'id': payment.id,
                'payment_date': payment.payment_date.strftime('%Y-%m-%d'),
                'branch': payment.branch.name if payment.branch else '-',
                'amount': payment.amount,
                'memo': payment.memo
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@admin_bp.route('/api/payments/<int:payment_id>/delete', methods=['POST'])
@login_required
@branch_required
def delete_payment(payment_id):
    """Delete a payment entry"""
    try:
        payment = Payment.query.get_or_404(payment_id)

        if not current_user.is_admin() and payment.branch_id != current_user.branch_id:
            return jsonify({'success': False, 'message': '권한이 없습니다.'}), 403

        payment.is_active = False
        db.session.commit()

        return jsonify({'success': True, 'message': '입금 내역이 삭제되었습니다.'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@admin_bp.route('/api/payments/list')
@login_required
@branch_required
def list_payments():
    """Get list of payments"""
    payment_type = request.args.get('payment_type', 'hq_branch')
    branch_id = request.args.get('branch_id', type=int)
    jungsung_id = request.args.get('jungsung_id', type=int)
    franchise_id = request.args.get('franchise_id', type=int)
    product_id = request.args.get('product_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    payments_query = Payment.query.filter_by(is_active=True, payment_type=payment_type)

    if not current_user.is_admin():
        if current_user.is_branch():
            payments_query = payments_query.filter_by(branch_id=current_user.branch_id)
        elif current_user.is_jungsung() and current_user.jungsung:
            payments_query = payments_query.filter_by(jungsung_id=current_user.jungsung.id)

    supplier_id = request.args.get('supplier_id', type=int)

    if branch_id:
        payments_query = payments_query.filter_by(branch_id=branch_id)
    if jungsung_id:
        payments_query = payments_query.filter_by(jungsung_id=jungsung_id)
    if franchise_id:
        payments_query = payments_query.filter_by(franchise_id=franchise_id)
    if product_id:
        payments_query = payments_query.filter_by(product_id=product_id)
    if supplier_id:
        payments_query = payments_query.filter_by(supplier_id=supplier_id)

    if date_from:
        try:
            payments_query = payments_query.filter(Payment.payment_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            payments_query = payments_query.filter(Payment.payment_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass

    payments = payments_query.order_by(Payment.payment_date.desc()).all()

    return jsonify({
        'success': True,
        'payments': [{
            'id': p.id,
            'payment_date': p.payment_date.strftime('%Y-%m-%d'),
            'branch': p.branch.name if p.branch else '-',
            'jungsung': p.jungsung.business_name if p.jungsung else '-',
            'franchise': p.franchise.name if p.franchise else '-',
            'product': p.product.name if p.product else '-',
            'supplier': p.supplier.company_name if p.supplier else '-',
            'amount': p.amount,
            'memo': p.memo or '',
            'created_by': p.creator.username if p.creator else '-',
            'created_at': p.created_at.strftime('%Y-%m-%d %H:%M')
        } for p in payments]
    })


@admin_bp.route('/erp-tracking')
@login_required
@branch_required
def erp_tracking():
    """ERP Registration Tracking - Monthly, Date Range, and Calendar views by store
    Shows data registered by 중상 users via ERPRegistration model"""
    import json
    from calendar import monthrange

    search_type = request.args.get('search_type', 'default')

    # Category filter
    selected_category = request.args.get('category', '전체')

    # Get filter parameters
    year = request.args.get('year', type=int) or kst_today().year
    month = request.args.get('month', type=int) or kst_today().month

    # Date range filter
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Default date range to current month if not specified
    today = kst_today()
    if not date_from:
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
    if not date_to:
        date_to = today.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get active categories, filtered by selection
    all_categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()
    if selected_category == '전체':
        categories = all_categories
    else:
        categories = [c for c in all_categories if c.name == selected_category]
    category_names = [cat.name for cat in categories]

    # Get stores based on user role
    if current_user.is_admin():
        stores_query = Store.query.filter_by(is_active=True)
    elif current_user.is_jungsung() and current_user.jungsung:
        # 중상 users see stores assigned to them
        stores_query = Store.query.filter_by(is_active=True, jungsung_id=current_user.jungsung.id)
    else:
        # Branch users see stores in their branch
        stores_query = Store.query.filter_by(is_active=True, branch_id=current_user.branch_id)

    stores = stores_query.order_by(Store.branch_id, Store.franchise_id, Store.name).all()

    def get_category_totals(registrations):
        """Sum category quantities from multiple registrations"""
        totals = {cat: 0 for cat in category_names}
        for reg in registrations:
            qty_dict = reg.get_category_quantities()
            for cat, qty in qty_dict.items():
                if cat in totals:
                    totals[cat] += qty
        return totals

    # Calculate week ranges for the selected month (Mon-Sun aligned)
    weeks = build_month_weeks(year, month)

    # Build weekly data for selected month (year + month view)
    # Show ALL stores with 0 values if no data
    weekly_data = []
    for store in stores:
        store_weeks = []
        total_categories = {cat: 0 for cat in category_names}

        for week in weeks:
            # Get registrations for this store and week
            registrations = ERPRegistration.query.filter(
                ERPRegistration.store_id == store.id,
                ERPRegistration.is_return == False,
                ERPRegistration.registration_date >= week['start'],
                ERPRegistration.registration_date <= week['end']
            ).all()

            week_totals = get_category_totals(registrations)
            store_weeks.append(week_totals)

            # Add to total
            for cat in category_names:
                total_categories[cat] += week_totals[cat]

        # Include ALL stores (show 0 if no data)
        weekly_data.append({
            'store': store,
            'branch': store.branch,
            'jungsung': store.jungsung,
            'franchise': store.franchise,
            'weeks': store_weeks,
            'totals': total_categories
        })

    # Build date range data with weekly breakdown
    # Calculate week ranges for the date range (starting from Monday)
    from datetime import timedelta
    daterange_weeks = []
    week_num = 1
    current_date = date_from_parsed
    # Find the Monday of the week containing date_from
    days_since_monday = current_date.weekday()
    week_start = current_date - timedelta(days=days_since_monday)
    if week_start < date_from_parsed:
        week_start = date_from_parsed

    while week_start <= date_to_parsed:
        # End of week is Sunday or date_to, whichever comes first
        week_end = week_start + timedelta(days=6 - week_start.weekday())
        if week_end > date_to_parsed:
            week_end = date_to_parsed

        daterange_weeks.append({
            'num': week_num,
            'start': week_start,
            'end': week_end
        })

        # Move to next Monday
        week_start = week_end + timedelta(days=1)
        week_num += 1

    # Build daterange_data with weekly breakdown
    daterange_data = []
    for store in stores:
        store_weeks = []
        total_categories = {cat: 0 for cat in category_names}

        for week in daterange_weeks:
            # Get registrations for this store and week
            registrations = ERPRegistration.query.filter(
                ERPRegistration.store_id == store.id,
                ERPRegistration.is_return == False,
                ERPRegistration.registration_date >= week['start'],
                ERPRegistration.registration_date <= week['end']
            ).all()

            week_totals = get_category_totals(registrations)
            store_weeks.append(week_totals)

            # Add to total
            for cat in category_names:
                total_categories[cat] += week_totals[cat]

        # Include ALL stores (show 0 if no data)
        daterange_data.append({
            'store': store,
            'branch': store.branch,
            'jungsung': store.jungsung,
            'franchise': store.franchise,
            'weeks': store_weeks,
            'totals': total_categories
        })

    # ========================================
    # Calendar view (일별 달력) - Mon-Sun columns per week
    # ========================================
    daily_data = []
    daily_days = []
    daily_weeks_list = []
    daily_week_num = 1

    if search_type == 'calendar':
        daily_weeks_list = build_month_weeks(year, month)

        daily_week_num = request.args.get('week', type=int) or 0  # 0 = 전체 (default)
        if daily_week_num > len(daily_weeks_list):
            daily_week_num = len(daily_weeks_list)

        weekday_names = ['월', '화', '수', '목', '금', '토', '일']

        if daily_week_num == 0:
            # 전체: show all days in the month
            first_day = date(year, month, 1)
            from calendar import monthrange as mr
            last_day = date(year, month, mr(year, month)[1])
            current_d = first_day
            while current_d <= last_day:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
        else:
            selected_week = daily_weeks_list[daily_week_num - 1]
            current_d = selected_week['start']
            while current_d <= selected_week['end']:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)

        for store in stores:
            store_days = []
            total_categories = {cat: 0 for cat in category_names}

            for day_info in daily_days:
                d = day_info['date']
                registrations = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date == d
                ).all()

                day_totals = get_category_totals(registrations)
                store_days.append(day_totals)

                for cat in category_names:
                    total_categories[cat] += day_totals[cat]

            daily_data.append({
                'store': store,
                'branch': store.branch,
                'jungsung': store.jungsung,
                'franchise': store.franchise,
                'days': store_days,
                'totals': total_categories
            })

    return render_template('admin/erp_tracking.html',
                           search_type=search_type,
                           selected_category=selected_category,
                           all_categories=all_categories,
                           year=year,
                           month=month,
                           weeks=weeks,
                           categories=categories,
                           category_names=category_names,
                           weekly_data=weekly_data,
                           daterange_weeks=daterange_weeks,
                           daterange_data=daterange_data,
                           date_from=date_from,
                           date_to=date_to,
                           daily_data=daily_data,
                           daily_days=daily_days,
                           daily_weeks=daily_weeks_list,
                           daily_week_num=daily_week_num)


@admin_bp.route('/daily-shipments')
@login_required
@branch_required
def daily_shipments():
    """Daily shipment search - Admin and Branch users"""
    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    jungsung_id = request.args.get('jungsung_id', type=int)
    franchise_id = request.args.get('franchise_id', type=int)

    # Default to current month if no dates specified
    today = kst_today()
    if not date_from:
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
    if not date_to:
        date_to = today.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get all active categories from DB (never hardcode category names)
    all_categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()
    category_names = [c.name for c in all_categories]

    # Build franchise_id → [category_name] mapping from franchise_categories table
    all_franchises_ds = Franchise.query.filter_by(is_active=True).all()
    franchise_cat_map_ds = {}
    for f in all_franchises_ds:
        franchise_cat_map_ds[f.id] = [c.name for c in f.categories] if f.categories else []

    # Build product_id → (category, franchise_id) lookup from all active products
    all_products = Product.query.filter_by(is_active=True).all()
    product_info_map = {}  # product_id → {'category': str, 'franchise_id': int}
    for p in all_products:
        product_info_map[p.id] = {'category': p.category, 'franchise_id': p.franchise_id}

    # Base query
    base_query = ShipmentItem.query.filter(
        ShipmentItem.is_active == True,
        ShipmentItem.shipment_date >= date_from_parsed,
        ShipmentItem.shipment_date <= date_to_parsed
    )
    # Branch users only see their branch's shipments
    if not current_user.is_admin():
        base_query = base_query.filter(ShipmentItem.branch_id == current_user.branch_id)

    if jungsung_id:
        base_query = base_query.filter(ShipmentItem.jungsung_id == jungsung_id)

    # Get all matching shipment items
    items = base_query.order_by(ShipmentItem.shipment_date.asc()).all()

    # Group by date, jungsung (person), and franchise
    daily_data = {}
    for item in items:
        # Get product info
        prod_info = product_info_map.get(item.product_id)
        if not prod_info:
            continue
        product_category = prod_info['category']

        # Determine franchise from store or from product
        store = item.store
        item_franchise_id = None
        item_franchise = None

        if store:
            item_franchise_id = store.franchise_id
            item_franchise = store.franchise
        else:
            # Jungsung-level shipment - get franchise from product
            item_franchise_id = prod_info['franchise_id']
            if item_franchise_id:
                item_franchise = Franchise.query.get(item_franchise_id)

        if not item_franchise_id:
            continue

        if franchise_id and item_franchise_id != franchise_id:
            continue

        # Check if product's category is valid for this franchise (franchise_categories)
        valid_cats = franchise_cat_map_ds.get(item_franchise_id, [])
        if valid_cats and product_category not in valid_cats:
            continue

        key = (
            item.shipment_date,
            item.jungsung_id,
            item_franchise_id
        )

        if key not in daily_data:
            # Initialize with 0 for ALL categories dynamically
            cat_qtys = {cat: 0 for cat in category_names}
            daily_data[key] = {
                'date': item.shipment_date,
                'jungsung': item.jungsung,
                'franchise': item_franchise,
                'categories': cat_qtys
            }

        # Add quantity to the correct category
        if product_category in daily_data[key]['categories']:
            daily_data[key]['categories'][product_category] += item.quantity

    # Convert to list and sort
    daily_list = sorted(daily_data.values(), key=lambda x: (x['date'], x['jungsung'].contact_person if x['jungsung'] else ''))

    # Calculate totals per category
    category_totals = {cat: 0 for cat in category_names}
    for d in daily_list:
        for cat in category_names:
            category_totals[cat] += d['categories'].get(cat, 0)

    # Get filter dropdown data
    if current_user.is_admin():
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()
        franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    else:
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids]
        franchises = Franchise.query.filter(
            Franchise.is_active == True,
            Franchise.id.in_(franchise_ids)
        ).order_by(Franchise.name).all()

    return render_template('admin/daily_shipments.html',
                           daily_list=daily_list,
                           category_names=category_names,
                           category_totals=category_totals,
                           jungsungs=jungsungs,
                           franchises=franchises,
                           filters={
                               'date_from': date_from,
                               'date_to': date_to,
                               'jungsung_id': jungsung_id,
                               'franchise_id': franchise_id
                           })


# ============================================
# ERP 등록수량 체크 (관리자/지사 전용)
# ============================================

@admin_bp.route('/erp-tracking-admin')
@login_required
@branch_required
def erp_tracking_admin():
    """ERP Registration Quantity Check for Admin/Branch users
    Three search types: Weekly, Monthly, and Period Search"""
    from calendar import monthrange
    import json

    # Get search type (일별/주별/월별/기간)
    search_type = request.args.get('search_type', 'weekly')

    # Get filter parameters
    year = request.args.get('year', type=int) or kst_today().year
    month = request.args.get('month', type=int) or kst_today().month

    # Category filter
    selected_category = request.args.get('category', '전체')
    all_categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()

    # View mode: store or franchise
    view_mode = request.args.get('view_mode', 'store')  # store or franchise

    # Period search parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    view_type = request.args.get('view_type', 'weekly')  # 일별/주별/월별/년별

    # Set default date range if not specified
    if not date_from or not date_to:
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        date_from = first_day.strftime('%Y-%m-%d')
        date_to = last_day.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Read franchise/store filters early for product filtering
    franchise_filter = request.args.get('franchise_id', type=int)
    store_filter = request.args.get('store_id', type=int)

    # Get products filtered by category (and by franchise_categories when franchise filter is applied)
    franchise_cat_names_admin = None  # used by erp_category_sum when franchise filter active
    product_query = Product.query.filter(Product.is_active == True)

    if franchise_filter:
        # Filter products by franchise's categories from franchise_categories table
        franchise_obj = Franchise.query.get(franchise_filter)
        franchise_cat_names_admin = [c.name for c in franchise_obj.categories] if franchise_obj and franchise_obj.categories else []
        product_query = product_query.filter(Product.franchise_id == franchise_filter)
        if selected_category == '전체':
            if franchise_cat_names_admin:
                product_query = product_query.filter(
                    Product.category.in_(franchise_cat_names_admin),
                    ~Product.category.in_(get_waste_category_names())
                )
            else:
                product_query = product_query.filter(False)  # no valid categories
        else:
            product_query = product_query.filter(Product.category == selected_category)
    else:
        if selected_category == '전체':
            product_query = product_query.filter(~Product.category.in_(get_waste_category_names()))
        else:
            product_query = product_query.filter(Product.category == selected_category)

    regular_products = product_query.all()
    regular_product_ids = [p.id for p in regular_products]

    # Get branches and jungsungs based on user role
    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()
        franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()

        # Get franchises that have stores in this branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids if f[0] is not None]
        if franchise_ids:
            franchises = Franchise.query.filter(
                Franchise.is_active == True,
                Franchise.id.in_(franchise_ids)
            ).order_by(Franchise.name).all()
        else:
            franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()

    # --- Helper: build periods list for any search type ---
    def build_periods(search_type, year, month, date_from_parsed, date_to_parsed, view_type):
        """Build list of period dicts with start/end dates."""
        periods = []
        if search_type == 'weekly':
            periods = build_month_weeks(year, month)
        elif search_type == 'monthly':
            for m in range(1, 13):
                first_day = date(year, m, 1)
                last_day = date(year, m, monthrange(year, m)[1])
                periods.append({'num': m, 'name': f'{m}월', 'start': first_day, 'end': last_day})
        elif search_type == 'period':
            if view_type == 'daily':
                current = date_from_parsed
                num = 1
                while current <= date_to_parsed:
                    periods.append({'num': num, 'start': current, 'end': current, 'label': current.strftime('%m/%d')})
                    current += timedelta(days=1)
                    num += 1
            elif view_type == 'weekly':
                current = date_from_parsed
                num = 1
                while current <= date_to_parsed:
                    week_end = min(current + timedelta(days=6), date_to_parsed)
                    periods.append({'num': num, 'start': current, 'end': week_end, 'label': f'{current.strftime("%m/%d")}~{week_end.strftime("%m/%d")}'})
                    current = week_end + timedelta(days=1)
                    num += 1
            elif view_type == 'monthly':
                cy, cm = date_from_parsed.year, date_from_parsed.month
                num = 1
                while True:
                    fd = date(cy, cm, 1)
                    ld = date(cy, cm, monthrange(cy, cm)[1])
                    ps = max(fd, date_from_parsed)
                    pe = min(ld, date_to_parsed)
                    if ps > date_to_parsed:
                        break
                    periods.append({'num': num, 'start': ps, 'end': pe, 'label': f'{cy}년 {cm}월'})
                    cm += 1
                    if cm > 12:
                        cm = 1
                        cy += 1
                    num += 1
                    if pe >= date_to_parsed:
                        break
            elif view_type == 'yearly':
                num = 1
                for y in range(date_from_parsed.year, date_to_parsed.year + 1):
                    ps = max(date(y, 1, 1), date_from_parsed)
                    pe = min(date(y, 12, 31), date_to_parsed)
                    periods.append({'num': num, 'start': ps, 'end': pe, 'label': f'{y}년'})
                    num += 1
        return periods

    # Helper: sum ERP quantities based on selected category
    def erp_category_sum(qty_dict):
        if not qty_dict:
            return 0
        if selected_category == '전체':
            if franchise_cat_names_admin:
                valid_cats = set(franchise_cat_names_admin) - set(get_waste_category_names())
                return sum(v for k, v in qty_dict.items() if k in valid_cats)
            return sum(v for k, v in qty_dict.items() if k not in get_waste_category_names())
        return qty_dict.get(selected_category, 0)

    # --- Helper: batch query shipments and ERP, then build store data ---
    def batch_build_store_data(stores, periods, regular_product_ids, overall_start, overall_end):
        """Batch query all shipments and ERP registrations, then assemble per-store per-period data."""
        if not stores or not periods:
            return []

        store_ids = [s.id for s in stores]

        # Batch query: shipment quantities grouped by store_id and date
        shipment_rows = db.session.query(
            ShipmentItem.store_id,
            ShipmentItem.shipment_date,
            func.sum(ShipmentItem.quantity)
        ).filter(
            ShipmentItem.is_active == True,
            ShipmentItem.store_id.in_(store_ids),
            ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else False,
            ShipmentItem.shipment_date >= overall_start,
            ShipmentItem.shipment_date <= overall_end
        ).group_by(ShipmentItem.store_id, ShipmentItem.shipment_date).all()

        # Build shipment lookup: {store_id: {date: qty}}
        shipment_lookup = {}
        for store_id, ship_date, qty in shipment_rows:
            if store_id not in shipment_lookup:
                shipment_lookup[store_id] = {}
            shipment_lookup[store_id][ship_date] = qty or 0

        # Also query jungsung-level shipments (no store_id) and distribute to stores
        jungsung_ids = list(set(s.jungsung_id for s in stores if s.jungsung_id))
        if jungsung_ids:
            jungsung_rows = db.session.query(
                ShipmentItem.jungsung_id,
                Product.franchise_id,
                ShipmentItem.shipment_date,
                func.sum(ShipmentItem.quantity)
            ).join(Product).filter(
                ShipmentItem.is_active == True,
                ShipmentItem.jungsung_id.in_(jungsung_ids),
                ShipmentItem.store_id == None,
                ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else False,
                ShipmentItem.shipment_date >= overall_start,
                ShipmentItem.shipment_date <= overall_end
            ).group_by(ShipmentItem.jungsung_id, Product.franchise_id, ShipmentItem.shipment_date).all()

            # Build jungsung+franchise → [store_ids] map
            jf_store_map = {}
            for s in stores:
                if s.jungsung_id and s.franchise_id:
                    key = (s.jungsung_id, s.franchise_id)
                    jf_store_map.setdefault(key, []).append(s.id)

            for j_id, f_id, ship_date, qty in jungsung_rows:
                matching = jf_store_map.get((j_id, f_id), [])
                if matching:
                    per_store = qty // len(matching)
                    remainder = qty % len(matching)
                    for idx, sid in enumerate(matching):
                        sq = per_store + (1 if idx < remainder else 0)
                        if sq > 0:
                            if sid not in shipment_lookup:
                                shipment_lookup[sid] = {}
                            shipment_lookup[sid][ship_date] = shipment_lookup[sid].get(ship_date, 0) + sq

        # Batch query: all ERP registrations in the date range
        erp_rows = ERPRegistration.query.filter(
            ERPRegistration.store_id.in_(store_ids),
            ERPRegistration.is_return == False,
            ERPRegistration.registration_date >= overall_start,
            ERPRegistration.registration_date <= overall_end
        ).all()

        # Build ERP lookup and waste lookup
        erp_lookup = {}
        waste_lookup = {}
        for reg in erp_rows:
            sid = reg.store_id
            rd = reg.registration_date
            if sid not in erp_lookup:
                erp_lookup[sid] = {}
            if sid not in waste_lookup:
                waste_lookup[sid] = {}
            qty_dict = reg.get_category_quantities()
            total = erp_category_sum(qty_dict)
            erp_lookup[sid][rd] = erp_lookup[sid].get(rd, 0) + total
            waste = sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0
            waste_lookup[sid][rd] = waste_lookup[sid].get(rd, 0) + waste

        # Build store data with period breakdowns
        result = []
        for store in stores:
            sid = store.id
            store_shipments = shipment_lookup.get(sid, {})
            store_erps = erp_lookup.get(sid, {})
            store_wastes = waste_lookup.get(sid, {})

            period_results = []
            totals = {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}

            for period in periods:
                p_start = period['start']
                p_end = period['end']

                # Sum shipments for this period
                ship_qty = 0
                for d, q in store_shipments.items():
                    if p_start <= d <= p_end:
                        ship_qty += q

                # Sum ERP for this period
                erp_qty = 0
                for d, q in store_erps.items():
                    if p_start <= d <= p_end:
                        erp_qty += q

                # Sum waste for this period
                waste_qty = 0
                for d, q in store_wastes.items():
                    if p_start <= d <= p_end:
                        waste_qty += q

                unreg = ship_qty - erp_qty

                period_results.append({
                    'shipment': ship_qty,
                    'erp': erp_qty,
                    'waste': waste_qty,
                    'unregistered': unreg
                })

                totals['shipment'] += ship_qty
                totals['erp'] += erp_qty
                totals['waste'] += waste_qty
                totals['unregistered'] += unreg

            if totals['shipment'] > 0 or totals['erp'] > 0:
                result.append({
                    'store': store,
                    'branch': store.branch,
                    'jungsung': store.jungsung,
                    'franchise': store.franchise,
                    'period_data': period_results,
                    'totals': totals
                })

        return result

    def group_by_franchise(data_list, period_key):
        """Group store-level data by franchise, summing quantities."""
        franchise_map = {}
        for item in data_list:
            f = item.get('franchise')
            fid = f.id if f else 0
            if fid not in franchise_map:
                franchise_map[fid] = {
                    'store': type('obj', (object,), {'name': f.name if f else '미지정'})(),
                    'branch': item.get('branch'),
                    'jungsung': None,
                    'franchise': f,
                    period_key: None,
                    'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
                }
            entry = franchise_map[fid]
            # Initialize period data if first store
            if entry[period_key] is None:
                entry[period_key] = [{'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0} for _ in item[period_key]]
            # Sum period data
            for i, pd in enumerate(item[period_key]):
                entry[period_key][i]['shipment'] += pd.get('shipment', 0)
                entry[period_key][i]['erp'] += pd.get('erp', 0)
                entry[period_key][i]['waste'] += pd.get('waste', 0)
                entry[period_key][i]['unregistered'] += pd.get('unregistered', 0)
            # Sum totals
            for k in ('shipment', 'erp', 'waste', 'unregistered'):
                entry['totals'][k] += item['totals'].get(k, 0)
        return sorted(franchise_map.values(), key=lambda x: x['store'].name)

    # Get all stores once with eager loading
    stores_query = Store.query.filter_by(is_active=True).options(
        joinedload(Store.branch),
        joinedload(Store.jungsung),
        joinedload(Store.franchise)
    )
    if not current_user.is_admin():
        stores_query = stores_query.filter_by(branch_id=current_user.branch_id)

    # All stores for filter dropdown (before applying franchise/store filters)
    all_stores_for_filter = stores_query.order_by(Store.franchise_id, Store.name).all()

    # Build stores-by-franchise map for JS cascading
    import json
    stores_by_franchise_map = {}
    for s in all_stores_for_filter:
        fid = s.franchise_id or 0
        if fid not in stores_by_franchise_map:
            stores_by_franchise_map[fid] = []
        stores_by_franchise_map[fid].append({'id': s.id, 'name': s.name})
    stores_by_franchise_json = json.dumps(stores_by_franchise_map, ensure_ascii=False)

    # Apply franchise/store filters
    if franchise_filter:
        stores_query = stores_query.filter(Store.franchise_id == franchise_filter)
    if store_filter:
        stores_query = stores_query.filter(Store.id == store_filter)
    stores = stores_query.order_by(Store.branch_id, Store.franchise_id, Store.name).all()

    # Build periods and data based on search type
    weekly_data = []
    weeks = []
    monthly_data = []
    months_list = []
    period_data = []
    periods = []
    daily_data = []
    daily_days = []
    daily_weeks = []
    daily_week_num = 1

    if search_type == 'calendar':
        # Daily calendar: year/month/week selector, Mon-Sun columns
        daily_weeks = build_month_weeks(year, month)

        daily_week_num = request.args.get('week', type=int) or 0  # 0 = 전체 (default)
        if daily_week_num > len(daily_weeks):
            daily_week_num = len(daily_weeks)

        weekday_names = ['월', '화', '수', '목', '금', '토', '일']

        if daily_week_num == 0:
            # 전체: show all days in the month
            first_day = date(year, month, 1)
            from calendar import monthrange as mr
            last_day = date(year, month, mr(year, month)[1])
            current_d = first_day
            while current_d <= last_day:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
            overall_start = first_day
            overall_end = last_day
        else:
            selected_week = daily_weeks[daily_week_num - 1]
            current_d = selected_week['start']
            while current_d <= selected_week['end']:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
            overall_start = selected_week['start']
            overall_end = selected_week['end']

        day_periods = [{'start': d['date'], 'end': d['date']} for d in daily_days]
        raw_data = batch_build_store_data(stores, day_periods, regular_product_ids,
                                          overall_start, overall_end)
        for item in raw_data:
            item['days'] = item.pop('period_data')
        daily_data = raw_data
        if view_mode == 'franchise':
            daily_data = group_by_franchise(daily_data, 'days')

    elif search_type == 'weekly':
        weeks = build_periods('weekly', year, month, None, None, None)
        if weeks:
            overall_start = weeks[0]['start']
            overall_end = weeks[-1]['end']
            raw_data = batch_build_store_data(stores, weeks, regular_product_ids, overall_start, overall_end)
            for item in raw_data:
                item['weeks'] = item.pop('period_data')
            weekly_data = raw_data
            if view_mode == 'franchise':
                weekly_data = group_by_franchise(weekly_data, 'weeks')

    elif search_type == 'monthly':
        months_list = [{'num': m, 'name': f'{m}월'} for m in range(1, 13)]
        month_periods = build_periods('monthly', year, month, None, None, None)
        if month_periods:
            overall_start = month_periods[0]['start']
            overall_end = month_periods[-1]['end']
            raw_data = batch_build_store_data(stores, month_periods, regular_product_ids, overall_start, overall_end)
            for item in raw_data:
                item['months'] = item.pop('period_data')
            monthly_data = raw_data
            if view_mode == 'franchise':
                monthly_data = group_by_franchise(monthly_data, 'months')

    elif search_type == 'period':
        periods = build_periods('period', year, month, date_from_parsed, date_to_parsed, view_type)
        if periods:
            overall_start = periods[0]['start']
            overall_end = periods[-1]['end']
            raw_data = batch_build_store_data(stores, periods, regular_product_ids, overall_start, overall_end)
            for item in raw_data:
                item['periods'] = item.pop('period_data')
            period_data = raw_data
            if view_mode == 'franchise':
                period_data = group_by_franchise(period_data, 'periods')

    return render_template('admin/erp_tracking_admin.html',
                           search_type=search_type,
                           year=year,
                           month=month,
                           date_from=date_from,
                           date_to=date_to,
                           view_type=view_type,
                           selected_category=selected_category,
                           all_categories=all_categories,
                           view_mode=view_mode,
                           franchise_filter=franchise_filter,
                           store_filter=store_filter,
                           all_stores_for_filter=all_stores_for_filter,
                           stores_by_franchise_json=stores_by_franchise_json,
                           weekly_data=weekly_data,
                           weeks=weeks,
                           monthly_data=monthly_data,
                           months_list=months_list,
                           period_data=period_data,
                           periods=periods,
                           daily_data=daily_data,
                           daily_days=daily_days,
                           daily_weeks=daily_weeks,
                           daily_week_num=daily_week_num,
                           branches=branches,
                           jungsungs=jungsungs,
                           franchises=franchises)


# ============================================
# ERP 등록 (중상 전용)
# ============================================

@admin_bp.route('/erp-registration')
@login_required
@jungsung_required
def erp_registration():
    """ERP Registration page for jungsung users (중상 전용)"""
    # Get filter parameters
    selected_date = request.args.get('date')
    if selected_date:
        try:
            registration_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            registration_date = kst_today()
    else:
        registration_date = kst_today()

    # Get jungsung associated with this user
    jungsung = current_user.jungsung
    if not jungsung:
        flash('연결된 중상 정보가 없습니다. 관리자에게 문의하세요.', 'danger')
        return redirect(url_for('dashboard.jungsung'))

    # Get stores assigned to this jungsung, grouped by franchise
    stores = Store.query.filter_by(
        jungsung_id=jungsung.id,
        is_active=True
    ).order_by(Store.franchise_id, Store.name).all()

    # Group stores by franchise
    franchise_groups = {}
    for store in stores:
        if store.franchise_id not in franchise_groups:
            franchise_groups[store.franchise_id] = {
                'franchise': store.franchise,
                'stores': []
            }
        franchise_groups[store.franchise_id]['stores'].append(store)

    # Get existing registrations for this date and jungsung
    existing_regs = ERPRegistration.query.filter_by(
        registration_date=registration_date,
        jungsung_id=jungsung.id
    ).all()

    # Create a dict for quick lookup
    reg_by_store = {reg.store_id: reg for reg in existing_regs}

    # Get active categories
    categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()

    # Build franchise -> allowed category names mapping
    franchise_cat_names = {}
    for fid, group in franchise_groups.items():
        franchise = group['franchise']
        if franchise:
            franchise_cat_names[fid] = [cat.name for cat in franchise.categories]
        else:
            franchise_cat_names[fid] = []

    return render_template('admin/erp_registration.html',
                           registration_date=registration_date,
                           jungsung=jungsung,
                           franchise_groups=franchise_groups,
                           reg_by_store=reg_by_store,
                           categories=categories,
                           franchise_cat_names=franchise_cat_names)


@admin_bp.route('/erp-registration/complete', methods=['POST'])
@login_required
@jungsung_required
def erp_registration_complete():
    """Save/complete ERP registration for a store (can be called multiple times)"""
    jungsung = current_user.jungsung
    if not jungsung:
        return jsonify({'success': False, 'message': '연결된 중상 정보가 없습니다.'})

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '데이터가 없습니다.'})

    registration_date_str = data.get('date')
    store_id = data.get('store_id')
    category_quantities = data.get('category_quantities', {})

    try:
        registration_date = datetime.strptime(registration_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '잘못된 날짜 형식입니다.'})

    # Verify store belongs to this jungsung
    store = Store.query.filter_by(id=store_id, jungsung_id=jungsung.id).first()
    if not store:
        return jsonify({'success': False, 'message': '해당 매장에 대한 권한이 없습니다.'})

    # Get or create registration
    reg = ERPRegistration.query.filter_by(
        registration_date=registration_date,
        store_id=store_id,
        jungsung_id=jungsung.id,
        is_return=False
    ).first()

    if reg:
        reg.set_category_quantities(category_quantities)
        reg.is_completed = True
        reg.updated_at = datetime.utcnow()
    else:
        reg = ERPRegistration(
            registration_date=registration_date,
            store_id=store_id,
            jungsung_id=jungsung.id,
            is_return=False,
            is_completed=True,
            created_by=current_user.id
        )
        reg.set_category_quantities(category_quantities)
        db.session.add(reg)

    db.session.commit()
    return jsonify({'success': True, 'message': '저장되었습니다.'})


@admin_bp.route('/erp-registration/return', methods=['POST'])
@login_required
@jungsung_required
def erp_registration_return():
    """Add return entry (반품시 입력)"""
    jungsung = current_user.jungsung
    if not jungsung:
        return jsonify({'success': False, 'message': '연결된 중상 정보가 없습니다.'})

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '데이터가 없습니다.'})

    registration_date_str = data.get('date')
    store_id = data.get('store_id')
    category_quantities = data.get('category_quantities', {})

    try:
        registration_date = datetime.strptime(registration_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '잘못된 날짜 형식입니다.'})

    # Verify store belongs to this jungsung
    store = Store.query.filter_by(id=store_id, jungsung_id=jungsung.id).first()
    if not store:
        return jsonify({'success': False, 'message': '해당 매장에 대한 권한이 없습니다.'})

    # Check for existing return registration
    existing = ERPRegistration.query.filter_by(
        registration_date=registration_date,
        store_id=store_id,
        jungsung_id=jungsung.id,
        is_return=True
    ).first()

    if existing:
        existing.set_category_quantities(category_quantities)
        existing.updated_at = datetime.utcnow()
    else:
        new_reg = ERPRegistration(
            registration_date=registration_date,
            store_id=store_id,
            jungsung_id=jungsung.id,
            is_return=True,
            created_by=current_user.id
        )
        new_reg.set_category_quantities(category_quantities)
        db.session.add(new_reg)

    db.session.commit()
    return jsonify({'success': True, 'message': '반품이 등록되었습니다.'})


@admin_bp.route('/erp-tracking-jungsung')
@login_required
@jungsung_required
def erp_tracking_jungsung():
    """ERP Registration Tracking for Jungsung users - Shows shipments vs ERP registrations
    Supports: daily (날짜별), weekly (주별), monthly (월별), period (기간) search"""
    from calendar import monthrange

    # Get jungsung associated with this user
    jungsung = current_user.jungsung
    if not jungsung:
        flash('연결된 중상 정보가 없습니다. 관리자에게 문의하세요.', 'danger')
        return redirect(url_for('dashboard.jungsung'))

    search_type = request.args.get('search_type', 'daily')

    # Category filter
    selected_category = request.args.get('category', '전체')
    all_categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()

    # View mode: store or franchise
    view_mode = request.args.get('view_mode', 'store')

    # Franchise and store filters
    franchise_filter = request.args.get('franchise_id', type=int)
    store_filter = request.args.get('store_id', type=int)

    # Common: get stores and products
    stores_query = Store.query.filter_by(
        jungsung_id=jungsung.id,
        is_active=True
    )

    # All stores for filter dropdown (before applying filters)
    all_stores_for_filter = stores_query.order_by(Store.franchise_id, Store.name).all()

    # Derive franchises from assigned stores
    franchise_map_for_filter = {}
    for s in all_stores_for_filter:
        if s.franchise_id and s.franchise_id not in franchise_map_for_filter:
            franchise_map_for_filter[s.franchise_id] = s.franchise

    franchises = sorted(franchise_map_for_filter.values(), key=lambda f: f.name if f else '')

    # Build stores-by-franchise map for JS cascading
    import json
    stores_by_franchise_map = {}
    for s in all_stores_for_filter:
        fid = s.franchise_id or 0
        if fid not in stores_by_franchise_map:
            stores_by_franchise_map[fid] = []
        stores_by_franchise_map[fid].append({'id': s.id, 'name': s.name})
    stores_by_franchise_json = json.dumps(stores_by_franchise_map, ensure_ascii=False)

    # Apply franchise/store filters
    if franchise_filter:
        stores_query = stores_query.filter(Store.franchise_id == franchise_filter)
    if store_filter:
        stores_query = stores_query.filter(Store.id == store_filter)

    stores = stores_query.order_by(Store.franchise_id, Store.name).all()

    # Get products filtered by category (and by franchise_categories when franchise filter is applied)
    franchise_cat_names_j = None  # used by erp_category_sum
    product_query = Product.query.filter(Product.is_active == True)

    if franchise_filter:
        franchise_obj = Franchise.query.get(franchise_filter)
        franchise_cat_names_j = [c.name for c in franchise_obj.categories] if franchise_obj and franchise_obj.categories else []
        product_query = product_query.filter(Product.franchise_id == franchise_filter)
        if selected_category == '전체':
            if franchise_cat_names_j:
                product_query = product_query.filter(
                    Product.category.in_(franchise_cat_names_j),
                    ~Product.category.in_(get_waste_category_names())
                )
            else:
                product_query = product_query.filter(False)
        else:
            product_query = product_query.filter(Product.category == selected_category)
    else:
        if selected_category == '전체':
            product_query = product_query.filter(~Product.category.in_(get_waste_category_names()))
        else:
            product_query = product_query.filter(Product.category == selected_category)

    regular_products = product_query.all()
    regular_product_ids = [p.id for p in regular_products]
    store_ids = [s.id for s in stores]

    # Build franchise_id → [store_id] map for distributing jungsung-level shipments
    franchise_store_map = {}
    for s in stores:
        if s.franchise_id:
            franchise_store_map.setdefault(s.franchise_id, []).append(s.id)

    # Batch helper: fetch all shipment data grouped by store+date in one query
    def batch_shipments(start_date, end_date):
        # 1. Shipments with store_id (direct to store)
        store_rows = db.session.query(
            ShipmentItem.store_id,
            ShipmentItem.shipment_date,
            func.sum(ShipmentItem.quantity)
        ).filter(
            ShipmentItem.is_active == True,
            ShipmentItem.store_id.in_(store_ids),
            ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else False,
            ShipmentItem.shipment_date >= start_date,
            ShipmentItem.shipment_date <= end_date
        ).group_by(ShipmentItem.store_id, ShipmentItem.shipment_date).all()

        # 2. Shipments to jungsung (no store_id) - 지사 출고 to 중상
        jungsung_rows = db.session.query(
            Product.franchise_id,
            ShipmentItem.shipment_date,
            func.sum(ShipmentItem.quantity)
        ).join(Product).filter(
            ShipmentItem.is_active == True,
            ShipmentItem.jungsung_id == jungsung.id,
            ShipmentItem.store_id == None,
            ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else False,
            ShipmentItem.shipment_date >= start_date,
            ShipmentItem.shipment_date <= end_date
        ).group_by(Product.franchise_id, ShipmentItem.shipment_date).all()

        # Map jungsung-level shipments to stores via franchise
        result = list(store_rows)
        for franchise_id, s_date, qty in jungsung_rows:
            matching = franchise_store_map.get(franchise_id, [])
            if matching:
                per_store = qty // len(matching)
                remainder = qty % len(matching)
                for j, sid in enumerate(matching):
                    sq = per_store + (1 if j < remainder else 0)
                    if sq > 0:
                        result.append((sid, s_date, sq))
        return result

    # Batch helper: fetch all ERP data in one query
    def batch_erp(start_date, end_date):
        return ERPRegistration.query.filter(
            ERPRegistration.store_id.in_(store_ids),
            ERPRegistration.is_return == False,
            ERPRegistration.registration_date >= start_date,
            ERPRegistration.registration_date <= end_date
        ).all()

    # Helper: sum ERP quantities based on selected category
    def erp_category_sum(qty_dict):
        if not qty_dict:
            return 0
        if selected_category == '전체':
            if franchise_cat_names_j:
                valid_cats = set(franchise_cat_names_j) - set(get_waste_category_names())
                return sum(v for k, v in qty_dict.items() if k in valid_cats)
            return sum(v for k, v in qty_dict.items() if k not in get_waste_category_names())
        return qty_dict.get(selected_category, 0)

    # Helper: build lookup dicts from batch data for time periods
    def build_period_lookups(time_periods, shipment_rows, erp_rows):
        # shipment_lookup[(store_id, period_idx)] = qty
        shipment_lookup = {}
        for store_id, s_date, qty in shipment_rows:
            for i, p in enumerate(time_periods):
                if p['start'] <= s_date <= p['end']:
                    key = (store_id, i)
                    shipment_lookup[key] = shipment_lookup.get(key, 0) + qty
                    break

        # erp_lookup[(store_id, period_idx)] = qty, waste_lookup[(store_id, period_idx)] = qty
        erp_lookup = {}
        waste_lookup = {}
        for reg in erp_rows:
            for i, p in enumerate(time_periods):
                if p['start'] <= reg.registration_date <= p['end']:
                    qty_dict = reg.get_category_quantities()
                    erp_qty = erp_category_sum(qty_dict)
                    waste_qty = sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0
                    key = (reg.store_id, i)
                    if erp_qty:
                        erp_lookup[key] = erp_lookup.get(key, 0) + erp_qty
                    if waste_qty:
                        waste_lookup[key] = waste_lookup.get(key, 0) + waste_qty
                    break

        return shipment_lookup, erp_lookup, waste_lookup

    # Helper: build store data from lookups
    def build_store_data(time_periods, shipment_lookup, erp_lookup, waste_lookup, period_key):
        result = []
        for store in stores:
            store_data = {
                'store': store, 'franchise': store.franchise,
                period_key: [], 'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
            }
            for i in range(len(time_periods)):
                s_qty = shipment_lookup.get((store.id, i), 0)
                e_qty = erp_lookup.get((store.id, i), 0)
                w_qty = waste_lookup.get((store.id, i), 0)
                unreg = s_qty - e_qty
                store_data[period_key].append({'shipment': s_qty, 'erp': e_qty, 'waste': w_qty, 'unregistered': unreg})
                store_data['totals']['shipment'] += s_qty
                store_data['totals']['erp'] += e_qty
                store_data['totals']['waste'] += w_qty
                store_data['totals']['unregistered'] += unreg
            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                result.append(store_data)
        return result

    # Helper: group store-level data by franchise
    def group_by_franchise(data_list, period_key):
        franchise_map = {}
        for item in data_list:
            f = item.get('franchise')
            fid = f.id if f else 0
            if fid not in franchise_map:
                franchise_map[fid] = {
                    'store': type('obj', (object,), {'name': f.name if f else '미지정'})(),
                    'franchise': f,
                    period_key: None,
                    'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
                }
            entry = franchise_map[fid]
            if entry[period_key] is None:
                entry[period_key] = [{'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0} for _ in item[period_key]]
            for i, pd in enumerate(item[period_key]):
                entry[period_key][i]['shipment'] += pd.get('shipment', 0)
                entry[period_key][i]['erp'] += pd.get('erp', 0)
                entry[period_key][i]['waste'] += pd.get('waste', 0)
                entry[period_key][i]['unregistered'] += pd.get('unregistered', 0)
            for k in ('shipment', 'erp', 'waste', 'unregistered'):
                entry['totals'][k] += item['totals'].get(k, 0)
        return sorted(franchise_map.values(), key=lambda x: x['store'].name)

    # Helper: group stores by franchise
    def get_franchise_dict():
        fd = {}
        for store in stores:
            if store.franchise_id not in fd:
                fd[store.franchise_id] = {'franchise': store.franchise, 'stores': []}
            fd[store.franchise_id]['stores'].append(store)
        return fd

    # ========================================
    # 1. 날짜별 (Daily) - single date view (original)
    # ========================================
    filter_date = kst_today()
    franchise_groups = []
    total_shipment = 0
    total_erp_registered = 0
    total_waste = 0
    total_unregistered = 0

    if search_type == 'daily':
        selected_date = request.args.get('date')
        if selected_date:
            try:
                filter_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            except ValueError:
                filter_date = kst_today()

        # Batch: 2 queries total instead of 2 per store
        shipment_rows = batch_shipments(filter_date, filter_date)
        erp_rows = batch_erp(filter_date, filter_date)

        shipment_by_store = {}
        for store_id, _, qty in shipment_rows:
            shipment_by_store[store_id] = shipment_by_store.get(store_id, 0) + qty
        erp_by_store = {}
        waste_by_store = {}
        for reg in erp_rows:
            qty_dict = reg.get_category_quantities()
            erp_qty = erp_category_sum(qty_dict)
            waste_qty = sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0
            if erp_qty:
                erp_by_store[reg.store_id] = erp_by_store.get(reg.store_id, 0) + erp_qty
            if waste_qty:
                waste_by_store[reg.store_id] = waste_by_store.get(reg.store_id, 0) + waste_qty

        franchise_dict = get_franchise_dict()
        for fid, group in franchise_dict.items():
            group_data = {'franchise': group['franchise'], 'stores': []}
            for store in group['stores']:
                s_qty = shipment_by_store.get(store.id, 0)
                e_qty = erp_by_store.get(store.id, 0)
                w_qty = waste_by_store.get(store.id, 0)
                unreg = s_qty - e_qty
                group_data['stores'].append({
                    'store': store, 'shipment': s_qty,
                    'erp_registered': e_qty, 'waste': w_qty, 'unregistered': unreg
                })
                total_shipment += s_qty
                total_erp_registered += e_qty
                total_waste += w_qty
                total_unregistered += unreg
            franchise_groups.append(group_data)

        # Add per-group totals for franchise view_mode
        for group_data in franchise_groups:
            group_data['total_shipment'] = sum(s['shipment'] for s in group_data['stores'])
            group_data['total_erp'] = sum(s['erp_registered'] for s in group_data['stores'])
            group_data['total_waste'] = sum(s['waste'] for s in group_data['stores'])
            group_data['total_unregistered'] = sum(s['unregistered'] for s in group_data['stores'])

    # ========================================
    # 1.5. 일별 달력 (Daily Calendar) - Mon-Sun columns per week
    # ========================================
    daily_data = []
    daily_days = []
    daily_weeks = []
    daily_week_num = 1

    if search_type == 'calendar':
        year = request.args.get('year', type=int) or kst_today().year
        month = request.args.get('month', type=int) or kst_today().month

        # Build weeks for the month (Mon-Sun aligned)
        daily_weeks = build_month_weeks(year, month)

        daily_week_num = request.args.get('week', type=int) or 0  # 0 = 전체 (default)
        if daily_week_num > len(daily_weeks):
            daily_week_num = len(daily_weeks)

        weekday_names = ['월', '화', '수', '목', '금', '토', '일']

        if daily_week_num == 0:
            # 전체: show all days in the month
            first_day = date(year, month, 1)
            from calendar import monthrange as mr
            last_day = date(year, month, mr(year, month)[1])
            current_d = first_day
            while current_d <= last_day:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
            overall_start = first_day
            overall_end = last_day
        else:
            selected_week = daily_weeks[daily_week_num - 1]
            current_d = selected_week['start']
            while current_d <= selected_week['end']:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
            overall_start = selected_week['start']
            overall_end = selected_week['end']

        day_periods = [{'start': d['date'], 'end': d['date']} for d in daily_days]
        s_rows = batch_shipments(overall_start, overall_end)
        e_rows = batch_erp(overall_start, overall_end)
        s_lookup, e_lookup, w_lookup = build_period_lookups(day_periods, s_rows, e_rows)
        daily_data = build_store_data(day_periods, s_lookup, e_lookup, w_lookup, 'days')
        if view_mode == 'franchise':
            daily_data = group_by_franchise(daily_data, 'days')

    # ========================================
    # 2. 주별 (Weekly) - year/month, weekly breakdown
    # ========================================
    year = request.args.get('year', type=int) or kst_today().year
    month = request.args.get('month', type=int) or kst_today().month
    weekly_data = []
    weeks = []

    if search_type == 'weekly':
        weeks = build_month_weeks(year, month)

        overall_start = date(year, month, 1)
        _, last_day_num = monthrange(year, month)
        overall_end = date(year, month, last_day_num)
        s_rows = batch_shipments(overall_start, overall_end)
        e_rows = batch_erp(overall_start, overall_end)
        s_lookup, e_lookup, w_lookup = build_period_lookups(weeks, s_rows, e_rows)
        weekly_data = build_store_data(weeks, s_lookup, e_lookup, w_lookup, 'weeks')
        if view_mode == 'franchise':
            weekly_data = group_by_franchise(weekly_data, 'weeks')

    # ========================================
    # 3. 월별 (Monthly) - year, 12 months breakdown
    # ========================================
    monthly_data = []
    months_list = []

    if search_type == 'monthly':
        months_list = [{'num': m, 'name': f'{m}월'} for m in range(1, 13)]
        month_periods = []
        for m in range(1, 13):
            month_periods.append({
                'start': date(year, m, 1),
                'end': date(year, m, monthrange(year, m)[1])
            })

        s_rows = batch_shipments(date(year, 1, 1), date(year, 12, 31))
        e_rows = batch_erp(date(year, 1, 1), date(year, 12, 31))
        s_lookup, e_lookup, w_lookup = build_period_lookups(month_periods, s_rows, e_rows)
        monthly_data = build_store_data(month_periods, s_lookup, e_lookup, w_lookup, 'months')
        if view_mode == 'franchise':
            monthly_data = group_by_franchise(monthly_data, 'months')

    # ========================================
    # 4. 기간 (Period) - date range + view type
    # ========================================
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    view_type = request.args.get('view_type', 'weekly')
    period_data = []
    periods = []

    if search_type == 'period':
        if not date_from or not date_to:
            first_day = date(year, month, 1)
            last_day = date(year, month, monthrange(year, month)[1])
            date_from = first_day.strftime('%Y-%m-%d')
            date_to = last_day.strftime('%Y-%m-%d')

        date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
        date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

        # Generate periods based on view_type
        if view_type == 'daily':
            current = date_from_parsed
            pn = 1
            while current <= date_to_parsed:
                periods.append({'num': pn, 'start': current, 'end': current, 'label': current.strftime('%m/%d')})
                current += timedelta(days=1)
                pn += 1
        elif view_type == 'weekly':
            current = date_from_parsed
            pn = 1
            while current <= date_to_parsed:
                week_end = min(current + timedelta(days=6), date_to_parsed)
                periods.append({'num': pn, 'start': current, 'end': week_end,
                                'label': f'{current.strftime("%m/%d")}~{week_end.strftime("%m/%d")}'})
                current = week_end + timedelta(days=1)
                pn += 1
        elif view_type == 'monthly':
            cy, cm = date_from_parsed.year, date_from_parsed.month
            pn = 1
            while True:
                fd = date(cy, cm, 1)
                ld = date(cy, cm, monthrange(cy, cm)[1])
                ps = max(fd, date_from_parsed)
                pe = min(ld, date_to_parsed)
                if ps > date_to_parsed:
                    break
                periods.append({'num': pn, 'start': ps, 'end': pe, 'label': f'{cy}년 {cm}월'})
                cm += 1
                if cm > 12:
                    cm = 1
                    cy += 1
                pn += 1
                if pe >= date_to_parsed:
                    break
        elif view_type == 'yearly':
            for y in range(date_from_parsed.year, date_to_parsed.year + 1):
                ps = max(date(y, 1, 1), date_from_parsed)
                pe = min(date(y, 12, 31), date_to_parsed)
                periods.append({'num': y - date_from_parsed.year + 1, 'start': ps, 'end': pe, 'label': f'{y}년'})

        s_rows = batch_shipments(date_from_parsed, date_to_parsed)
        e_rows = batch_erp(date_from_parsed, date_to_parsed)
        s_lookup, e_lookup, w_lookup = build_period_lookups(periods, s_rows, e_rows)
        period_data = build_store_data(periods, s_lookup, e_lookup, w_lookup, 'periods')
        if view_mode == 'franchise':
            period_data = group_by_franchise(period_data, 'periods')

    return render_template('admin/erp_tracking_jungsung.html',
                           search_type=search_type,
                           jungsung=jungsung,
                           selected_category=selected_category,
                           all_categories=all_categories,
                           view_mode=view_mode,
                           franchise_filter=franchise_filter,
                           store_filter=store_filter,
                           franchises=franchises,
                           all_stores_for_filter=all_stores_for_filter,
                           stores_by_franchise_json=stores_by_franchise_json,
                           # daily
                           filter_date=filter_date,
                           franchise_groups=franchise_groups,
                           total_shipment=total_shipment,
                           total_erp_registered=total_erp_registered,
                           total_waste=total_waste,
                           total_unregistered=total_unregistered,
                           # calendar
                           daily_data=daily_data,
                           daily_days=daily_days,
                           daily_weeks=daily_weeks,
                           daily_week_num=daily_week_num,
                           # weekly
                           year=year, month=month,
                           weekly_data=weekly_data, weeks=weeks,
                           # monthly
                           monthly_data=monthly_data, months_list=months_list,
                           # period
                           date_from=date_from, date_to=date_to,
                           view_type=view_type,
                           period_data=period_data, periods=periods)


@admin_bp.route('/erp-tracking-franchise')
@login_required
@franchise_required
def erp_tracking_franchise():
    """ERP Registration Quantity Check for Franchise users
    Three search types: Weekly, Monthly, and Period Search (matching admin version)"""
    from calendar import monthrange

    # Get search type (주별/월별/기간)
    search_type = request.args.get('search_type', 'weekly')

    # Category filter
    selected_category = request.args.get('category', '전체')
    all_categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()

    # Get filter parameters
    year = request.args.get('year', type=int) or kst_today().year
    month = request.args.get('month', type=int) or kst_today().month

    # Period search parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    view_type = request.args.get('view_type', 'weekly')  # 일별/주별/월별/년별

    # Set default date range if not specified
    if not date_from or not date_to:
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        date_from = first_day.strftime('%Y-%m-%d')
        date_to = last_day.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get franchise associated with this user
    franchise = current_user.franchise
    if not franchise:
        flash('연결된 프랜차이즈 정보가 없습니다. 관리자에게 문의하세요.', 'danger')
        return redirect(url_for('dashboard.franchise'))

    # Get franchise's valid categories from franchise_categories table
    franchise_cat_names = [c.name for c in franchise.categories] if franchise.categories else []

    # Filter all_categories to only show this franchise's categories
    all_categories = [c for c in all_categories if c.name in franchise_cat_names]

    # Get active products filtered by category AND franchise
    if selected_category == '전체':
        if franchise_cat_names:
            regular_products = Product.query.filter(
                Product.is_active == True,
                Product.franchise_id == franchise.id,
                Product.category.in_(franchise_cat_names),
                ~Product.category.in_(get_waste_category_names())
            ).all()
        else:
            regular_products = []
    else:
        regular_products = Product.query.filter(
            Product.is_active == True,
            Product.franchise_id == franchise.id,
            Product.category == selected_category
        ).all()
    regular_product_ids = [p.id for p in regular_products]

    # Helper: sum ERP quantities based on selected category
    def erp_category_sum(qty_dict):
        if not qty_dict:
            return 0
        if selected_category == '전체':
            valid_cats = set(franchise_cat_names) - set(get_waste_category_names())
            return sum(v for k, v in qty_dict.items() if k in valid_cats)
        return qty_dict.get(selected_category, 0)

    # Store filter
    store_filter = request.args.get('store_id', type=int)

    # Get stores belonging to this franchise
    stores_query = Store.query.filter_by(
        franchise_id=franchise.id,
        is_active=True
    )
    # All stores for dropdown (before filtering)
    all_stores_for_filter = stores_query.order_by(Store.name).all()

    if store_filter:
        stores_query = stores_query.filter(Store.id == store_filter)
    stores = stores_query.order_by(Store.name).all()

    # Pre-compute jungsung-level shipments for this franchise's stores
    # These are ShipmentItems with jungsung_id but no store_id
    store_ids_franchise = [s.id for s in stores]
    jungsung_ids_franchise = list(set(s.jungsung_id for s in stores if s.jungsung_id))

    # Build jungsung+franchise → [store_ids] map for distribution
    jf_map_franchise = {}
    for s in stores:
        if s.jungsung_id:
            jf_map_franchise.setdefault(s.jungsung_id, []).append(s.id)

    def get_jungsung_shipment_extra(store, period_start, period_end):
        """Get this store's share of jungsung-level shipments for the period."""
        if not store.jungsung_id or not jungsung_ids_franchise:
            return 0
        siblings = jf_map_franchise.get(store.jungsung_id, [])
        if not siblings:
            return 0
        total = db.session.query(func.sum(ShipmentItem.quantity)).join(Product).filter(
            ShipmentItem.is_active == True,
            ShipmentItem.jungsung_id == store.jungsung_id,
            ShipmentItem.store_id == None,
            Product.franchise_id == franchise.id,
            ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else False,
            ShipmentItem.shipment_date >= period_start,
            ShipmentItem.shipment_date <= period_end
        ).scalar() or 0
        if total == 0:
            return 0
        per_store = total // len(siblings)
        idx = siblings.index(store.id) if store.id in siblings else -1
        remainder = total % len(siblings)
        return per_store + (1 if 0 <= idx < remainder else 0)

    # ========================================
    # 0. 일별 달력 (Daily Calendar) - Mon-Sun columns per week
    # ========================================
    daily_data = []
    daily_days = []
    daily_weeks = []
    daily_week_num = 1

    if search_type == 'calendar':
        # Build weeks for the month (Mon-Sun aligned)
        daily_weeks = build_month_weeks(year, month)

        daily_week_num = request.args.get('week', type=int) or 0  # 0 = 전체 (default)
        if daily_week_num > len(daily_weeks):
            daily_week_num = len(daily_weeks)

        weekday_names = ['월', '화', '수', '목', '금', '토', '일']

        if daily_week_num == 0:
            # 전체: show all days in the month
            first_day = date(year, month, 1)
            from calendar import monthrange as mr
            last_day = date(year, month, mr(year, month)[1])
            current_d = first_day
            while current_d <= last_day:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
        else:
            selected_week = daily_weeks[daily_week_num - 1]
            current_d = selected_week['start']
            while current_d <= selected_week['end']:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)

        # Build daily data for each store
        for store in stores:
            store_data = {
                'store': store,
                'days': [],
                'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
            }

            for day_info in daily_days:
                d = day_info['date']
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else False,
                    ShipmentItem.shipment_date == d
                ).scalar() or 0
                shipment_qty += get_jungsung_shipment_extra(store, d, d)

                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date == d
                ).all()

                erp_qty = 0
                waste_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += erp_category_sum(qty_dict)
                    waste_qty += sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty

                store_data['days'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'waste': waste_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['waste'] += waste_qty
                store_data['totals']['unregistered'] += unregistered

            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                daily_data.append(store_data)

    # ========================================
    # 1. 주별 검색 (Weekly Search) - Select year/month, see weekly breakdown
    # ========================================
    weekly_data = []
    weeks = []
    if search_type == 'weekly':
        # Calculate weeks in the selected month (Mon-Sun aligned)
        weeks = build_month_weeks(year, month)

        # Build weekly data for each store
        for store in stores:
            store_data = {
                'store': store,
                'weeks': [],
                'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
            }

            for week in weeks:
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= week['start'],
                    ShipmentItem.shipment_date <= week['end']
                ).scalar() or 0
                shipment_qty += get_jungsung_shipment_extra(store, week['start'], week['end'])

                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= week['start'],
                    ERPRegistration.registration_date <= week['end']
                ).all()

                erp_qty = 0
                waste_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += erp_category_sum(qty_dict)
                    waste_qty += sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty

                store_data['weeks'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'waste': waste_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['waste'] += waste_qty
                store_data['totals']['unregistered'] += unregistered

            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                weekly_data.append(store_data)

    # ========================================
    # 2. 월별 검색 (Monthly Search) - Select year, see all 12 months
    # ========================================
    monthly_data = []
    months_list = []
    if search_type == 'monthly':
        months_list = [{'num': m, 'name': f'{m}월'} for m in range(1, 13)]

        # Build monthly data for each store
        for store in stores:
            store_data = {
                'store': store,
                'months': [],
                'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
            }

            for m in range(1, 13):
                first_day = date(year, m, 1)
                last_day = date(year, m, monthrange(year, m)[1])

                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= first_day,
                    ShipmentItem.shipment_date <= last_day
                ).scalar() or 0
                shipment_qty += get_jungsung_shipment_extra(store, first_day, last_day)

                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= first_day,
                    ERPRegistration.registration_date <= last_day
                ).all()

                erp_qty = 0
                waste_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += erp_category_sum(qty_dict)
                    waste_qty += sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty

                store_data['months'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'waste': waste_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['waste'] += waste_qty
                store_data['totals']['unregistered'] += unregistered

            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                monthly_data.append(store_data)

    # ========================================
    # 3. 기간 검색 (Period Search) - Select date range + view type
    # ========================================
    period_data = []
    periods = []
    if search_type == 'period':
        if view_type == 'daily':
            # Generate daily periods
            current = date_from_parsed
            period_num = 1
            while current <= date_to_parsed:
                periods.append({
                    'num': period_num,
                    'start': current,
                    'end': current,
                    'label': current.strftime('%m/%d')
                })
                current += timedelta(days=1)
                period_num += 1

        elif view_type == 'weekly':
            # Generate weekly periods
            current = date_from_parsed
            period_num = 1
            while current <= date_to_parsed:
                week_end = min(current + timedelta(days=6), date_to_parsed)
                periods.append({
                    'num': period_num,
                    'start': current,
                    'end': week_end,
                    'label': f'{current.strftime("%m/%d")}~{week_end.strftime("%m/%d")}'
                })
                current = week_end + timedelta(days=1)
                period_num += 1

        elif view_type == 'monthly':
            # Generate monthly periods
            current_year = date_from_parsed.year
            current_month = date_from_parsed.month
            period_num = 1

            while True:
                first_day = date(current_year, current_month, 1)
                last_day = date(current_year, current_month, monthrange(current_year, current_month)[1])

                period_start = max(first_day, date_from_parsed)
                period_end = min(last_day, date_to_parsed)

                if period_start > date_to_parsed:
                    break

                periods.append({
                    'num': period_num,
                    'start': period_start,
                    'end': period_end,
                    'label': f'{current_year}년 {current_month}월'
                })

                current_month += 1
                if current_month > 12:
                    current_month = 1
                    current_year += 1
                period_num += 1

                if period_end >= date_to_parsed:
                    break

        elif view_type == 'yearly':
            # Generate yearly periods
            start_year = date_from_parsed.year
            end_year = date_to_parsed.year
            period_num = 1

            for y in range(start_year, end_year + 1):
                year_start = date(y, 1, 1)
                year_end = date(y, 12, 31)

                period_start = max(year_start, date_from_parsed)
                period_end = min(year_end, date_to_parsed)

                periods.append({
                    'num': period_num,
                    'start': period_start,
                    'end': period_end,
                    'label': f'{y}년'
                })
                period_num += 1

        # Build period data for each store
        for store in stores:
            store_data = {
                'store': store,
                'periods': [],
                'totals': {'shipment': 0, 'erp': 0, 'waste': 0, 'unregistered': 0}
            }

            for period in periods:
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= period['start'],
                    ShipmentItem.shipment_date <= period['end']
                ).scalar() or 0
                shipment_qty += get_jungsung_shipment_extra(store, period['start'], period['end'])

                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= period['start'],
                    ERPRegistration.registration_date <= period['end']
                ).all()

                erp_qty = 0
                waste_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += erp_category_sum(qty_dict)
                    waste_qty += sum(qty_dict.get(wc, 0) for wc in get_waste_category_names()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty

                store_data['periods'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'waste': waste_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['waste'] += waste_qty
                store_data['totals']['unregistered'] += unregistered

            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                period_data.append(store_data)

    return render_template('admin/erp_tracking_franchise.html',
                           search_type=search_type,
                           selected_category=selected_category,
                           all_categories=all_categories,
                           year=year,
                           month=month,
                           date_from=date_from,
                           date_to=date_to,
                           view_type=view_type,
                           daily_data=daily_data,
                           daily_days=daily_days,
                           daily_weeks=daily_weeks,
                           daily_week_num=daily_week_num,
                           weekly_data=weekly_data,
                           weeks=weeks,
                           monthly_data=monthly_data,
                           months_list=months_list,
                           period_data=period_data,
                           periods=periods,
                           franchise=franchise,
                           store_filter=store_filter,
                           all_stores_for_filter=all_stores_for_filter)


# ============================================
# 월마감자료 (Monthly Closing Data - Franchise)
# ============================================

@admin_bp.route('/monthly-closing-franchise')
@login_required
@franchise_required
def monthly_closing_franchise():
    """Monthly closing data for franchise users.
    Shows per-store 입고 (ERP registered, excl. 폐유) and 폐유 values.
    Three search types: calendar (일별), monthly (주별 within month), period (기간검색)."""
    from calendar import monthrange

    search_type = request.args.get('search_type', 'monthly')
    year = request.args.get('year', type=int) or kst_today().year
    month = request.args.get('month', type=int) or kst_today().month

    # Period search parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    view_type = request.args.get('view_type', 'weekly')

    # Set default date range if not specified
    if not date_from or not date_to:
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        date_from = first_day.strftime('%Y-%m-%d')
        date_to = last_day.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get franchise
    franchise = current_user.franchise
    if not franchise:
        flash('연결된 프랜차이즈 정보가 없습니다. 관리자에게 문의하세요.', 'danger')
        return redirect(url_for('dashboard.franchise'))

    stores = Store.query.filter_by(
        franchise_id=franchise.id,
        is_active=True
    ).order_by(Store.name).all()

    # Helper: extract 입고 and 폐유 from ERP registrations
    def get_stockin_waste(store_id, start_date, end_date):
        regs = ERPRegistration.query.filter(
            ERPRegistration.store_id == store_id,
            ERPRegistration.is_return == False,
            ERPRegistration.registration_date >= start_date,
            ERPRegistration.registration_date <= end_date
        ).all()
        stockin = 0
        waste = 0
        for reg in regs:
            qty_dict = reg.get_category_quantities()
            if qty_dict:
                stockin += sum(v for k, v in qty_dict.items() if k not in get_waste_category_names())
                waste += sum(qty_dict.get(wc, 0) for wc in get_waste_category_names())
        return stockin, waste

    # Helper: build store data for a list of periods
    def build_closing_data(periods_list, period_key):
        result = []
        for store in stores:
            store_data = {
                'store': store,
                period_key: [],
                'totals': {'stockin': 0, 'waste': 0}
            }
            for period in periods_list:
                si, wa = get_stockin_waste(store.id, period['start'], period['end'])
                store_data[period_key].append({'stockin': si, 'waste': wa})
                store_data['totals']['stockin'] += si
                store_data['totals']['waste'] += wa
            result.append(store_data)
        return result

    # ========================================
    # 0. 일별 달력 (Daily Calendar)
    # ========================================
    daily_data = []
    daily_days = []
    daily_weeks_list = []
    daily_week_num = 1

    if search_type == 'calendar':
        daily_weeks_list = build_month_weeks(year, month)

        daily_week_num = request.args.get('week', type=int) or 0  # 0 = 전체 (default)
        if daily_week_num > len(daily_weeks_list):
            daily_week_num = len(daily_weeks_list)

        weekday_names = ['월', '화', '수', '목', '금', '토', '일']

        if daily_week_num == 0:
            # 전체: show all days in the month
            first_day = date(year, month, 1)
            from calendar import monthrange as mr
            last_day = date(year, month, mr(year, month)[1])
            current_d = first_day
            while current_d <= last_day:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)
        else:
            selected_week = daily_weeks_list[daily_week_num - 1]
            current_d = selected_week['start']
            while current_d <= selected_week['end']:
                daily_days.append({
                    'date': current_d,
                    'weekday': weekday_names[current_d.weekday()],
                    'label': current_d.strftime('%m/%d')
                })
                current_d += timedelta(days=1)

        day_periods = [{'start': dd['date'], 'end': dd['date']} for dd in daily_days]
        daily_data = build_closing_data(day_periods, 'days')

    # ========================================
    # 1. 월별 (주별 within month)
    # ========================================
    weekly_data = []
    weeks = []

    if search_type == 'monthly':
        weeks = build_month_weeks(year, month)

        weekly_data = build_closing_data(weeks, 'weeks')

    # ========================================
    # 2. 기간검색 (Period Search)
    # ========================================
    period_data = []
    periods = []

    if search_type == 'period':
        if view_type == 'daily':
            current = date_from_parsed
            pn = 1
            while current <= date_to_parsed:
                periods.append({'num': pn, 'start': current, 'end': current, 'label': current.strftime('%m/%d')})
                current += timedelta(days=1)
                pn += 1
        elif view_type == 'weekly':
            current = date_from_parsed
            pn = 1
            while current <= date_to_parsed:
                week_end = min(current + timedelta(days=6), date_to_parsed)
                periods.append({'num': pn, 'start': current, 'end': week_end,
                                'label': f'{current.strftime("%m/%d")}~{week_end.strftime("%m/%d")}'})
                current = week_end + timedelta(days=1)
                pn += 1
        elif view_type == 'monthly':
            cy, cm = date_from_parsed.year, date_from_parsed.month
            pn = 1
            while True:
                fd = date(cy, cm, 1)
                ld = date(cy, cm, monthrange(cy, cm)[1])
                ps = max(fd, date_from_parsed)
                pe = min(ld, date_to_parsed)
                if ps > date_to_parsed:
                    break
                periods.append({'num': pn, 'start': ps, 'end': pe, 'label': f'{cy}년 {cm}월'})
                cm += 1
                if cm > 12:
                    cm = 1
                    cy += 1
                pn += 1
                if pe >= date_to_parsed:
                    break
        elif view_type == 'yearly':
            pn = 1
            for y in range(date_from_parsed.year, date_to_parsed.year + 1):
                ps = max(date(y, 1, 1), date_from_parsed)
                pe = min(date(y, 12, 31), date_to_parsed)
                periods.append({'num': pn, 'start': ps, 'end': pe, 'label': f'{y}년'})
                pn += 1

        period_data = build_closing_data(periods, 'periods')

    return render_template('admin/monthly_closing_franchise.html',
                           search_type=search_type,
                           year=year,
                           month=month,
                           date_from=date_from,
                           date_to=date_to,
                           view_type=view_type,
                           franchise=franchise,
                           daily_data=daily_data,
                           daily_days=daily_days,
                           daily_weeks=daily_weeks_list,
                           daily_week_num=daily_week_num,
                           weekly_data=weekly_data,
                           weeks=weeks,
                           period_data=period_data,
                           periods=periods)


# ============================================
# Store Status Management (중상 전용)
# ============================================

def calculate_store_status(store_id):
    """
    Calculate automatic status flags for a store based on data.
    - no_shipment_2months: No shipments in the last 2 months
    - unused_store: No ERP registrations (입고) in the last 2 months
    - uncollected_waste_oil: No waste oil (폐유) registered in the last 2 months
    """
    from datetime import date
    two_months_ago = kst_today() - timedelta(days=60)

    store = Store.query.get(store_id)
    if not store:
        return

    # Check no_shipment_2months - no shipments to this store in last 2 months
    recent_shipment = ShipmentItem.query.filter(
        ShipmentItem.store_id == store_id,
        ShipmentItem.is_active == True,
        ShipmentItem.shipment_date >= two_months_ago
    ).first()
    store.no_shipment_2months = (recent_shipment is None)

    # Check unused_store - no ERP registration (입고) in last 2 months
    recent_regs = ERPRegistration.query.filter(
        ERPRegistration.store_id == store_id,
        ERPRegistration.is_return == False,
        ERPRegistration.registration_date >= two_months_ago
    ).all()
    has_stockin = any(
        sum(v for k, v in reg.get_category_quantities().items() if k not in get_waste_category_names()) > 0
        for reg in recent_regs
    )
    store.unused_store = not has_stockin

    # Check uncollected_waste_oil - no waste oil (폐유) registered in last 2 months
    has_waste = any(
        sum(reg.get_category_quantities().get(wc, 0) for wc in get_waste_category_names()) > 0
        for reg in recent_regs
    )
    store.uncollected_waste_oil = not has_waste

    db.session.commit()
    return store


@admin_bp.route('/store-status/update', methods=['POST'])
@login_required
@jungsung_required
def update_store_status():
    """Update manual store status flags (폐업매장, 악성미수매장) - 중상 only"""
    jungsung = current_user.jungsung
    if not jungsung:
        return jsonify({'success': False, 'message': '연결된 중상 정보가 없습니다.'})

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '데이터가 없습니다.'})

    store_id = data.get('store_id')
    field = data.get('field')
    value = data.get('value', False)

    # Validate field - only allow manual flags
    if field not in ['closed_store', 'bad_debt_store', 'external_purchase_store']:
        return jsonify({'success': False, 'message': '잘못된 필드입니다.'})

    # Verify store belongs to this jungsung
    store = Store.query.filter_by(id=store_id, jungsung_id=jungsung.id).first()
    if not store:
        return jsonify({'success': False, 'message': '해당 매장에 대한 권한이 없습니다.'})

    # Update the field
    setattr(store, field, value)
    store.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True, 'message': '상태가 업데이트되었습니다.'})


@admin_bp.route('/store-status/refresh/<int:store_id>', methods=['POST'])
@login_required
@jungsung_required
def refresh_store_status(store_id):
    """Refresh automatic store status flags"""
    jungsung = current_user.jungsung
    if not jungsung:
        return jsonify({'success': False, 'message': '연결된 중상 정보가 없습니다.'})

    # Verify store belongs to this jungsung
    store = Store.query.filter_by(id=store_id, jungsung_id=jungsung.id).first()
    if not store:
        return jsonify({'success': False, 'message': '해당 매장에 대한 권한이 없습니다.'})

    # Recalculate automatic flags
    calculate_store_status(store_id)

    return jsonify({
        'success': True,
        'message': '상태가 갱신되었습니다.',
        'status': {
            'no_shipment_2months': store.no_shipment_2months,
            'unused_store': store.unused_store,
            'uncollected_waste_oil': store.uncollected_waste_oil
        }
    })


@admin_bp.route('/store-status/list')
@login_required
@jungsung_required
def store_status_list():
    """Store status management page for jungsung users"""
    jungsung = current_user.jungsung
    if not jungsung:
        flash('연결된 중상 정보가 없습니다. 관리자에게 문의하세요.', 'danger')
        return redirect(url_for('dashboard.jungsung'))

    # Get stores assigned to this jungsung
    stores = Store.query.filter_by(
        jungsung_id=jungsung.id,
        is_active=True
    ).order_by(Store.franchise_id, Store.name).all()

    # Recalculate automatic flags for all stores
    for store in stores:
        calculate_store_status(store.id)

    # Group by franchise
    franchise_groups = {}
    for store in stores:
        if store.franchise_id not in franchise_groups:
            franchise_groups[store.franchise_id] = {
                'franchise': store.franchise,
                'stores': []
            }
        franchise_groups[store.franchise_id]['stores'].append(store)

    return render_template('admin/store_status_list.html',
                           jungsung=jungsung,
                           franchise_groups=franchise_groups)


# ============================================
# 미수금 관리 (Receivables Management)
# ============================================

@admin_bp.route('/receivables')
@login_required
@admin_required
def receivables_list():
    """미수금 관리 페이지 - 악성미수매장 및 미수금 현황"""
    # Get filter parameters
    franchise_id = request.args.get('franchise_id', type=int)
    branch_id = request.args.get('branch_id', type=int)

    # Query stores with bad_debt_store flag
    query = Store.query.filter_by(is_active=True, bad_debt_store=True)

    if franchise_id:
        query = query.filter_by(franchise_id=franchise_id)
    if branch_id:
        query = query.filter_by(branch_id=branch_id)

    bad_debt_stores = query.order_by(Store.franchise_id, Store.name).all()

    # Get filter options
    franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    return render_template('admin/receivables_list.html',
                           bad_debt_stores=bad_debt_stores,
                           franchises=franchises,
                           branches=branches,
                           selected_franchise_id=franchise_id,
                           selected_branch_id=branch_id)


# ============================================
# 컴플레인 매장관리 (Franchise Store Complaint Management)
# ============================================

@admin_bp.route('/complaint-stores')
@login_required
@franchise_required
def complaint_stores():
    """Complaint store management page for franchise users - view stores with red status flags"""
    franchise = current_user.franchise
    if not franchise:
        flash('연결된 프랜차이즈 정보가 없습니다. 관리자에게 문의하세요.', 'danger')
        return redirect(url_for('dashboard.franchise'))

    # Get all stores belonging to this franchise
    stores = Store.query.filter_by(
        franchise_id=franchise.id,
        is_active=True
    ).order_by(Store.name).all()

    # Recalculate automatic flags for all stores
    for store in stores:
        calculate_store_status(store.id)

    return render_template('admin/complaint_stores.html',
                           franchise=franchise,
                           stores=stores)
