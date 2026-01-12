from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user import User, Branch, Franchise, Store, Jungsung, Supplier, Product, Shipment, ShipmentItem, StockIn, ERPRegistration, Payment, UserRole, Category
from app.utils.decorators import admin_required, branch_required, jungsung_required, franchise_required
from datetime import datetime, date, timedelta
from sqlalchemy import func, extract, or_, and_

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


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
def franchises_list():
    """Franchise list - accessible by admin and branch users"""
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

    return render_template('admin/franchises_list.html', franchises=franchises, sort=sort, order=order)


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
            code=code,
            address=address,
            phone=phone,
            contact_person=contact_person
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
        code=code,
        address=address,
        phone=phone,
        contact_person=contact_person
    )
    db.session.add(franchise)
    db.session.flush()

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
def products_list():
    """Products list - accessible by admin and branch users"""
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
        franchise_ids = [f[0] for f in franchise_ids]
        query = query.filter(Product.franchise_id.in_(franchise_ids))
        franchises = Franchise.query.filter(Franchise.id.in_(franchise_ids)).order_by(Franchise.name).all()
    else:
        franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()

    products = query.order_by(order_col).all()
    return render_template('admin/products_list.html', products=products, franchises=franchises, sort=sort, order=order)


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
    db.session.delete(product)
    db.session.commit()
    flash('제품이 삭제되었습니다.', 'success')
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
    product_id = request.args.get('product_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    jungsung_id = request.args.get('jungsung_id', type=int)
    store_id = request.args.get('store_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Parse date filters once
    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None

    # Base query for shipment items (use ShipmentItem.shipment_date for per-item dates)
    query = ShipmentItem.query.filter(ShipmentItem.is_active == True)

    # Branch users only see their branch's data
    if not current_user.is_admin():
        query = query.filter(ShipmentItem.branch_id == current_user.branch_id)

    # Apply filters
    if category:
        query = query.join(Product).filter(Product.category == category)
    if product_id:
        query = query.filter(ShipmentItem.product_id == product_id)
    if branch_id and current_user.is_admin():  # Only admin can filter by branch
        query = query.filter(ShipmentItem.branch_id == branch_id)
    if jungsung_id:
        query = query.filter(ShipmentItem.jungsung_id == jungsung_id)
    if store_id:
        query = query.filter(ShipmentItem.store_id == store_id)
    if date_from_parsed:
        query = query.filter(ShipmentItem.shipment_date >= date_from_parsed)
    if date_to_parsed:
        query = query.filter(ShipmentItem.shipment_date <= date_to_parsed)

    # Get shipment items ordered by per-item date
    items = query.order_by(ShipmentItem.shipment_date.desc(), ShipmentItem.id.desc()).all()

    # Calculate summary stats by product with applied filters
    today = date.today()
    first_of_month = today.replace(day=1)
    first_of_prev_month = (first_of_month - timedelta(days=1)).replace(day=1)

    # Get products for summary (filtered by category if specified)
    products_query = Product.query.filter_by(is_active=True)
    if category:
        products_query = products_query.filter(Product.category == category)
    if product_id:
        products_query = products_query.filter(Product.id == product_id)
    products_for_stats = products_query.all()

    product_stats = []

    for product in products_for_stats:
        # Base filter with all applicable filters
        base_filter = [
            ShipmentItem.product_id == product.id,
            ShipmentItem.is_active == True
        ]
        if not current_user.is_admin():
            base_filter.append(ShipmentItem.branch_id == current_user.branch_id)
        if branch_id and current_user.is_admin():
            base_filter.append(ShipmentItem.branch_id == branch_id)
        if jungsung_id:
            base_filter.append(ShipmentItem.jungsung_id == jungsung_id)
        if store_id:
            base_filter.append(ShipmentItem.store_id == store_id)

        # Apply date filters for stats calculation
        # If date filter is set, use those dates; otherwise use default periods
        if date_from_parsed or date_to_parsed:
            # When date filter is applied, show filtered total in 'this_month' column
            filtered_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(*base_filter)
            if date_from_parsed:
                filtered_qty = filtered_qty.filter(ShipmentItem.shipment_date >= date_from_parsed)
            if date_to_parsed:
                filtered_qty = filtered_qty.filter(ShipmentItem.shipment_date <= date_to_parsed)
            filtered_qty = filtered_qty.scalar() or 0

            product_stats.append({
                'product': product,
                'today': 0,
                'this_month': filtered_qty,
                'prev_month': 0
            })
        else:
            # Today's quantity
            today_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                *base_filter,
                ShipmentItem.shipment_date == today
            ).scalar() or 0

            # This month's quantity
            month_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                *base_filter,
                ShipmentItem.shipment_date >= first_of_month,
                ShipmentItem.shipment_date <= today
            ).scalar() or 0

            # Previous month's quantity
            prev_month_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                *base_filter,
                ShipmentItem.shipment_date >= first_of_prev_month,
                ShipmentItem.shipment_date < first_of_month
            ).scalar() or 0

            product_stats.append({
                'product': product,
                'today': today_qty,
                'this_month': month_qty,
                'prev_month': prev_month_qty
            })

    # Get data for filters
    categories = db.session.query(Product.category).filter(Product.is_active == True).distinct().all()
    categories = [c[0] for c in categories]

    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()
        stores = Store.query.filter_by(is_active=True).order_by(Store.name).all()
        all_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()
        stores = Store.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Store.name).all()

        # Get products from franchises that have stores in this branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids]
        all_products = Product.query.filter(
            Product.is_active == True,
            Product.franchise_id.in_(franchise_ids)
        ).order_by(Product.name).all()

    return render_template('admin/shipments_list.html',
                           items=items,
                           product_stats=product_stats,
                           products=all_products,
                           categories=categories,
                           branches=branches,
                           jungsungs=jungsungs,
                           stores=stores,
                           filters={
                               'category': category,
                               'product_id': product_id,
                               'branch_id': branch_id,
                               'jungsung_id': jungsung_id,
                               'store_id': store_id,
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
        franchise_ids = [f[0] for f in franchise_ids]
        products = Product.query.filter(
            Product.is_active == True,
            Product.franchise_id.in_(franchise_ids)
        ).order_by(Product.category, Product.name).all()

    return render_template('admin/shipments_create.html',
                           branches=branches,
                           jungsungs=jungsungs,
                           stores=stores,
                           products=products,
                           categories=categories,
                           today=date.today().strftime('%Y-%m-%d'))


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
    store_ids = request.form.getlist('store_id[]')
    product_ids = request.form.getlist('product_id[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')

    if not product_ids or len(product_ids) == 0:
        flash('출고 항목을 추가해주세요.', 'danger')
        return redirect(url_for('admin.shipments_create'))

    # Create shipment batch (use first item's date as batch date)
    first_date = datetime.strptime(shipment_dates[0], '%Y-%m-%d').date() if shipment_dates else date.today()
    shipment = Shipment(
        shipment_date=first_date,
        memo=memo
    )
    db.session.add(shipment)
    db.session.flush()

    # Add items with per-item dates
    total = 0
    for i in range(len(product_ids)):
        if not product_ids[i] or not quantities[i] or not unit_prices[i]:
            continue

        item_date = datetime.strptime(shipment_dates[i], '%Y-%m-%d').date() if i < len(shipment_dates) and shipment_dates[i] else date.today()
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

        item = ShipmentItem(
            shipment_id=shipment.id,
            shipment_date=item_date,
            branch_id=item_branch_id,
            jungsung_id=item_jungsung_id,
            store_id=int(store_ids[i]) if store_ids[i] else None,
            product_id=int(product_ids[i]),
            quantity=qty,
            unit_price=price,
            total_price=item_total,
            created_by=current_user.id  # Track who created this shipment
        )
        db.session.add(item)

    shipment.total_amount = total
    db.session.commit()

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
    product_id = request.args.get('product_id', type=int)
    supplier_id = request.args.get('supplier_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Base query
    query = StockIn.query.filter_by(is_active=True)

    # 지사 사용자인 경우 본인 지사 데이터만 표시
    if current_user.is_branch() and current_user.branch_id:
        query = query.filter(StockIn.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(StockIn.branch_id == branch_id)

    # Apply filters
    if category:
        query = query.join(Product).filter(Product.category == category)
    if product_id:
        query = query.filter(StockIn.product_id == product_id)
    if supplier_id:
        query = query.filter(StockIn.supplier_id == supplier_id)
    if date_from:
        query = query.filter(StockIn.stock_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(StockIn.stock_date <= datetime.strptime(date_to, '%Y-%m-%d').date())

    stockins = query.order_by(StockIn.stock_date.desc(), StockIn.id.desc()).all()

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
        franchise_ids = [f[0] for f in franchise_ids]
        products = Product.query.filter(
            Product.is_active == True,
            Product.franchise_id.in_(franchise_ids)
        ).order_by(Product.name).all()

    return render_template('admin/stockins_list.html',
                           stockins=stockins,
                           products=products,
                           suppliers=suppliers,
                           branches=branches,
                           categories=categories,
                           filters={
                               'category': category,
                               'product_id': product_id,
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
        franchise_ids = [f[0] for f in franchise_ids]
        products = Product.query.filter(
            Product.is_active == True,
            Product.franchise_id.in_(franchise_ids)
        ).order_by(Product.category, Product.name).all()

    return render_template('admin/stockins_create.html',
                           products=products,
                           suppliers=suppliers,
                           branches=branches,
                           categories=categories,
                           today=date.today().isoformat())


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
            branch_id = int(branch_ids[i]) if branch_ids[i] else (current_user.branch_id if current_user.is_branch() else None)
            supplier_id = int(supplier_ids[i]) if supplier_ids[i] else None
            product_id = int(product_ids[i])
            qty = int(quantities[i])
            price = int(unit_prices[i])

            stockin = StockIn(
                stock_date=stock_date,
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

    # 지사 사용자인 경우 본인 지사로 설정
    if current_user.is_branch() and current_user.branch_id:
        branch_id = current_user.branch_id
    elif branch_id:
        branch_id = int(branch_id)

    stockin = StockIn(
        stock_date=stock_date,
        branch_id=branch_id,
        supplier_id=int(supplier_id) if supplier_id else None,
        product_id=int(product_id),
        quantity=qty,
        unit_price=price,
        total_price=qty * price,
        memo=memo,
        created_by=current_user.id  # Track who created this stock-in
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
# 재고현황 (Inventory Status) - Admin + Branch users
# ============================================

@admin_bp.route('/inventory')
@login_required
@branch_required
def inventory_status():
    """Comprehensive inventory status dashboard"""
    from calendar import monthrange

    today = date.today()
    current_year = today.year
    current_month = today.month

    # Get period type (month or range)
    period_type = request.args.get('period_type', 'month')

    # Get filter parameters - 기본값을 현재 달로 설정
    year = request.args.get('year', type=int) or current_year
    month = request.args.get('month', type=int) or current_month
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Franchise filter
    franchise_id = request.args.get('franchise_id', type=int)
    franchise_category = request.args.get('franchise_category')

    # Supplier filter
    supplier_id = request.args.get('supplier_id', type=int)
    supplier_category = request.args.get('supplier_category')
    supplier_franchise_id = request.args.get('supplier_franchise_id', type=int)

    # Branch filter (admin only)
    branch_id = request.args.get('branch_id', type=int)
    branch_franchise_id = request.args.get('branch_franchise_id', type=int)
    branch_category = request.args.get('branch_category')

    # Jungsung filter
    jungsung_id = request.args.get('jungsung_id', type=int)
    jungsung_franchise_id = request.args.get('jungsung_franchise_id', type=int)
    jungsung_category = request.args.get('jungsung_category')

    # Parse date range based on period type
    if period_type == 'range' and date_from and date_to:
        date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
        date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
        period_display = f"{date_from} ~ {date_to}"
    else:
        # 월별 선택 (기본값)
        period_type = 'month'
        _, last_day = monthrange(year, month)
        date_from_parsed = date(year, month, 1)
        date_to_parsed = date(year, month, last_day)
        period_display = f"{year}년 {month}월"

    # ========================================
    # 전체 재고 요약 (Total Stats for selected period)
    # ========================================
    # 총 입고수량
    total_stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.stock_date >= date_from_parsed,
        StockIn.stock_date <= date_to_parsed
    )
    if not current_user.is_admin() and current_user.branch_id:
        total_stockin_query = total_stockin_query.filter(StockIn.branch_id == current_user.branch_id)
    total_stockin = total_stockin_query.scalar() or 0

    # 총 출고수량
    total_shipment_query = db.session.query(func.sum(ShipmentItem.quantity)).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.shipment_date >= date_from_parsed,
        ShipmentItem.shipment_date <= date_to_parsed
    )
    if not current_user.is_admin():
        total_shipment_query = total_shipment_query.filter(ShipmentItem.branch_id == current_user.branch_id)
    total_shipment = total_shipment_query.scalar() or 0

    total_stats = {
        'stockin': total_stockin,
        'shipment': total_shipment,
        'stock': total_stockin - total_shipment
    }

    # ========================================
    # 2. 프랜차이즈별검색 (Franchise Search)
    # ========================================
    franchise_stats = []
    franchise_groups = []
    if franchise_id:
        # Get stores for this franchise
        stores = Store.query.filter_by(franchise_id=franchise_id, is_active=True).all()
        store_ids = [s.id for s in stores]

        # Get products to show (filter by franchise and optionally category)
        products_query = Product.query.filter_by(is_active=True, franchise_id=franchise_id)
        if franchise_category:
            products_query = products_query.filter_by(category=franchise_category)
        products_to_show = products_query.all()

        # Group products by franchise (should be only one franchise, but keep structure consistent)
        franchise_obj = Franchise.query.get(franchise_id)
        product_stats = []

        for product in products_to_show:
            if not product:
                continue

            # 입고수량 - total stock in for this product
            stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
                StockIn.is_active == True,
                StockIn.product_id == product.id
            )
            if date_from_parsed:
                stockin_query = stockin_query.filter(StockIn.stock_date >= date_from_parsed)
            if date_to_parsed:
                stockin_query = stockin_query.filter(StockIn.stock_date <= date_to_parsed)
            stockin_qty = stockin_query.scalar() or 0

            # 출고수량 - shipments to this franchise's stores OR shipments with this product (franchise match)
            shipment_query = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                ShipmentItem.is_active == True,
                ShipmentItem.product_id == product.id
            )
            # Include shipments where store_id is in franchise stores OR store_id is NULL (jungsung/branch level shipments)
            if store_ids:
                shipment_query = shipment_query.filter(
                    or_(
                        ShipmentItem.store_id.in_(store_ids),
                        ShipmentItem.store_id == None
                    )
                )
            if date_from_parsed:
                shipment_query = shipment_query.filter(ShipmentItem.shipment_date >= date_from_parsed)
            if date_to_parsed:
                shipment_query = shipment_query.filter(ShipmentItem.shipment_date <= date_to_parsed)
            if not current_user.is_admin():
                shipment_query = shipment_query.filter(ShipmentItem.branch_id == current_user.branch_id)
            shipment_qty = shipment_query.scalar() or 0

            product_stats.append({
                'product': product,
                'stockin': stockin_qty,
                'shipment': shipment_qty,
                'stock': stockin_qty - shipment_qty
            })

        # Create franchise group with products
        if product_stats:
            franchise_groups.append({
                'franchise': franchise_obj,
                'products': product_stats
            })

        # Keep the old format for backward compatibility (will be removed once template is updated)
        for pstat in product_stats:
            franchise_stats.append({
                'franchise': franchise_obj,
                'product': pstat['product'],
                'stockin': pstat['stockin'],
                'shipment': pstat['shipment'],
                'stock': pstat['stock']
            })

    # ========================================
    # 3. 입고사 월별검색 (Supplier Monthly Search)
    # ========================================
    supplier_stats = []
    if supplier_id:
        # Build product query based on category and/or franchise
        products_query = Product.query.filter_by(is_active=True)
        if supplier_category:
            products_query = products_query.filter_by(category=supplier_category)
        if supplier_franchise_id:
            products_query = products_query.filter_by(franchise_id=supplier_franchise_id)
        products_to_show = products_query.all()

        for product in products_to_show:
            if not product:
                continue

            # 입고수량 from this supplier
            stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
                StockIn.is_active == True,
                StockIn.supplier_id == supplier_id,
                StockIn.product_id == product.id
            )
            if date_from_parsed:
                stockin_query = stockin_query.filter(StockIn.stock_date >= date_from_parsed)
            if date_to_parsed:
                stockin_query = stockin_query.filter(StockIn.stock_date <= date_to_parsed)
            stockin_qty = stockin_query.scalar() or 0

            # 출고수량 for this product
            shipment_query = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                ShipmentItem.is_active == True,
                ShipmentItem.product_id == product.id
            )
            if date_from_parsed:
                shipment_query = shipment_query.filter(ShipmentItem.shipment_date >= date_from_parsed)
            if date_to_parsed:
                shipment_query = shipment_query.filter(ShipmentItem.shipment_date <= date_to_parsed)
            if not current_user.is_admin():
                shipment_query = shipment_query.filter(ShipmentItem.branch_id == current_user.branch_id)
            shipment_qty = shipment_query.scalar() or 0

            if stockin_qty > 0 or shipment_qty > 0:
                supplier_stats.append({
                    'supplier': Supplier.query.get(supplier_id),
                    'franchise': product.franchise,
                    'product': product,
                    'stockin': stockin_qty,
                    'shipment': shipment_qty,
                    'stock': stockin_qty - shipment_qty
                })

    # ========================================
    # 4. 지사별검색 (Branch Search) - Admin only
    # ========================================
    branch_stats = []
    if current_user.is_admin() and branch_id:
        # Filter by franchise if specified
        if branch_franchise_id:
            stores = Store.query.filter_by(branch_id=branch_id, franchise_id=branch_franchise_id, is_active=True).all()
        else:
            stores = Store.query.filter_by(branch_id=branch_id, is_active=True).all()

        # Group by franchise
        franchise_groups = {}
        for store in stores:
            if store.franchise_id not in franchise_groups:
                franchise_groups[store.franchise_id] = []
            franchise_groups[store.franchise_id].append(store.id)

        # Build product query based on category and/or franchise
        products_query = Product.query.filter_by(is_active=True)
        if branch_category:
            products_query = products_query.filter_by(category=branch_category)
        if branch_franchise_id:
            products_query = products_query.filter_by(franchise_id=branch_franchise_id)
        products_to_show = products_query.all()

        for franchise_id_key, store_ids in franchise_groups.items():
            franchise = Franchise.query.get(franchise_id_key)
            for product in products_to_show:
                if not product:
                    continue

                # Skip products that don't belong to this franchise
                if product.franchise_id != franchise_id_key:
                    continue

                # 입고수량 for this branch (StockIn is at branch level, not store level)
                stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True,
                    StockIn.product_id == product.id,
                    StockIn.branch_id == branch_id
                )
                if date_from_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date >= date_from_parsed)
                if date_to_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date <= date_to_parsed)
                stockin_qty = stockin_query.scalar() or 0

                # 출고수량 for this branch and franchise
                # Include shipments with store_id in stores OR store_id is NULL (branch level shipments)
                shipment_query = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.branch_id == branch_id,
                    ShipmentItem.product_id == product.id
                )
                if store_ids:
                    shipment_query = shipment_query.filter(
                        or_(
                            ShipmentItem.store_id.in_(store_ids),
                            ShipmentItem.store_id == None
                        )
                    )
                if date_from_parsed:
                    shipment_query = shipment_query.filter(ShipmentItem.shipment_date >= date_from_parsed)
                if date_to_parsed:
                    shipment_query = shipment_query.filter(ShipmentItem.shipment_date <= date_to_parsed)
                shipment_qty = shipment_query.scalar() or 0

                if stockin_qty > 0 or shipment_qty > 0:
                    branch_stats.append({
                        'branch': Branch.query.get(branch_id),
                        'franchise': franchise,
                        'product': product,
                        'stockin': stockin_qty,
                        'shipment': shipment_qty,
                        'stock': stockin_qty - shipment_qty
                    })

    # ========================================
    # 5. 중상 월별검색 (Jungsung Monthly Search)
    # ========================================
    jungsung_stats = []
    if jungsung_id:
        # Get stores managed by this jungsung
        if jungsung_franchise_id:
            stores = Store.query.filter_by(jungsung_id=jungsung_id, franchise_id=jungsung_franchise_id, is_active=True).all()
        else:
            stores = Store.query.filter_by(jungsung_id=jungsung_id, is_active=True).all()

        # Group by franchise
        franchise_groups = {}
        for store in stores:
            if store.franchise_id not in franchise_groups:
                franchise_groups[store.franchise_id] = []
            franchise_groups[store.franchise_id].append(store.id)

        # Build product query based on category and/or franchise
        products_query = Product.query.filter_by(is_active=True)
        if jungsung_category:
            products_query = products_query.filter_by(category=jungsung_category)
        if jungsung_franchise_id:
            products_query = products_query.filter_by(franchise_id=jungsung_franchise_id)
        products_to_show = products_query.all()

        for franchise_id_key, store_ids in franchise_groups.items():
            franchise = Franchise.query.get(franchise_id_key)
            for product in products_to_show:
                if not product:
                    continue

                # Skip if product doesn't belong to this franchise
                if product.franchise_id != franchise_id_key:
                    continue

                # 출고수량 for this product and these stores
                # Handle both new data (with store_id) and old data (with jungsung_id only)
                shipment_query = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.product_id == product.id,
                    or_(
                        ShipmentItem.store_id.in_(store_ids),
                        and_(
                            ShipmentItem.jungsung_id == jungsung_id,
                            ShipmentItem.store_id == None
                        )
                    )
                )
                if date_from_parsed:
                    shipment_query = shipment_query.filter(ShipmentItem.shipment_date >= date_from_parsed)
                if date_to_parsed:
                    shipment_query = shipment_query.filter(ShipmentItem.shipment_date <= date_to_parsed)
                if not current_user.is_admin():
                    shipment_query = shipment_query.filter(ShipmentItem.branch_id == current_user.branch_id)
                shipment_qty = shipment_query.scalar() or 0

                # ERP등록 - Calculate from ERPRegistration table (excluding 폐유)
                # Get all ERP registrations for these stores in the date range
                erp_query = ERPRegistration.query.filter(
                    ERPRegistration.store_id.in_(store_ids),
                    ERPRegistration.is_return == False
                )
                if date_from_parsed:
                    erp_query = erp_query.filter(ERPRegistration.registration_date >= date_from_parsed)
                if date_to_parsed:
                    erp_query = erp_query.filter(ERPRegistration.registration_date <= date_to_parsed)
                erp_regs = erp_query.all()

                # Sum quantities for this product's category (excluding 폐유)
                erp_registered = 0
                if product.category != '폐유':  # Only count if product itself is not 폐유
                    for erp_reg in erp_regs:
                        qty_dict = erp_reg.get_category_quantities()
                        if qty_dict and product.category in qty_dict:
                            erp_registered += qty_dict[product.category]

                # Calculate unregistered (allow negative values to show over-registration)
                erp_unregistered = shipment_qty - erp_registered

                if shipment_qty > 0 or erp_registered > 0:
                    jungsung_stats.append({
                        'jungsung': Jungsung.query.get(jungsung_id),
                        'franchise': franchise,
                        'product': product,
                        'shipment': shipment_qty,
                        'erp_registered': erp_registered,
                        'erp_unregistered': erp_unregistered
                    })

    # Get data for filter dropdowns
    franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.category, Product.name).all()

    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
        jungsungs = Jungsung.query.filter_by(is_active=True).order_by(Jungsung.business_name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []
        jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()

    return render_template('admin/inventory_status.html',
                           year=year,
                           month=month,
                           current_year=current_year,
                           period_type=period_type,
                           period_display=period_display,
                           total_stats=total_stats,
                           franchise_stats=franchise_stats,
                           franchise_groups=franchise_groups,
                           supplier_stats=supplier_stats,
                           branch_stats=branch_stats,
                           jungsung_stats=jungsung_stats,
                           franchises=franchises,
                           suppliers=suppliers,
                           products=products,
                           branches=branches,
                           jungsungs=jungsungs,
                           filters={
                               'year': year,
                               'month': month,
                               'date_from': date_from,
                               'date_to': date_to,
                               'franchise_id': franchise_id,
                               'franchise_category': franchise_category,
                               'supplier_id': supplier_id,
                               'supplier_category': supplier_category,
                               'supplier_franchise_id': supplier_franchise_id,
                               'branch_id': branch_id,
                               'branch_franchise_id': branch_franchise_id,
                               'branch_category': branch_category,
                               'jungsung_id': jungsung_id,
                               'jungsung_franchise_id': jungsung_franchise_id,
                               'jungsung_category': jungsung_category
                           })


# ============================================
# 미수금 관리 (Accounts Receivable Management)
# ============================================

@admin_bp.route('/receivables')
@login_required
@branch_required
def receivables():
    """미수금 관리 - Accounts Receivable Management - accessible by admin and branch users"""
    # Get filter parameters
    franchise_id = request.args.get('franchise_id', type=int)
    product_id = request.args.get('product_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Parse dates
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

    # Get branches for columns - branch users only see their own branch
    if current_user.is_admin():
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    else:
        branches = [current_user.branch] if current_user.branch else []

    # Build data structure: Group by franchise, then by product
    franchises_query = Franchise.query.filter_by(is_active=True)
    if franchise_id:
        franchises_query = franchises_query.filter_by(id=franchise_id)
    franchises = franchises_query.order_by(Franchise.name).all()

    # Build receivables data
    receivables_data = []

    # Pre-calculate total payments per branch for the summary row
    branch_total_payments = {}
    for branch in branches:
        payments_query = db.session.query(func.sum(Payment.amount)).filter(
            Payment.is_active == True,
            Payment.branch_id == branch.id
        )
        if date_from_parsed:
            payments_query = payments_query.filter(Payment.payment_date >= date_from_parsed)
        if date_to_parsed:
            payments_query = payments_query.filter(Payment.payment_date <= date_to_parsed)

        branch_total_payments[branch.id] = payments_query.scalar() or 0

    for franchise in franchises:
        # Get products for this franchise
        products_query = Product.query.filter_by(is_active=True, franchise_id=franchise.id)
        if product_id:
            products_query = products_query.filter_by(id=product_id)
        products = products_query.order_by(Product.name).all()

        for product in products:
            row_data = {
                'franchise': franchise,
                'product': product,
                'branches': {}
            }

            total_qty = 0
            total_amount = 0
            total_paid = 0

            for branch in branches:
                # Calculate 입고 quantity for this branch/franchise/product
                stockin_query = db.session.query(func.sum(StockIn.quantity)).filter(
                    StockIn.is_active == True,
                    StockIn.branch_id == branch.id,
                    StockIn.product_id == product.id
                )
                if date_from_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date >= date_from_parsed)
                if date_to_parsed:
                    stockin_query = stockin_query.filter(StockIn.stock_date <= date_to_parsed)

                qty = stockin_query.scalar() or 0

                # Calculate amount (입고 * 단가)
                amount = qty * product.unit_price if qty > 0 else 0

                # Calculate payments for this specific franchise/product/branch combination
                payment_query = db.session.query(func.sum(Payment.amount)).filter(
                    Payment.is_active == True,
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
                    'qty': qty,
                    'amount': amount,
                    'paid': paid,
                    'unpaid': amount - paid
                }

                total_qty += qty
                total_amount += amount
                total_paid += paid

            row_data['total_qty'] = total_qty
            row_data['total_amount'] = total_amount
            row_data['total_paid'] = total_paid
            row_data['total_unpaid'] = total_amount - total_paid

            # Only add rows with data
            if total_qty > 0 or total_paid > 0:
                receivables_data.append(row_data)

    # Get all franchises and products for filter dropdowns
    if current_user.is_admin():
        all_franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.name).all()
        all_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    else:
        # Branch users only see franchises and products related to their branch
        franchise_ids = db.session.query(Store.franchise_id).filter(
            Store.branch_id == current_user.branch_id,
            Store.is_active == True
        ).distinct().all()
        franchise_ids = [f[0] for f in franchise_ids]
        all_franchises = Franchise.query.filter(
            Franchise.is_active == True,
            Franchise.id.in_(franchise_ids)
        ).order_by(Franchise.name).all()
        all_products = Product.query.filter(
            Product.is_active == True,
            Product.franchise_id.in_(franchise_ids)
        ).order_by(Product.name).all()

    # Calculate grand totals
    grand_total_unpaid = sum(row['total_unpaid'] for row in receivables_data)

    return render_template('admin/receivables.html',
                           branches=branches,
                           receivables_data=receivables_data,
                           grand_total_unpaid=grand_total_unpaid,
                           branch_total_payments=branch_total_payments,
                           all_franchises=all_franchises,
                           all_products=all_products,
                           filters={
                               'franchise_id': franchise_id,
                               'product_id': product_id,
                               'date_from': date_from,
                               'date_to': date_to
                           })


