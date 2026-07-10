-- ═══════════════════════════════════════════════════════════════════
-- KRISHNA POLY NET — ERP Order Management System
-- MySQL Schema v2.0 — Fully up to date with ORM models
-- ═══════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS epr_orders CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE epr_orders;

-- ─── ADMIN USERS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    email            VARCHAR(255) UNIQUE NOT NULL,
    hashed_password  VARCHAR(255) NOT NULL,
    role             VARCHAR(50) DEFAULT 'subadmin',  -- 'admin' or 'subadmin'
    is_active        BOOLEAN DEFAULT TRUE,
    created_by       INT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES admin_users(id) ON DELETE SET NULL
);

-- ─── CATEGORIES ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    description  TEXT
);

-- ─── CUSTOMERS ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255) UNIQUE,
    phone       VARCHAR(50),
    address     TEXT,
    city        VARCHAR(100),
    country     VARCHAR(100) DEFAULT 'India',
    gst_number  VARCHAR(20),                    -- Indian GST: 22AAAAA0000A1Z5
    is_deleted  BOOLEAN DEFAULT FALSE,          -- Soft delete
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ─── PRODUCTS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    sku              VARCHAR(100) UNIQUE NOT NULL,
    description      TEXT,
    price            DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    cost_price       DECIMAL(12,2),
    stock_quantity   INT DEFAULT 0,
    min_stock_level  INT DEFAULT 10,
    category_id      INT,
    unit             VARCHAR(50) DEFAULT 'pcs',
    product_type     VARCHAR(20) NOT NULL DEFAULT 'FINISHED_GOOD', -- RAW_MATERIAL | FINISHED_GOOD
    is_deleted       BOOLEAN DEFAULT FALSE,     -- Soft delete
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
);

-- ─── PRODUCT MATERIALS (Bill of Materials) ───────────────────────
-- Raw materials / components required to manufacture each product.
CREATE TABLE IF NOT EXISTS product_materials (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    parent_product_id   INT NOT NULL,
    material_name       VARCHAR(255) NOT NULL,
    unit                VARCHAR(50) DEFAULT 'pcs',
    quantity_per_unit   FLOAT DEFAULT 1.0,      -- Material qty needed per 1 finished product
    stock_quantity      FLOAT DEFAULT 0,         -- Available raw material stock
    min_stock_level     FLOAT DEFAULT 0,
    FOREIGN KEY (parent_product_id) REFERENCES products(id) ON DELETE CASCADE
);

-- ─── ORDERS ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    order_number        VARCHAR(50) UNIQUE NOT NULL,
    customer_id         INT NOT NULL,
    status              VARCHAR(50) DEFAULT 'pending',
                        -- Values: pending, confirmed, processing, shipped, delivered, cancelled
    subtotal            DECIMAL(12,2) DEFAULT 0,
    total               DECIMAL(12,2) DEFAULT 0,
    description         TEXT,
    priority            VARCHAR(50) DEFAULT 'medium',   -- low, medium, high
    inventory_deducted  BOOLEAN DEFAULT FALSE,  -- TRUE once stock is deducted (on delivery)
    order_date          DATETIME DEFAULT CURRENT_TIMESTAMP,
    delivery_date       DATE,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
);

-- ─── ORDER ITEMS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    order_id     INT NOT NULL,
    product_id   INT NOT NULL,
    quantity     INT NOT NULL,
    unit_price   DECIMAL(12,2) NOT NULL,
    total_price  DECIMAL(12,2) NOT NULL,
    unit         VARCHAR(50) DEFAULT 'pcs',
    FOREIGN KEY (order_id)   REFERENCES orders(id)   ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

-- ─── ORDER ITEM MATERIALS ─────────────────────────────────────────
-- Tracks which materials are consumed by each order item.
CREATE TABLE IF NOT EXISTS order_item_materials (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    order_item_id     INT NOT NULL,
    material_id       INT NOT NULL,
    quantity_per_unit FLOAT DEFAULT 1.0,
    FOREIGN KEY (order_item_id) REFERENCES order_items(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id)   REFERENCES product_materials(id) ON DELETE CASCADE
);

-- ─── MATERIAL MASTER (Standalone) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS materials (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    unit VARCHAR(50) DEFAULT 'pcs',
    stock_quantity FLOAT DEFAULT 0.0,
    min_stock_level FLOAT DEFAULT 10.0,
    rate DECIMAL(12, 2) DEFAULT 0.00,
    status VARCHAR(50) DEFAULT 'ok',
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ─── ORDER MATERIALS (Make-to-Order Dynamic BOM) ──────────────────
CREATE TABLE IF NOT EXISTS order_materials (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    material_id INT NOT NULL,
    required_qty FLOAT NOT NULL DEFAULT 0.0,
    used_qty FLOAT DEFAULT 0.0,
    unit VARCHAR(50) DEFAULT 'pcs',
    rate DECIMAL(12, 2) DEFAULT 0.00,
    amount DECIMAL(12, 2) DEFAULT 0.00,
    remarks TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE RESTRICT
);

-- ─── ORDER EXTRA ITEMS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_extra_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    item_name VARCHAR(255) NOT NULL,
    quantity FLOAT NOT NULL DEFAULT 1.0,
    price DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);



