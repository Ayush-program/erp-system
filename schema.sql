-- ═══════════════════════════════════════════════════════
-- EPR ORDER MANAGEMENT SYSTEM — MySQL Schema
-- ═══════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS epr_orders CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE epr_orders;

-- CATEGORIES
CREATE TABLE IF NOT EXISTS categories (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CUSTOMERS
CREATE TABLE IF NOT EXISTS customers (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255) UNIQUE NOT NULL,
    phone       VARCHAR(50),
    address     TEXT,
    city        VARCHAR(100),
    country     VARCHAR(100) DEFAULT 'India',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- PRODUCTS
CREATE TABLE IF NOT EXISTS products (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    sku              VARCHAR(100) UNIQUE NOT NULL,
    description      TEXT,
    price            DECIMAL(10,2) NOT NULL,
    cost_price       DECIMAL(10,2),
    stock_quantity   INT DEFAULT 0,
    min_stock_level  INT DEFAULT 10,
    category_id      INT,
    unit             VARCHAR(50) DEFAULT 'pcs',
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
);

-- ORDERS
CREATE TABLE IF NOT EXISTS orders (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    order_number    VARCHAR(50) UNIQUE NOT NULL,
    customer_id     INT NOT NULL,
    status          ENUM('pending','confirmed','processing','shipped','delivered','cancelled') DEFAULT 'pending',
    subtotal        DECIMAL(12,2) DEFAULT 0,
    tax             DECIMAL(12,2) DEFAULT 0,
    discount        DECIMAL(12,2) DEFAULT 0,
    total           DECIMAL(12,2) DEFAULT 0,
    notes           TEXT,
    order_date      DATETIME DEFAULT CURRENT_TIMESTAMP,
    delivery_date   DATE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
);

-- ORDER ITEMS
CREATE TABLE IF NOT EXISTS order_items (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    order_id     INT NOT NULL,
    product_id   INT NOT NULL,
    quantity     INT NOT NULL,
    unit_price   DECIMAL(10,2) NOT NULL,
    total_price  DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id)   REFERENCES orders(id)   ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

-- ═══════════════════════════════════════════════════════
-- SEED DATA
-- ═══════════════════════════════════════════════════════

INSERT INTO categories (name, description) VALUES
('Electronics', 'Electronic devices and components'),
('Furniture', 'Office and home furniture'),
('Stationery', 'Office supplies and stationery'),
('Raw Materials', 'Industrial raw materials');

INSERT INTO customers (name, email, phone, address, city, country) VALUES
('Rahul Mehta', 'rahul.mehta@example.com', '+91-9876543210', '12 MG Road', 'Mumbai', 'India'),
('Priya Sharma', 'priya.sharma@example.com', '+91-9123456789', '45 Nehru Street', 'Delhi', 'India'),
('Vijay Patel', 'vijay.patel@example.com', '+91-9988776655', '7 Ashok Nagar', 'Ahmedabad', 'India'),
('Sunita Rao', 'sunita.rao@example.com', '+91-9011223344', '23 Brigade Road', 'Bangalore', 'India'),
('Arun Kumar', 'arun.kumar@example.com', '+91-9345678901', '89 Anna Salai', 'Chennai', 'India');

INSERT INTO products (name, sku, description, price, cost_price, stock_quantity, min_stock_level, category_id, unit) VALUES
('Laptop Pro X1', 'ELEC-LP-001', '15.6 inch Full HD laptop', 65000.00, 52000.00, 25, 5, 1, 'pcs'),
('Office Chair Ergo', 'FURN-OC-001', 'Ergonomic office chair with lumbar support', 12500.00, 9000.00, 40, 8, 2, 'pcs'),
('A4 Paper Ream', 'STAT-AP-001', '500 sheets A4 80gsm paper', 350.00, 250.00, 200, 50, 3, 'ream'),
('Steel Rod 6mm', 'RAW-SR-001', '6mm mild steel rod 12ft length', 850.00, 650.00, 7, 10, 4, 'pcs'),
('Wireless Mouse', 'ELEC-WM-001', 'USB wireless optical mouse', 1200.00, 800.00, 60, 15, 1, 'pcs'),
('Standing Desk', 'FURN-SD-001', 'Height-adjustable standing desk', 28000.00, 21000.00, 15, 3, 2, 'pcs'),
('Ballpoint Pens Box', 'STAT-BP-001', 'Box of 50 blue ballpoint pens', 180.00, 120.00, 3, 20, 3, 'box');

-- Sample Orders
INSERT INTO orders (order_number, customer_id, status, subtotal, tax, discount, total, notes, delivery_date) VALUES
('EPR-202401-001', 1, 'delivered', 66200.00, 11916.00, 2000.00, 76116.00, 'Priority delivery', '2024-01-15'),
('EPR-202402-002', 2, 'shipped', 12500.00, 2250.00, 0.00, 14750.00, NULL, '2024-02-20'),
('EPR-202403-003', 3, 'processing', 1700.00, 306.00, 0.00, 2006.00, 'Bulk order discount applied', '2024-03-10'),
('EPR-202404-004', 4, 'pending', 29200.00, 5256.00, 1000.00, 33456.00, NULL, '2024-04-05'),
('EPR-202405-005', 5, 'confirmed', 5350.00, 963.00, 0.00, 6313.00, NULL, '2024-05-01');

INSERT INTO order_items (order_id, product_id, quantity, unit_price, total_price) VALUES
(1, 1, 1, 65000.00, 65000.00),
(1, 5, 1, 1200.00, 1200.00),
(2, 2, 1, 12500.00, 12500.00),
(3, 3, 4, 350.00, 1400.00),
(3, 6, 0, 0, 0),
(4, 6, 1, 28000.00, 28000.00),
(4, 5, 1, 1200.00, 1200.00),
(5, 1, 0, 0, 0),
(5, 7, 5, 180.00, 900.00),
(5, 5, 3, 1200.00, 3600.00),
(5, 3, 2, 350.00, 700.00);