@admin_bp.route('/api/payments/add', methods=['POST'])
@login_required
@branch_required
def add_payment():
    """Add a new payment entry - accessible by admin and branch users"""
    try:
        data = request.get_json()

        payment = Payment(
            payment_date=datetime.strptime(data['payment_date'], '%Y-%m-%d').date(),
            branch_id=data['branch_id'],
            franchise_id=data.get('franchise_id'),
            product_id=data.get('product_id'),
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
                'branch': payment.branch.name,
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
    """Delete a payment entry - accessible by admin and branch users"""
    try:
        payment = Payment.query.get_or_404(payment_id)

        # Branch users can only delete payments from their branch
        if not current_user.is_admin() and payment.branch_id != current_user.branch_id:
            return jsonify({'success': False, 'message': '권한이 없습니다.'}), 403

        payment.is_active = False
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '입금 내역이 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@admin_bp.route('/api/payments/list')
@login_required
@branch_required
def list_payments():
    """Get list of payments - accessible by admin and branch users"""
    branch_id = request.args.get('branch_id', type=int)
    franchise_id = request.args.get('franchise_id', type=int)
    product_id = request.args.get('product_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    payments_query = Payment.query.filter_by(is_active=True)

    # Branch users only see payments from their branch
    if not current_user.is_admin():
        payments_query = payments_query.filter_by(branch_id=current_user.branch_id)

    if branch_id:
        payments_query = payments_query.filter_by(branch_id=branch_id)
    if franchise_id:
        payments_query = payments_query.filter_by(franchise_id=franchise_id)
    if product_id:
        payments_query = payments_query.filter_by(product_id=product_id)

    # Date filtering
    if date_from:
        try:
            date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
            payments_query = payments_query.filter(Payment.payment_date >= date_from_parsed)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
            payments_query = payments_query.filter(Payment.payment_date <= date_to_parsed)
        except ValueError:
            pass

    payments = payments_query.order_by(Payment.payment_date.desc()).all()

    return jsonify({
        'success': True,
        'payments': [{
            'id': p.id,
            'payment_date': p.payment_date.strftime('%Y-%m-%d'),
            'branch': p.branch.name if p.branch else '-',
            'franchise': p.franchise.name if p.franchise else '-',
            'product': p.product.name if p.product else '-',
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
    """ERP Registration Tracking - Monthly and Date Range views by store
    Shows data registered by 중상 users via ERPRegistration model"""
    import json
    from calendar import monthrange

    # Get filter parameters
    year = request.args.get('year', type=int) or date.today().year
    month = request.args.get('month', type=int) or date.today().month

    # Date range filter
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Default date range to current month if not specified
    today = date.today()
    if not date_from:
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
    if not date_to:
        date_to = today.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get active categories
    categories = Category.query.filter_by(is_active=True).order_by(Category.id).all()
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

    # Calculate week ranges for the selected month
    _, last_day = monthrange(year, month)
    weeks = []
    week_num = 1
    day = 1
    while day <= last_day:
        week_start = date(year, month, day)
        week_end_day = min(day + 6, last_day)
        week_end = date(year, month, week_end_day)
        weeks.append({
            'num': week_num,
            'start': week_start,
            'end': week_end
        })
        day = week_end_day + 1
        week_num += 1

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

    return render_template('admin/erp_tracking.html',
                           year=year,
                           month=month,
                           weeks=weeks,
                           categories=categories,
                           category_names=category_names,
                           weekly_data=weekly_data,
                           daterange_weeks=daterange_weeks,
                           daterange_data=daterange_data,
                           date_from=date_from,
                           date_to=date_to)


@admin_bp.route('/daily-shipments')
@login_required
@branch_required
def daily_shipments():
    """Daily shipment search - Branch users only (지사 전용)"""
    # Only allow branch users (not admin)
    if current_user.is_admin():
        flash('이 페이지는 지사 전용입니다.', 'warning')
        return redirect(url_for('admin.shipments_list'))

    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    jungsung_id = request.args.get('jungsung_id', type=int)
    franchise_id = request.args.get('franchise_id', type=int)

    # Default to current month if no dates specified
    today = date.today()
    if not date_from:
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
    if not date_to:
        date_to = today.strftime('%Y-%m-%d')

    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get product categories
    oil_products = Product.query.filter_by(category='식용유', is_active=True).all()
    oil_product_ids = [p.id for p in oil_products]

    flour_products = Product.query.filter_by(category='밀가루', is_active=True).all()
    flour_product_ids = [p.id for p in flour_products]

    # Base query - only this branch's shipments
    base_query = ShipmentItem.query.filter(
        ShipmentItem.is_active == True,
        ShipmentItem.branch_id == current_user.branch_id,
        ShipmentItem.shipment_date >= date_from_parsed,
        ShipmentItem.shipment_date <= date_to_parsed
    )

    if jungsung_id:
        base_query = base_query.filter(ShipmentItem.jungsung_id == jungsung_id)

    # Get all matching shipment items
    items = base_query.order_by(ShipmentItem.shipment_date.asc()).all()

    # Group by date, jungsung (person), and franchise
    daily_data = {}
    for item in items:
        # Get store's franchise
        store = item.store
        if not store:
            continue

        if franchise_id and store.franchise_id != franchise_id:
            continue

        key = (
            item.shipment_date,
            item.jungsung_id,
            store.franchise_id
        )

        if key not in daily_data:
            daily_data[key] = {
                'date': item.shipment_date,
                'jungsung': item.jungsung,
                'franchise': store.franchise,
                'oil': 0,
                'flour': 0
            }

        # Add quantities based on product category
        if item.product_id in oil_product_ids:
            daily_data[key]['oil'] += item.quantity
        elif item.product_id in flour_product_ids:
            daily_data[key]['flour'] += item.quantity

    # Convert to list and sort
    daily_list = sorted(daily_data.values(), key=lambda x: (x['date'], x['jungsung'].contact_person if x['jungsung'] else ''))

    # Calculate totals
    total_oil = sum(d['oil'] for d in daily_list)
    total_flour = sum(d['flour'] for d in daily_list)

    # Get filter dropdown data
    jungsungs = Jungsung.query.filter_by(is_active=True, branch_id=current_user.branch_id).order_by(Jungsung.business_name).all()

    # Get franchises that have stores in this branch
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
                           total_oil=total_oil,
                           total_flour=total_flour,
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

    # Get search type (주별/월별/기간)
    search_type = request.args.get('search_type', 'weekly')

    # Get filter parameters
    year = request.args.get('year', type=int) or date.today().year
    month = request.args.get('month', type=int) or date.today().month

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

    # Get active categories (excluding 폐유)
    regular_products = Product.query.filter(
        Product.is_active == True,
        Product.category != '폐유'
    ).all()
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
        franchise_ids = [f[0] for f in franchise_ids]
        franchises = Franchise.query.filter(
            Franchise.is_active == True,
            Franchise.id.in_(franchise_ids)
        ).order_by(Franchise.name).all()

    # ========================================
    # 1. 주별 검색 (Weekly Search) - Select year/month, see weekly breakdown
    # ========================================
    weekly_data = []
    weeks = []
    if search_type == 'weekly':
        # Calculate weeks in the selected month
        _, last_day = monthrange(year, month)
        week_num = 1
        day = 1
        while day <= last_day:
            week_start = date(year, month, day)
            week_end_day = min(day + 6, last_day)
            week_end = date(year, month, week_end_day)
            weeks.append({
                'num': week_num,
                'start': week_start,
                'end': week_end
            })
            day = week_end_day + 1
            week_num += 1

        # Get all stores with their jungsung assignments
        stores_query = Store.query.filter_by(is_active=True)
        if not current_user.is_admin():
            stores_query = stores_query.filter_by(branch_id=current_user.branch_id)
        stores = stores_query.order_by(Store.branch_id, Store.franchise_id, Store.name).all()

        # Build weekly data for each store
        for store in stores:
            store_data = {
                'store': store,
                'branch': store.branch,
                'jungsung': store.jungsung,
                'franchise': store.franchise,
                'weeks': [],
                'totals': {'shipment': 0, 'erp': 0, 'unregistered': 0}
            }

            # For each week, calculate shipment, ERP, and unregistered
            for week in weeks:
                # Shipment quantity for this store in this week
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= week['start'],
                    ShipmentItem.shipment_date <= week['end']
                ).scalar() or 0

                # ERP registration quantity for this store in this week
                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= week['start'],
                    ERPRegistration.registration_date <= week['end']
                ).all()

                erp_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += sum(qty_dict.values()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty if shipment_qty > erp_qty else 0

                store_data['weeks'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['unregistered'] += unregistered

            # Only include stores with data
            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                weekly_data.append(store_data)

    # ========================================
    # 2. 월별 검색 (Monthly Search) - Select year, see all 12 months
    # ========================================
    monthly_data = []
    months_list = []
    if search_type == 'monthly':
        months_list = [{'num': m, 'name': f'{m}월'} for m in range(1, 13)]

        # Get all stores
        stores_query = Store.query.filter_by(is_active=True)
        if not current_user.is_admin():
            stores_query = stores_query.filter_by(branch_id=current_user.branch_id)
        stores = stores_query.order_by(Store.branch_id, Store.franchise_id, Store.name).all()

        # Build monthly data for each store
        for store in stores:
            store_data = {
                'store': store,
                'branch': store.branch,
                'jungsung': store.jungsung,
                'franchise': store.franchise,
                'months': [],
                'totals': {'shipment': 0, 'erp': 0, 'unregistered': 0}
            }

            # For each month, calculate shipment, ERP, and unregistered
            for m in range(1, 13):
                first_day = date(year, m, 1)
                last_day = date(year, m, monthrange(year, m)[1])

                # Shipment quantity for this store in this month
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= first_day,
                    ShipmentItem.shipment_date <= last_day
                ).scalar() or 0

                # ERP registration quantity for this store in this month
                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= first_day,
                    ERPRegistration.registration_date <= last_day
                ).all()

                erp_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += sum(qty_dict.values()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty if shipment_qty > erp_qty else 0

                store_data['months'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['unregistered'] += unregistered

            # Only include stores with data
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

        # Get all stores
        stores_query = Store.query.filter_by(is_active=True)
        if not current_user.is_admin():
            stores_query = stores_query.filter_by(branch_id=current_user.branch_id)
        stores = stores_query.order_by(Store.branch_id, Store.franchise_id, Store.name).all()

        # Build period data for each store
        for store in stores:
            store_data = {
                'store': store,
                'branch': store.branch,
                'jungsung': store.jungsung,
                'franchise': store.franchise,
                'periods': [],
                'totals': {'shipment': 0, 'erp': 0, 'unregistered': 0}
            }

            # For each period, calculate shipment, ERP, and unregistered
            for period in periods:
                # Shipment quantity for this store in this period
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= period['start'],
                    ShipmentItem.shipment_date <= period['end']
                ).scalar() or 0

                # ERP registration quantity for this store in this period
                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= period['start'],
                    ERPRegistration.registration_date <= period['end']
                ).all()

                erp_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += sum(qty_dict.values()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty if shipment_qty > erp_qty else 0

                store_data['periods'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['unregistered'] += unregistered

            # Only include stores with data
            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                period_data.append(store_data)

    return render_template('admin/erp_tracking_admin.html',
                           search_type=search_type,
                           year=year,
                           month=month,
                           date_from=date_from,
                           date_to=date_to,
                           view_type=view_type,
                           weekly_data=weekly_data,
                           weeks=weeks,
                           monthly_data=monthly_data,
                           months_list=months_list,
                           period_data=period_data,
                           periods=periods,
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
            registration_date = date.today()
    else:
        registration_date = date.today()

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

    return render_template('admin/erp_registration.html',
                           registration_date=registration_date,
                           jungsung=jungsung,
                           franchise_groups=franchise_groups,
                           reg_by_store=reg_by_store,
                           categories=categories)


@admin_bp.route('/erp-registration/save', methods=['POST'])
@login_required
@jungsung_required
def erp_registration_save():
    """Save ERP registration data"""
    jungsung = current_user.jungsung
    if not jungsung:
        return jsonify({'success': False, 'message': '연결된 중상 정보가 없습니다.'})

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '데이터가 없습니다.'})

    registration_date_str = data.get('date')
    store_id = data.get('store_id')
    stockin_qty = data.get('stockin_qty', 0) or 0
    waste_qty = data.get('waste_qty', 0) or 0
    is_return = data.get('is_return', False)

    try:
        registration_date = datetime.strptime(registration_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '잘못된 날짜 형식입니다.'})

    # Verify store belongs to this jungsung
    store = Store.query.filter_by(id=store_id, jungsung_id=jungsung.id).first()
    if not store:
        return jsonify({'success': False, 'message': '해당 매장에 대한 권한이 없습니다.'})

    # Check for existing registration
    existing = ERPRegistration.query.filter_by(
        registration_date=registration_date,
        store_id=store_id,
        jungsung_id=jungsung.id,
        is_return=is_return
    ).first()

    if existing:
        # Update existing
        existing.stockin_qty = stockin_qty
        existing.waste_qty = waste_qty
        existing.updated_at = datetime.utcnow()
    else:
        # Create new
        new_reg = ERPRegistration(
            registration_date=registration_date,
            store_id=store_id,
            jungsung_id=jungsung.id,
            stockin_qty=stockin_qty,
            waste_qty=waste_qty,
            is_return=is_return,
            created_by=current_user.id
        )
        db.session.add(new_reg)

    db.session.commit()
    return jsonify({'success': True, 'message': '저장되었습니다.'})


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
    """ERP Registration Tracking for Jungsung users - Shows shipments vs ERP registrations"""
    # Get date filter
    selected_date = request.args.get('date')
    if selected_date:
        try:
            filter_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            filter_date = date.today()
    else:
        filter_date = date.today()

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

    # Get product categories for shipment calculation
    regular_products = Product.query.filter(
        Product.is_active == True,
        Product.category != '폐유'
    ).all()
    regular_product_ids = [p.id for p in regular_products]

    # Get total shipment for this jungsung on this date (from 출고)
    # This includes ALL shipments with this jungsung_id regardless of store
    total_shipment = db.session.query(func.sum(ShipmentItem.quantity)).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.jungsung_id == jungsung.id,
        ShipmentItem.product_id.in_(regular_product_ids) if regular_product_ids else True,
        ShipmentItem.shipment_date == filter_date
    ).scalar() or 0

    # Build tracking data grouped by franchise
    total_shipment_stores = 0  # Sum from per-store shipments
    total_erp_registered = 0
    total_unregistered = 0

    # Group stores by franchise
    franchise_dict = {}
    for store in stores:
        if store.franchise_id not in franchise_dict:
            franchise_dict[store.franchise_id] = {
                'franchise': store.franchise,
                'stores': []
            }
        franchise_dict[store.franchise_id]['stores'].append(store)

    # Build franchise groups with store data (ERP registration per store)
    franchise_groups = []
    for franchise_id, group in franchise_dict.items():
        group_data = {
            'franchise': group['franchise'],
            'stores': []
        }

        # Calculate per-store values
        for store in group['stores']:
            # 출고: Shipments to THIS STORE on this date (excluding 폐유)
            store_shipment = db.session.query(func.sum(ShipmentItem.quantity)).join(
                Product
            ).filter(
                ShipmentItem.is_active == True,
                ShipmentItem.store_id == store.id,
                ShipmentItem.shipment_date == filter_date,
                Product.category != '폐유'
            ).scalar() or 0

            # ERP등록: Total for THIS STORE on this date (excluding 폐유)
            store_erp = 0
            erp_regs = ERPRegistration.query.filter(
                ERPRegistration.registration_date == filter_date,
                ERPRegistration.store_id == store.id,
                ERPRegistration.is_return == False
            ).all()

            for erp_reg in erp_regs:
                qty_dict = erp_reg.get_category_quantities()
                if qty_dict:
                    for category, qty in qty_dict.items():
                        if category != '폐유':
                            store_erp += qty

            # 미등록: 출고 - ERP등록 for THIS STORE (allow negative values)
            store_unregistered = store_shipment - store_erp

            group_data['stores'].append({
                'store': store,
                'shipment': store_shipment,
                'erp_registered': store_erp,
                'unregistered': store_unregistered
            })

            # Accumulate totals
            total_shipment_stores += store_shipment
            total_erp_registered += store_erp
            total_unregistered += store_unregistered

        franchise_groups.append(group_data)

    return render_template('admin/erp_tracking_jungsung.html',
                           filter_date=filter_date,
                           jungsung=jungsung,
                           franchise_groups=franchise_groups,
                           total_shipment=total_shipment_stores,
                           total_erp_registered=total_erp_registered,
                           total_unregistered=total_unregistered)


@admin_bp.route('/erp-tracking-franchise')
@login_required
@franchise_required
def erp_tracking_franchise():
    """ERP Registration Quantity Check for Franchise users
    Three search types: Weekly, Monthly, and Period Search (matching admin version)"""
    from calendar import monthrange

    # Get search type (주별/월별/기간)
    search_type = request.args.get('search_type', 'weekly')

    # Get filter parameters
    year = request.args.get('year', type=int) or date.today().year
    month = request.args.get('month', type=int) or date.today().month

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

    # Get active categories (excluding 폐유)
    regular_products = Product.query.filter(
        Product.is_active == True,
        Product.category != '폐유'
    ).all()
    regular_product_ids = [p.id for p in regular_products]

    # Get stores belonging to this franchise
    stores = Store.query.filter_by(
        franchise_id=franchise.id,
        is_active=True
    ).order_by(Store.name).all()

    # ========================================
    # 1. 주별 검색 (Weekly Search) - Select year/month, see weekly breakdown
    # ========================================
    weekly_data = []
    weeks = []
    if search_type == 'weekly':
        # Calculate weeks in the selected month
        _, last_day = monthrange(year, month)
        week_num = 1
        day = 1
        while day <= last_day:
            week_start = date(year, month, day)
            week_end_day = min(day + 6, last_day)
            week_end = date(year, month, week_end_day)
            weeks.append({
                'num': week_num,
                'start': week_start,
                'end': week_end
            })
            day = week_end_day + 1
            week_num += 1

        # Build weekly data for each store
        for store in stores:
            store_data = {
                'store': store,
                'weeks': [],
                'totals': {'shipment': 0, 'erp': 0, 'unregistered': 0}
            }

            # For each week, calculate shipment, ERP, and unregistered
            for week in weeks:
                # Shipment quantity for this store in this week
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= week['start'],
                    ShipmentItem.shipment_date <= week['end']
                ).scalar() or 0

                # ERP registration quantity for this store in this week
                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= week['start'],
                    ERPRegistration.registration_date <= week['end']
                ).all()

                erp_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += sum(qty_dict.values()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty if shipment_qty > erp_qty else 0

                store_data['weeks'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['unregistered'] += unregistered

            # Only include stores with data
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
                'totals': {'shipment': 0, 'erp': 0, 'unregistered': 0}
            }

            # For each month, calculate shipment, ERP, and unregistered
            for m in range(1, 13):
                first_day = date(year, m, 1)
                last_day = date(year, m, monthrange(year, m)[1])

                # Shipment quantity for this store in this month
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= first_day,
                    ShipmentItem.shipment_date <= last_day
                ).scalar() or 0

                # ERP registration quantity for this store in this month
                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= first_day,
                    ERPRegistration.registration_date <= last_day
                ).all()

                erp_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += sum(qty_dict.values()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty if shipment_qty > erp_qty else 0

                store_data['months'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['unregistered'] += unregistered

            # Only include stores with data
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
                'totals': {'shipment': 0, 'erp': 0, 'unregistered': 0}
            }

            # For each period, calculate shipment, ERP, and unregistered
            for period in periods:
                # Shipment quantity for this store in this period
                shipment_qty = db.session.query(func.sum(ShipmentItem.quantity)).filter(
                    ShipmentItem.is_active == True,
                    ShipmentItem.store_id == store.id,
                    ShipmentItem.product_id.in_(regular_product_ids),
                    ShipmentItem.shipment_date >= period['start'],
                    ShipmentItem.shipment_date <= period['end']
                ).scalar() or 0

                # ERP registration quantity for this store in this period
                erp_regs = ERPRegistration.query.filter(
                    ERPRegistration.store_id == store.id,
                    ERPRegistration.is_return == False,
                    ERPRegistration.registration_date >= period['start'],
                    ERPRegistration.registration_date <= period['end']
                ).all()

                erp_qty = 0
                for reg in erp_regs:
                    qty_dict = reg.get_category_quantities()
                    erp_qty += sum(qty_dict.values()) if qty_dict else 0

                unregistered = shipment_qty - erp_qty if shipment_qty > erp_qty else 0

                store_data['periods'].append({
                    'shipment': shipment_qty,
                    'erp': erp_qty,
                    'unregistered': unregistered
                })

                store_data['totals']['shipment'] += shipment_qty
                store_data['totals']['erp'] += erp_qty
                store_data['totals']['unregistered'] += unregistered

            # Only include stores with data
            if store_data['totals']['shipment'] > 0 or store_data['totals']['erp'] > 0:
                period_data.append(store_data)

    return render_template('admin/erp_tracking_franchise.html',
                           search_type=search_type,
                           year=year,
                           month=month,
                           date_from=date_from,
                           date_to=date_to,
                           view_type=view_type,
                           weekly_data=weekly_data,
                           weeks=weeks,
                           monthly_data=monthly_data,
                           months_list=months_list,
                           period_data=period_data,
                           periods=periods,
                           franchise=franchise)


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
    two_months_ago = date.today() - timedelta(days=60)

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
    recent_stockin = ERPRegistration.query.filter(
        ERPRegistration.store_id == store_id,
        ERPRegistration.is_return == False,
        ERPRegistration.stockin_qty > 0,
        ERPRegistration.registration_date >= two_months_ago
    ).first()
    store.unused_store = (recent_stockin is None)

    # Check uncollected_waste_oil - no waste oil (폐유) registered in last 2 months
    recent_waste = ERPRegistration.query.filter(
        ERPRegistration.store_id == store_id,
        ERPRegistration.is_return == False,
        ERPRegistration.waste_qty > 0,
        ERPRegistration.registration_date >= two_months_ago
    ).first()
    store.uncollected_waste_oil = (recent_waste is None)

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
    if field not in ['closed_store', 'bad_debt_store']:
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
