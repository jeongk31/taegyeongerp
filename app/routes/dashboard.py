from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app.utils.decorators import admin_required, branch_required, driver_required, franchise_required, jungsung_required
from app.models import User, Branch, Franchise, Store, Product, ShipmentItem, StockIn, Jungsung, ERPRegistration
from app import db
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from datetime import date, datetime, timedelta

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """
    Redirect to the appropriate dashboard based on user role.
    """
    if current_user.is_admin():
        return redirect(url_for('dashboard.admin'))
    elif current_user.is_branch():
        return redirect(url_for('dashboard.branch'))
    elif current_user.is_driver():
        return redirect(url_for('dashboard.driver'))
    elif current_user.is_franchise():
        return redirect(url_for('dashboard.franchise'))
    elif current_user.is_jungsung():
        return redirect(url_for('dashboard.jungsung'))
    else:
        return redirect(url_for('auth.login'))


@dashboard_bp.route('/admin')
@login_required
@admin_required
def admin():
    """
    Admin dashboard - 관리자
    Full access to all data and user management.
    """
    today = date.today()
    first_of_month = today.replace(day=1)

    # User counts
    total_users = User.query.count()
    branch_count = Branch.query.filter_by(is_active=True).count()
    franchise_count = Franchise.query.filter_by(is_active=True).count()
    store_count = Store.query.filter_by(is_active=True).count()
    jungsung_count = Jungsung.query.filter_by(is_active=True).count()

    # Today's stats
    today_shipments = db.session.query(func.sum(ShipmentItem.quantity)).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.shipment_date == today
    ).scalar() or 0

    today_stockins = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.stock_date == today
    ).scalar() or 0

    # This month's stats
    month_shipments = db.session.query(func.sum(ShipmentItem.quantity)).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.shipment_date >= first_of_month
    ).scalar() or 0

    month_stockins = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.stock_date >= first_of_month
    ).scalar() or 0

    # Recent users
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()

    return render_template('dashboard/admin.html',
                           total_users=total_users,
                           branch_count=branch_count,
                           franchise_count=franchise_count,
                           store_count=store_count,
                           jungsung_count=jungsung_count,
                           today_shipments=today_shipments,
                           today_stockins=today_stockins,
                           month_shipments=month_shipments,
                           month_stockins=month_stockins,
                           recent_users=recent_users)


@dashboard_bp.route('/branch')
@login_required
@branch_required
def branch():
    """
    Branch dashboard - 지사
    Can see only their branch-specific data.
    """
    today = date.today()
    first_of_month = today.replace(day=1)
    branch_id = current_user.branch_id

    # Branch-specific counts
    store_count = Store.query.filter_by(branch_id=branch_id, is_active=True).count()
    jungsung_count = Jungsung.query.filter_by(branch_id=branch_id, is_active=True).count()

    # Get franchise IDs in this branch
    franchise_ids = db.session.query(Store.franchise_id).filter(
        Store.branch_id == branch_id,
        Store.is_active == True
    ).distinct().all()
    franchise_ids = [f[0] for f in franchise_ids]
    franchise_count = len(franchise_ids)

    # Today's stats
    today_shipments = db.session.query(func.sum(ShipmentItem.quantity)).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.branch_id == branch_id,
        ShipmentItem.shipment_date == today
    ).scalar() or 0

    today_stockins = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.branch_id == branch_id,
        StockIn.stock_date == today
    ).scalar() or 0

    # This month's stats
    month_shipments = db.session.query(func.sum(ShipmentItem.quantity)).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.branch_id == branch_id,
        ShipmentItem.shipment_date >= first_of_month
    ).scalar() or 0

    month_stockins = db.session.query(func.sum(StockIn.quantity)).filter(
        StockIn.is_active == True,
        StockIn.branch_id == branch_id,
        StockIn.stock_date >= first_of_month
    ).scalar() or 0

    # Inventory per category - batch query using JOINs (2 queries instead of 2*N)
    stockin_by_cat = db.session.query(
        Product.category,
        func.sum(StockIn.quantity)
    ).join(Product, StockIn.product_id == Product.id).filter(
        StockIn.is_active == True,
        StockIn.branch_id == branch_id,
        Product.is_active == True
    ).group_by(Product.category).all()

    shipped_by_cat = db.session.query(
        Product.category,
        func.sum(ShipmentItem.quantity)
    ).join(Product, ShipmentItem.product_id == Product.id).filter(
        ShipmentItem.is_active == True,
        ShipmentItem.branch_id == branch_id,
        Product.is_active == True
    ).group_by(Product.category).all()

    stockin_dict = {cat: qty or 0 for cat, qty in stockin_by_cat}
    shipped_dict = {cat: qty or 0 for cat, qty in shipped_by_cat}
    all_cats = sorted(set(stockin_dict.keys()) | set(shipped_dict.keys()))

    inventory_by_category = []
    total_inventory = 0
    for cat in all_cats:
        cat_stockin = stockin_dict.get(cat, 0)
        cat_shipped = shipped_dict.get(cat, 0)
        cat_inventory = cat_stockin - cat_shipped
        total_inventory += cat_inventory
        inventory_by_category.append({
            'category': cat,
            'stockin': cat_stockin,
            'shipped': cat_shipped,
            'inventory': cat_inventory
        })

    # Recent shipments with eager loading
    recent_shipments = ShipmentItem.query.filter(
        ShipmentItem.is_active == True,
        ShipmentItem.branch_id == branch_id
    ).options(
        joinedload(ShipmentItem.product).joinedload(Product.franchise),
        joinedload(ShipmentItem.store),
        joinedload(ShipmentItem.jungsung)
    ).order_by(ShipmentItem.shipment_date.desc()).limit(10).all()

    return render_template('dashboard/branch.html',
                           store_count=store_count,
                           jungsung_count=jungsung_count,
                           today_shipments=today_shipments,
                           today_stockins=today_stockins,
                           month_shipments=month_shipments,
                           month_stockins=month_stockins,
                           inventory_by_category=inventory_by_category,
                           total_inventory=total_inventory,
                           recent_shipments=recent_shipments)