-- ═══════════════════════════════════════════════════════════════════
-- SEED DATA
-- ═══════════════════════════════════════════════════════════════════

-- Default admin: admin@erp.com / admin123
-- NOTE: The application auto-creates this on startup via create_default_admin().
-- Insert here only if seeding a fresh DB without running the app first.
-- INSERT INTO admin_users (name, email, hashed_password, role)
-- VALUES ('Admin', 'admin@erp.com', '<bcrypt_hash_of_admin123>', 'admin');

INSERT INTO categories (name, description) VALUES
('Electronics',   'Electronic devices and components'),
('Furniture',     'Office and home furniture'),
('Stationery',    'Office supplies and stationery'),
('Raw Materials', 'Industrial raw materials');

INSERT INTO customers (name, email, phone, address, city, country) VALUES
('Rahul Mehta',  'rahul.mehta@example.com',  '9876543210', '12 MG Road',       'Mumbai',    'India'),
('Priya Sharma', 'priya.sharma@example.com', '9123456789', '45 Nehru Street',   'Delhi',     'India'),
('Vijay Patel',  'vijay.patel@example.com',  '9988776655', '7 Ashok Nagar',     'Ahmedabad', 'India'),
('Sunita Rao',   'sunita.rao@example.com',   '9011223344', '23 Brigade Road',   'Bangalore', 'India'),
('Arun Kumar',   'arun.kumar@example.com',   '9345678901', '89 Anna Salai',     'Chennai',   'India');

INSERT INTO products (name, sku, description, price, cost_price, stock_quantity, min_stock_level, category_id, unit) VALUES
('Laptop Pro X1',      'ELEC-LP-001', '15.6 inch Full HD laptop',                65000.00, 52000.00, 25,  5,  1, 'pcs'),
('Office Chair Ergo',  'FURN-OC-001', 'Ergonomic office chair with lumbar support', 12500.00,  9000.00, 40,  8,  2, 'pcs'),
('A4 Paper Ream',      'STAT-AP-001', '500 sheets A4 80gsm paper',                  350.00,   250.00, 200, 50,  3, 'ream'),
('Steel Rod 6mm',      'RAW-SR-001',  '6mm mild steel rod 12ft length',              850.00,   650.00,   7, 10,  4, 'pcs'),
('Wireless Mouse',     'ELEC-WM-001', 'USB wireless optical mouse',                 1200.00,   800.00,  60, 15,  1, 'pcs'),
('Standing Desk',      'FURN-SD-001', 'Height-adjustable standing desk',           28000.00, 21000.00,  15,  3,  2, 'pcs'),
('Ballpoint Pens Box', 'STAT-BP-001', 'Box of 50 blue ballpoint pens',              180.00,   120.00,   3, 20,  3, 'box');

INSERT INTO orders (order_number, customer_id, status, subtotal, total, priority, inventory_deducted, delivery_date) VALUES
('ORD-202401-001', 1, 'delivered',  66200.00,  66200.00, 'high',   TRUE,  '2024-01-15'),
('ORD-202402-002', 2, 'shipped',    12500.00,  12500.00, 'medium', FALSE, '2024-02-20'),
('ORD-202403-003', 3, 'processing',  1700.00,   1700.00, 'low',    FALSE, '2024-03-10'),
('ORD-202404-004', 4, 'pending',    29200.00,  29200.00, 'medium', FALSE, '2024-04-05'),
('ORD-202405-005', 5, 'confirmed',   5350.00,   5350.00, 'low',    FALSE, '2024-05-01');

INSERT INTO order_items (order_id, product_id, quantity, unit_price, total_price, unit) VALUES
(1, 1, 1, 65000.00, 65000.00, 'pcs'),
(1, 5, 1,  1200.00,  1200.00, 'pcs'),
(2, 2, 1, 12500.00, 12500.00, 'pcs'),
(3, 3, 4,   350.00,  1400.00, 'ream'),
(4, 6, 1, 28000.00, 28000.00, 'pcs'),
(4, 5, 1,  1200.00,  1200.00, 'pcs'),
(5, 7, 5,   180.00,   900.00, 'box'),
(5, 5, 3,  1200.00,  3600.00, 'pcs'),
(5, 3, 2,   350.00,   700.00, 'ream');
