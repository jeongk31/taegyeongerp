"""
Safe production database initialization script.
This script creates all required tables WITHOUT dropping existing ones.
It also creates an admin user and minimal required data if they don't exist.
"""
import os
from app import create_app, db
from app.models.user import User, UserRole, Category, Branch, Jungsung, Supplier, Franchise, Store, Product
from datetime import datetime

def init_production_db():
    """Initialize production database safely"""
    app = create_app()

    with app.app_context():
        print("Starting production database initialization...")
        print("=" * 60)

        # Create all tables (only creates missing tables, doesn't drop existing ones)
        print("\n1. Creating missing database tables...")
        db.create_all()
        print("✓ All required tables created (existing tables preserved)")

        # Check if admin user exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("\n2. Creating admin user...")
            admin = User(
                username='admin',
                name='관리자',
                role=UserRole.ADMIN.value,
                is_active=True,
                must_change_password=False
            )
            admin.set_password('temp123')
            db.session.add(admin)
            db.session.commit()
            print(f"✓ Admin user created: username='admin', password='temp123'")
        else:
            print(f"\n2. Admin user already exists (id={admin.id})")

        # Check if categories exist
        categories_created = False
        for cat_name in ['식용유', '밀가루', '폐유']:
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat:
                cat = Category(name=cat_name, is_active=True)
                db.session.add(cat)
                categories_created = True

        if categories_created:
            db.session.commit()
            print("\n3. Created default categories: 식용유, 밀가루, 폐유")
        else:
            print("\n3. Default categories already exist")

        # Check if at least one branch exists
        branch = Branch.query.first()
        if not branch:
            print("\n4. No branches found. Creating sample branch...")
            branch = Branch(
                name='서울지사',
                contact_person='홍길동',
                phone='010-1234-5678',
                is_active=True
            )
            db.session.add(branch)
            db.session.commit()

            # Create a branch user
            branch_user = User(
                username='seoul',
                name='서울지사',
                role=UserRole.BRANCH.value,
                branch_id=branch.id,
                is_active=True,
                must_change_password=True
            )
            branch_user.set_password('temp123')
            db.session.add(branch_user)
            db.session.commit()
            print(f"✓ Created branch: {branch.name} (id={branch.id})")
            print(f"✓ Created branch user: username='seoul', password='temp123'")
        else:
            print(f"\n4. Branches already exist (found {Branch.query.count()} branches)")

        # Check if at least one supplier exists
        supplier = Supplier.query.first()
        if not supplier:
            print("\n5. No suppliers found. Creating sample supplier...")
            supplier = Supplier(
                company_name='대한식품',
                contact_person='김공급',
                phone='010-9876-5432',
                is_active=True
            )
            db.session.add(supplier)
            db.session.commit()
            print(f"✓ Created supplier: {supplier.company_name} (id={supplier.id})")
        else:
            print(f"\n5. Suppliers already exist (found {Supplier.query.count()} suppliers)")

        print("\n" + "=" * 60)
        print("Production database initialization completed successfully!")
        print("\nIMPORTANT: Default credentials")
        print("  Admin: username='admin', password='temp123'")
        print("\nYou should now:")
        print("  1. Change the admin password immediately")
        print("  2. Create your actual branches, franchises, and stores through the admin panel")
        print("=" * 60)

if __name__ == '__main__':
    init_production_db()