@dashboard_bp.route('/driver')
@login_required
@driver_required
def driver():
    """
    Driver dashboard - 배송기사
    Can see assigned deliveries with limited edit capabilities.
    """
    return render_template('dashboard/driver.html')


@dashboard_bp.route('/franchise')
@login_required
@franchise_required
def franchise():
    """
    Franchise HQ dashboard - 프랜차이즈 본사
    Separate from hierarchy, can only see their own data.
    """
    franchise = current_user.franchise

    # Get all stores under this franchise
    stores = Store.query.filter_by(franchise_id=franchise.id, is_active=True).all()
    total_stores = len(stores)

    # Count stores with issues
    stores_with_no_shipment = sum(1 for s in stores if s.no_shipment_2months)
    stores_unused = sum(1 for s in stores if s.unused_store)
    stores_waste_uncollected = sum(1 for s in stores if s.uncollected_waste_oil)
    stores_closed = sum(1 for s in stores if s.closed_store)
    stores_bad_debt = sum(1 for s in stores if s.bad_debt_store)

    # Total stores with any issue
    stores_with_issues = sum(1 for s in stores if any([
        s.no_shipment_2months,
        s.unused_store,
        s.uncollected_waste_oil,
        s.closed_store,
        s.bad_debt_store
    ]))

    return render_template('dashboard/franchise.html',
                           franchise=franchise,
                           total_stores=total_stores,
                           stores_with_issues=stores_with_issues,
                           stores_with_no_shipment=stores_with_no_shipment,
                           stores_unused=stores_unused,
                           stores_waste_uncollected=stores_waste_uncollected,
                           stores_closed=stores_closed,
                           stores_bad_debt=stores_bad_debt)


@dashboard_bp.route('/jungsung')
@login_required
@jungsung_required
def jungsung():
    """
    Jungsung dashboard - 중상
    Can register ERP data for their assigned stores.
    """
    today = date.today()
    first_of_month = today.replace(day=1)
    jungsung_id = current_user.jungsung_id

    # Assigned stores count
    store_count = Store.query.filter_by(jungsung_id=jungsung_id, is_active=True).count()

    # Today's ERP registrations
    today_registrations = ERPRegistration.query.filter(
        ERPRegistration.jungsung_id == jungsung_id,
        ERPRegistration.registration_date == today
    ).count()

    # This month's ERP registrations
    month_registrations = ERPRegistration.query.filter(
        ERPRegistration.jungsung_id == jungsung_id,
        ERPRegistration.registration_date >= first_of_month
    ).count()

    # Today's totals from category_quantities JSON
    today_regs = ERPRegistration.query.filter(
        ERPRegistration.jungsung_id == jungsung_id,
        ERPRegistration.registration_date == today,
        ERPRegistration.is_return == False
    ).all()
    today_stockin_qty = sum(
        sum(v for k, v in reg.get_category_quantities().items() if k != '폐유')
        for reg in today_regs
    )
    today_waste_qty = sum(
        reg.get_category_quantities().get('폐유', 0)
        for reg in today_regs
    )

    # Recent registrations
    recent_registrations = ERPRegistration.query.filter(
        ERPRegistration.jungsung_id == jungsung_id
    ).order_by(ERPRegistration.registration_date.desc(), ERPRegistration.created_at.desc()).limit(10).all()

    # Assigned stores
    assigned_stores = Store.query.filter_by(jungsung_id=jungsung_id, is_active=True).order_by(Store.name).all()

    return render_template('dashboard/jungsung.html',
                           store_count=store_count,
                           today_registrations=today_registrations,
                           month_registrations=month_registrations,
                           today_stockin_qty=today_stockin_qty,
                           today_waste_qty=today_waste_qty,
                           recent_registrations=recent_registrations,
                           assigned_stores=assigned_stores)
