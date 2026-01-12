from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import enum


class UserRole(enum.Enum):
    ADMIN = 'admin'           # 관리자 - Super admin
    BRANCH = 'branch'         # 지사 - Branch manager
    DRIVER = 'driver'         # 배송기사 - Delivery driver
    FRANCHISE = 'franchise'   # 프랜차이즈 본사 - Franchise HQ
    JUNGSUNG = 'jungsung'     # 중상 - Jungsung manager


class ProductCategory(enum.Enum):
    COOKING_OIL = '식용유'
    FLOUR = '밀가루'
    WASTE_OIL = '폐유'


class Category(db.Model):
    """품목 카테고리"""
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 품목명
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Category {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(20), nullable=False, default=UserRole.DRIVER.value)

    # For branch-specific filtering
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)

    # For franchise-specific filtering
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)

    # For jungsung-specific filtering
    jungsung_id = db.Column(db.Integer, db.ForeignKey('jungsungs.id'), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=True)  # 첫 로그인 시 비밀번호 변경 필요
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    branch = db.relationship('Branch', backref='users', lazy=True)
    franchise = db.relationship('Franchise', backref='users', lazy=True)
    jungsung = db.relationship('Jungsung', backref='users', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == UserRole.ADMIN.value

    def is_branch(self):
        return self.role == UserRole.BRANCH.value

    def is_driver(self):
        return self.role == UserRole.DRIVER.value

    def is_franchise(self):
        return self.role == UserRole.FRANCHISE.value

    def is_jungsung(self):
        return self.role == UserRole.JUNGSUNG.value

    def get_role_display(self):
        role_names = {
            'admin': '관리자',
            'branch': '지사',
            'driver': '배송기사',
            'franchise': '프랜차이즈 본사',
            'jungsung': '중상'
        }
        return role_names.get(self.role, self.role)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Branch(db.Model):
    """거래처 (지사)"""
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # 지사명
    contact_person = db.Column(db.String(100), nullable=True)  # 담당자명
    phone = db.Column(db.String(20), nullable=True)  # 연락처
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to jungsung
    jungsungs = db.relationship('Jungsung', backref='branch', lazy=True)

    def __repr__(self):
        return f'<Branch {self.name}>'


class Jungsung(db.Model):
    """담당중상"""
    __tablename__ = 'jungsungs'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)  # 소속지사
    business_name = db.Column(db.String(100), nullable=False)  # 사업자명
    contact_person = db.Column(db.String(100), nullable=True)  # 담당자명
    phone = db.Column(db.String(20), nullable=True)  # 연락처
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Jungsung {self.business_name}>'


class Supplier(db.Model):
    """제품입고업체"""
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), nullable=False)  # 회사명
    contact_person = db.Column(db.String(100), nullable=True)  # 담당자
    phone = db.Column(db.String(20), nullable=True)  # 연락처
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Supplier {self.company_name}>'


class Franchise(db.Model):
    __tablename__ = 'franchises'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=True)
    address = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to stores
    stores = db.relationship('Store', backref='franchise', lazy=True)

    def __repr__(self):
        return f'<Franchise {self.name}>'


class Store(db.Model):
    """프랜차이즈 매장"""
    __tablename__ = 'stores'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # 매장명
    address = db.Column(db.String(255), nullable=True)  # 주소
    owner_name = db.Column(db.String(100), nullable=True)  # 점주명
    owner_phone = db.Column(db.String(20), nullable=True)  # 점주연락처

    # Belongs to a franchise
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=False)

    # 관리 지사
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)

    # 관리 중상
    jungsung_id = db.Column(db.Integer, db.ForeignKey('jungsungs.id'), nullable=True)

    # Status flags (for red markers)
    # Automatic flags (calculated based on data)
    no_shipment_2months = db.Column(db.Boolean, default=False)  # 2달 이상 출고x
    unused_store = db.Column(db.Boolean, default=False)  # 미사용매장
    uncollected_waste_oil = db.Column(db.Boolean, default=False)  # 폐유미수거매장
    # Manual flags (set by 중상)
    closed_store = db.Column(db.Boolean, default=False)  # 폐업매장
    bad_debt_store = db.Column(db.Boolean, default=False)  # 악성미수매장

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    branch = db.relationship('Branch', backref='stores', lazy=True)
    jungsung = db.relationship('Jungsung', backref='stores', lazy=True)

    def __repr__(self):
        return f'<Store {self.name}>'


class Product(db.Model):
    """제품"""
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # 제품명
    category = db.Column(db.String(20), nullable=False)  # 품목 (식용유, 밀가루, 폐유)
    unit_price = db.Column(db.Integer, nullable=False)  # 단가

    # Optional: 프랜차이즈 선택
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    franchise = db.relationship('Franchise', backref='products', lazy=True)

    def get_category_display(self):
        return self.category

    def __repr__(self):
        return f'<Product {self.name}>'


