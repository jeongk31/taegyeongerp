-- ============================================================================
-- Supabase Database Initialization Script for 태경바이오 ERP System
-- Run this script in Supabase SQL Editor
-- ============================================================================

-- Drop existing tables if they exist (in reverse dependency order)
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS erp_registrations CASCADE;
DROP TABLE IF EXISTS stock_ins CASCADE;
DROP TABLE IF EXISTS shipment_items CASCADE;
DROP TABLE IF EXISTS shipments CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS stores CASCADE;
DROP TABLE IF EXISTS franchises CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS jungsungs CASCADE;
DROP TABLE IF EXISTS branches CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS categories CASCADE;

-- ============================================================================
-- 1. Categories Table (품목 카테고리)
-- ============================================================================
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 2. Branches Table (지사)
-- ============================================================================
CREATE TABLE branches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 3. Jungsungs Table (중상)
-- ============================================================================
CREATE TABLE jungsungs (
    id SERIAL PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    business_name VARCHAR(100) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 4. Suppliers Table (제품입고업체)
-- ============================================================================
CREATE TABLE suppliers (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(100) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 5. Franchises Table (프랜차이즈 본사)
-- ============================================================================
CREATE TABLE franchises (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(20) UNIQUE,
    address VARCHAR(255),
    phone VARCHAR(20),
    contact_person VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 6. Users Table (사용자)
-- ============================================================================
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'driver',
    branch_id INTEGER REFERENCES branches(id),
    franchise_id INTEGER REFERENCES franchises(id),
    jungsung_id INTEGER REFERENCES jungsungs(id),
    is_active BOOLEAN DEFAULT TRUE,
    must_change_password BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);

-- ============================================================================
-- 7. Stores Table (매장)
-- ============================================================================
CREATE TABLE stores (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    address VARCHAR(255),
    owner_name VARCHAR(100),
    owner_phone VARCHAR(20),
    franchise_id INTEGER NOT NULL REFERENCES franchises(id),
    branch_id INTEGER REFERENCES branches(id),
    jungsung_id INTEGER REFERENCES jungsungs(id),
    no_shipment_2months BOOLEAN DEFAULT FALSE,
    unused_store BOOLEAN DEFAULT FALSE,
    uncollected_waste_oil BOOLEAN DEFAULT FALSE,
    closed_store BOOLEAN DEFAULT FALSE,
    bad_debt_store BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 8. Products Table (제품)
-- ============================================================================
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(20) NOT NULL,
    unit_price INTEGER NOT NULL,
    franchise_id INTEGER REFERENCES franchises(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 9. Shipments Table (출고 배치)
-- ============================================================================
CREATE TABLE shipments (
    id SERIAL PRIMARY KEY,
    shipment_date DATE NOT NULL,
    total_amount INTEGER DEFAULT 0,
    memo TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 10. Shipment Items Table (출고 항목)
-- ============================================================================
CREATE TABLE shipment_items (
    id SERIAL PRIMARY KEY,
    shipment_id INTEGER REFERENCES shipments(id),
    shipment_date DATE NOT NULL,
    branch_id INTEGER REFERENCES branches(id),
    jungsung_id INTEGER REFERENCES jungsungs(id),
    store_id INTEGER REFERENCES stores(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    total_price INTEGER NOT NULL,
    created_by INTEGER REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 11. Stock Ins Table (입고)
-- ============================================================================
CREATE TABLE stock_ins (
    id SERIAL PRIMARY KEY,
    stock_date DATE NOT NULL,
    supplier_id INTEGER REFERENCES suppliers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    branch_id INTEGER REFERENCES branches(id),
    quantity INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    total_price INTEGER NOT NULL,
    memo TEXT,
    created_by INTEGER REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 12. ERP Registrations Table (ERP 등록)
-- ============================================================================
CREATE TABLE erp_registrations (
    id SERIAL PRIMARY KEY,
    registration_date DATE NOT NULL,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    jungsung_id INTEGER NOT NULL REFERENCES jungsungs(id),
    stockin_qty INTEGER DEFAULT 0,
    waste_qty INTEGER DEFAULT 0,
    category_quantities TEXT,
    is_return BOOLEAN DEFAULT FALSE,
    is_completed BOOLEAN DEFAULT FALSE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 13. Payments Table (입금)
-- ============================================================================
CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    payment_date DATE NOT NULL,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    franchise_id INTEGER REFERENCES franchises(id),
    product_id INTEGER REFERENCES products(id),
    amount INTEGER NOT NULL,
    memo TEXT,
    created_by INTEGER REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- Insert Default Data
-- ============================================================================

-- Insert default categories
INSERT INTO categories (name, is_active) VALUES
('식용유', TRUE),
('밀가루', TRUE),
('폐유', TRUE);

-- Insert admin user (password hash for 'temp123')
-- Using Werkzeug's pbkdf2:sha256 format
INSERT INTO users (username, password_hash, name, role, is_active, must_change_password, created_at, updated_at) VALUES
('admin', 'pbkdf2:sha256:260000$xNrtaqfAL3vkorR4$2d86fb064699adb523ac3137b51dc49de6b5084dd7902ee9dd8742265d98513e', '관리자', 'admin', TRUE, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- ============================================================================
-- Create Indexes for Performance
-- ============================================================================

CREATE INDEX idx_shipment_items_date ON shipment_items(shipment_date);
CREATE INDEX idx_shipment_items_store ON shipment_items(store_id);
CREATE INDEX idx_shipment_items_product ON shipment_items(product_id);
CREATE INDEX idx_erp_registrations_date ON erp_registrations(registration_date);
CREATE INDEX idx_erp_registrations_store ON erp_registrations(store_id);
CREATE INDEX idx_stock_ins_date ON stock_ins(stock_date);
CREATE INDEX idx_payments_date ON payments(payment_date);

-- ============================================================================
-- Success Message
-- ============================================================================

-- Note: Run this query to verify all tables were created:
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;

-- Default credentials:
-- Username: admin
-- Password: temp123
--
-- IMPORTANT: Change the admin password immediately after first login!
