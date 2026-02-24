"""
Database update script to add new ERPRegistration table and jungsung_id column to users.
Run this script once to update the existing database.
"""
from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    # Check if jungsung_id column exists in users table
    try:
        db.session.execute(text("SELECT jungsung_id FROM users LIMIT 1"))
        print("jungsung_id column already exists in users table")
    except:
        print("Adding jungsung_id column to users table...")
        db.session.execute(text("ALTER TABLE users ADD COLUMN jungsung_id INTEGER REFERENCES jungsungs(id)"))
        db.session.commit()
        print("jungsung_id column added successfully")

    # Check if erp_registrations table exists
    try:
        db.session.execute(text("SELECT 1 FROM erp_registrations LIMIT 1"))
        print("erp_registrations table already exists")
    except:
        print("Creating erp_registrations table...")
        db.session.execute(text("""
            CREATE TABLE erp_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration_date DATE NOT NULL,
                store_id INTEGER NOT NULL REFERENCES stores(id),
                jungsung_id INTEGER NOT NULL REFERENCES jungsungs(id),
                category_quantities TEXT,
                is_return BOOLEAN DEFAULT 0,
                is_completed BOOLEAN DEFAULT 0,
                created_by INTEGER REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
        print("erp_registrations table created successfully")

    # Add category_quantities column if it doesn't exist
    try:
        db.session.execute(text("SELECT category_quantities FROM erp_registrations LIMIT 1"))
        print("category_quantities column already exists in erp_registrations table")
    except:
        db.session.rollback()
        print("Adding category_quantities column to erp_registrations table...")
        db.session.execute(text("ALTER TABLE erp_registrations ADD COLUMN category_quantities TEXT"))
        db.session.commit()
        print("category_quantities column added successfully")

    # Check if bad_debt_store column exists in stores table
    try:
        db.session.execute(text("SELECT bad_debt_store FROM stores LIMIT 1"))
        print("bad_debt_store column already exists in stores table")
    except:
        print("Adding bad_debt_store column to stores table...")
        db.session.execute(text("ALTER TABLE stores ADD COLUMN bad_debt_store BOOLEAN DEFAULT 0"))
        db.session.commit()
        print("bad_debt_store column added successfully")

    # Check if external_purchase_store column exists in stores table
    try:
        db.session.execute(text("SELECT external_purchase_store FROM stores LIMIT 1"))
        print("external_purchase_store column already exists in stores table")
    except:
        print("Adding external_purchase_store column to stores table...")
        db.session.execute(text("ALTER TABLE stores ADD COLUMN external_purchase_store BOOLEAN DEFAULT 0"))
        db.session.commit()
        print("external_purchase_store column added successfully")

    # Check if branch_id column exists in stock_ins table
    try:
        db.session.execute(text("SELECT branch_id FROM stock_ins LIMIT 1"))
        print("branch_id column already exists in stock_ins table")
    except:
        print("Adding branch_id column to stock_ins table...")
        db.session.execute(text("ALTER TABLE stock_ins ADD COLUMN branch_id INTEGER REFERENCES branches(id)"))
        db.session.commit()
        print("branch_id column added successfully to stock_ins table")

    # Check if must_change_password column exists in users table
    try:
        db.session.execute(text("SELECT must_change_password FROM users LIMIT 1"))
        print("must_change_password column already exists in users table")
    except:
        print("Adding must_change_password column to users table...")
        db.session.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 1"))
        db.session.commit()
        # Set admin users to not require password change
        db.session.execute(text("UPDATE users SET must_change_password = 0 WHERE role = 'admin'"))
        db.session.commit()
        print("must_change_password column added successfully")

    # Check if payments table exists
    try:
        db.session.execute(text("SELECT 1 FROM payments LIMIT 1"))
        print("payments table already exists")
    except:
        print("Creating payments table...")
        db.session.execute(text("""
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_date DATE NOT NULL,
                branch_id INTEGER NOT NULL REFERENCES branches(id),
                franchise_id INTEGER REFERENCES franchises(id),
                product_id INTEGER REFERENCES products(id),
                amount INTEGER NOT NULL,
                memo TEXT,
                created_by INTEGER REFERENCES users(id),
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
        print("payments table created successfully")

    # Check if franchise_categories table exists
    try:
        db.session.execute(text("SELECT 1 FROM franchise_categories LIMIT 1"))
        print("franchise_categories table already exists")
    except:
        db.session.rollback()
        print("Creating franchise_categories table...")
        db.session.execute(text("""
            CREATE TABLE franchise_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                franchise_id INTEGER NOT NULL REFERENCES franchises(id) ON DELETE CASCADE,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(franchise_id, category_id)
            )
        """))
        db.session.commit()
        print("franchise_categories table created successfully")

        # Populate from existing products data
        print("Populating franchise_categories from existing products...")
        db.session.execute(text("""
            INSERT OR IGNORE INTO franchise_categories (franchise_id, category_id)
            SELECT DISTINCT p.franchise_id, c.id
            FROM products p
            JOIN categories c ON c.name = p.category
            WHERE p.franchise_id IS NOT NULL
              AND p.is_active = 1
        """))
        db.session.commit()
        print("franchise_categories populated from existing products")

    print("\nDatabase update completed!")