class Shipment(db.Model):
    """출고 (Outbound shipment batch)"""
    __tablename__ = 'shipments'

    id = db.Column(db.Integer, primary_key=True)
    shipment_date = db.Column(db.Date, nullable=False)  # 출고일
    total_amount = db.Column(db.Integer, default=0)  # 총 합계
    memo = db.Column(db.Text, nullable=True)  # 메모

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    items = db.relationship('ShipmentItem', backref='shipment', lazy=True, cascade='all, delete-orphan')

    def update_total(self):
        self.total_amount = sum(item.total_price for item in self.items)

    def __repr__(self):
        return f'<Shipment {self.id} - {self.shipment_date}>'


class ShipmentItem(db.Model):
    """출고 항목 (Individual shipment line item)"""
    __tablename__ = 'shipment_items'

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.id'), nullable=True)  # Optional batch reference
    shipment_date = db.Column(db.Date, nullable=False)  # 출고일 (per item)

    # 지사
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    # 중상
    jungsung_id = db.Column(db.Integer, db.ForeignKey('jungsungs.id'), nullable=True)
    # 프랜차이즈 (매장)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=True)
    # 제품
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    quantity = db.Column(db.Integer, nullable=False)  # 수량
    unit_price = db.Column(db.Integer, nullable=False)  # 단가
    total_price = db.Column(db.Integer, nullable=False)  # 합계

    # 출고 담당자 (누가 출고했는지 기록)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    branch = db.relationship('Branch', backref='shipment_items', lazy=True)
    jungsung = db.relationship('Jungsung', backref='shipment_items', lazy=True)
    store = db.relationship('Store', backref='shipment_items', lazy=True)
    product = db.relationship('Product', backref='shipment_items', lazy=True)
    creator = db.relationship('User', backref='shipment_items', lazy=True)

    def __repr__(self):
        return f'<ShipmentItem {self.id} - {self.product_id}>'


class StockIn(db.Model):
    """입고 (Inbound stock)"""
    __tablename__ = 'stock_ins'

    id = db.Column(db.Integer, primary_key=True)
    stock_date = db.Column(db.Date, nullable=False)  # 입고일
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)  # 입고업체
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)  # 제품

    # 지사 (어느 지사에 입고되는지)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)

    quantity = db.Column(db.Integer, nullable=False)  # 수량
    unit_price = db.Column(db.Integer, nullable=False)  # 단가
    total_price = db.Column(db.Integer, nullable=False)  # 합계
    memo = db.Column(db.Text, nullable=True)  # 메모

    # 입고 담당자 (누가 입고했는지 기록)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    supplier = db.relationship('Supplier', backref='stock_ins', lazy=True)
    product = db.relationship('Product', backref='stock_ins', lazy=True)
    branch = db.relationship('Branch', backref='stock_ins', lazy=True)
    creator = db.relationship('User', backref='stock_ins', lazy=True)

    def __repr__(self):
        return f'<StockIn {self.id} - {self.stock_date}>'


class ERPRegistration(db.Model):
    """ERP 등록 (중상이 입력하는 입고/폐유 데이터)"""
    __tablename__ = 'erp_registrations'

    id = db.Column(db.Integer, primary_key=True)
    registration_date = db.Column(db.Date, nullable=False)  # 등록일자
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)  # 매장
    jungsung_id = db.Column(db.Integer, db.ForeignKey('jungsungs.id'), nullable=False)  # 담당중상

    stockin_qty = db.Column(db.Integer, default=0)  # 입고 수량 (deprecated - use category_quantities)
    waste_qty = db.Column(db.Integer, default=0)  # 폐유 수량 (deprecated - use category_quantities)
    category_quantities = db.Column(db.Text, nullable=True)  # JSON: {"식용유": 5, "밀가루": 3, "폐유": 2}
    is_return = db.Column(db.Boolean, default=False)  # 반품 여부
    is_completed = db.Column(db.Boolean, default=False)  # 완료 여부

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = db.relationship('Store', backref='erp_registrations', lazy=True)
    jungsung = db.relationship('Jungsung', backref='erp_registrations', lazy=True)
    creator = db.relationship('User', backref='erp_registrations', lazy=True)

    def get_category_quantities(self):
        """Get category quantities as dict"""
        import json
        if self.category_quantities:
            try:
                return json.loads(self.category_quantities)
            except:
                return {}
        return {}

    def set_category_quantities(self, quantities_dict):
        """Set category quantities from dict"""
        import json
        self.category_quantities = json.dumps(quantities_dict, ensure_ascii=False)

    def get_quantity(self, category_name):
        """Get quantity for a specific category"""
        return self.get_category_quantities().get(category_name, 0)

    def __repr__(self):
        return f'<ERPRegistration {self.id} - {self.registration_date}>'


class Payment(db.Model):
    """입금 기록 (Payment records for receivables management)"""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    payment_date = db.Column(db.Date, nullable=False)  # 입금일
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)  # 지사
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)  # 프렌차이즈
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # 품목

    amount = db.Column(db.Integer, nullable=False)  # 입금액
    memo = db.Column(db.Text, nullable=True)  # 메모

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    branch = db.relationship('Branch', backref='payments', lazy=True)
    franchise = db.relationship('Franchise', backref='payments', lazy=True)
    product = db.relationship('Product', backref='payments', lazy=True)
    creator = db.relationship('User', backref='payments', lazy=True)

    def __repr__(self):
        return f'<Payment {self.id} - {self.payment_date}>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
