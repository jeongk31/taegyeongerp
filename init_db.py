"""
Initialize database with sample data for testing
Run with: python init_db.py
"""

from app import create_app, db
from app.models.user import User, UserRole, Category, Branch, Jungsung, Supplier, Franchise, Store, Product

app = create_app()

def init_db():
    with app.app_context():
        # Drop and recreate tables
        db.drop_all()
        db.create_all()

        # Create admin user
        admin = User(
            username='admin',
            name='관리자',
            role=UserRole.ADMIN.value,
            is_active=True,
            must_change_password=False
        )
        admin.set_password('temp123')
        db.session.add(admin)

        # Create default categories
        default_categories = ['식용유', '밀가루', '폐유']
        for cat_name in default_categories:
            category = Category(name=cat_name, is_active=True)
            db.session.add(category)

        # Create a Branch
        branch1 = Branch(
            name='서울지사',
            contact_person='김지사',
            phone='02-1234-5678',
            is_active=True
        )
        db.session.add(branch1)
        db.session.flush()  # Get the ID

        # Create Branch user
        branch_user = User(
            username='branch1',
            name='김지사',
            role=UserRole.BRANCH.value,
            branch_id=branch1.id,
            is_active=True,
            must_change_password=True
        )
        branch_user.set_password('temp123')
        db.session.add(branch_user)

        # Create a Jungsung
        jungsung1 = Jungsung(
            branch_id=branch1.id,
            business_name='중상1',
            contact_person='박중상',
            phone='010-1111-2222',
            is_active=True
        )
        db.session.add(jungsung1)
        db.session.flush()

        # Create Jungsung user
        jungsung_user = User(
            username='jungsung1',
            name='박중상',
            role=UserRole.JUNGSUNG.value,
            branch_id=branch1.id,
            jungsung_id=jungsung1.id,
            is_active=True,
            must_change_password=True
        )
        jungsung_user.set_password('temp123')
        db.session.add(jungsung_user)

        # Create a Supplier
        supplier1 = Supplier(
            company_name='대한식품',
            contact_person='이공급',
            phone='02-9999-8888',
            is_active=True
        )
        db.session.add(supplier1)

        # Create Franchises
        franchise1 = Franchise(
            name='맘스터치',
            code='MT001',
            contact_person='최본사1',
            phone='02-5555-6666',
            is_active=True
        )
        db.session.add(franchise1)
        db.session.flush()

        franchise1_user = User(
            username='momstouch',
            name='맘스터치 담당자',
            role=UserRole.FRANCHISE.value,
            franchise_id=franchise1.id,
            is_active=True,
            must_change_password=True
        )
        franchise1_user.set_password('temp123')
        db.session.add(franchise1_user)

        franchise2 = Franchise(
            name='BHC',
            code='BHC01',
            contact_person='최본사2',
            phone='02-7777-8888',
            is_active=True
        )
        db.session.add(franchise2)
        db.session.flush()

        franchise2_user = User(
            username='bhc',
            name='BHC 담당자',
            role=UserRole.FRANCHISE.value,
            franchise_id=franchise2.id,
            is_active=True,
            must_change_password=True
        )
        franchise2_user.set_password('temp123')
        db.session.add(franchise2_user)

        # Create Products (category + franchise combinations)
        products_data = [
            # 맘스터치 products
            {'name': '맘스터치 식용유', 'category': '식용유', 'unit_price': 15000, 'franchise_id': franchise1.id},
            {'name': '맘스터치 밀가루', 'category': '밀가루', 'unit_price': 8000, 'franchise_id': franchise1.id},
            # BHC products
            {'name': 'BHC 식용유', 'category': '식용유', 'unit_price': 16000, 'franchise_id': franchise2.id},
            {'name': 'BHC 밀가루', 'category': '밀가루', 'unit_price': 8500, 'franchise_id': franchise2.id},
        ]
        for p_data in products_data:
            product = Product(**p_data, is_active=True)
            db.session.add(product)

        # Create Stores
        stores_data = [
            {'name': '맘스터치 강남점', 'franchise_id': franchise1.id, 'branch_id': branch1.id, 'jungsung_id': jungsung1.id, 'address': '서울시 강남구', 'owner_name': '김점주1', 'owner_phone': '010-1234-5678'},
            {'name': '맘스터치 홍대점', 'franchise_id': franchise1.id, 'branch_id': branch1.id, 'jungsung_id': jungsung1.id, 'address': '서울시 마포구', 'owner_name': '이점주2', 'owner_phone': '010-2345-6789'},
            {'name': 'BHC 신촌점', 'franchise_id': franchise2.id, 'branch_id': branch1.id, 'jungsung_id': jungsung1.id, 'address': '서울시 서대문구', 'owner_name': '박점주3', 'owner_phone': '010-3456-7890'},
        ]
        for s_data in stores_data:
            store = Store(**s_data, is_active=True)
            db.session.add(store)

        db.session.commit()

        print("=" * 50)
        print("Database initialized with sample data!")
        print("=" * 50)
        print("\nAccounts (all passwords: temp123):")
        print("-" * 50)
        print("Admin:     admin")
        print("Branch:    branch1")
        print("Jungsung:  jungsung1")
        print("Franchise: momstouch, bhc")
        print("-" * 50)
        print("\nCategories:", ', '.join(default_categories))
        print("Franchises: 맘스터치, BHC")
        print("Products: 4 items")
        print("Stores: 3 stores")
        print("=" * 50)


if __name__ == '__main__':
    init_db()
