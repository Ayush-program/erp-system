# EPR Order Management System

A full-featured Enterprise Planning & Resource (Order) Management System built with **FastAPI + MySQL + Vanilla JS Dashboard**.

---

## 🗂 Project Structure

```
epr-system/
├── backend/
│   ├── main.py          # FastAPI app & routes
│   ├── models.py        # SQLAlchemy ORM models
│   ├── schemas.py       # Pydantic request/response schemas
│   ├── crud.py          # Database operations
│   ├── database.py      # DB connection (MySQL)
│   ├── schema.sql       # MySQL schema + seed data
│   └── requirements.txt
└── frontend/
    └── dashboard.html   # Full dashboard UI (open in browser)
```

---

## ⚡ Setup Instructions

### 1. MySQL Setup

```sql
-- Run schema.sql in your MySQL server
mysql -u root -p < backend/schema.sql
```

### 2. Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Configure your DB URL in database.py (or set env variable)
export DATABASE_URL="mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/epr_orders"

# Start the server
uvicorn main:app --reload --port 8000
```

### 3. Frontend

Simply open `frontend/dashboard.html` in your browser.

> If your API runs on a different host/port, update the `API` constant at the top of `dashboard.html`.

---

## 🚀 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/stats` | Summary stats |
| GET | `/api/dashboard/monthly-revenue` | Monthly chart data |
| GET | `/api/dashboard/recent-orders` | Last 10 orders |
| GET/POST | `/api/orders` | List / Create orders |
| GET/PUT/DELETE | `/api/orders/{id}` | Order detail/update/delete |
| PUT | `/api/orders/{id}/status` | Update order status |
| GET/POST | `/api/customers` | List / Create customers |
| GET/PUT/DELETE | `/api/customers/{id}` | Customer CRUD |
| GET/POST | `/api/products` | List / Create products |
| GET/PUT/DELETE | `/api/products/{id}` | Product CRUD |
| GET | `/api/inventory` | Stock levels |
| PUT | `/api/inventory/{id}` | Update stock quantity |

📖 **Auto Docs**: Visit `http://localhost:8000/docs` for Swagger UI.

---

## 🎯 Features

- **Dashboard** — KPI stats, revenue bar chart, order status donut, recent orders
- **Orders** — Create with multiple line items, auto tax/discount calculation, status tracking
- **Customers** — Full CRUD with search
- **Products** — Full CRUD with SKU, pricing, stock levels
- **Inventory** — Stock tracking with low-stock alerts and progress bars
- **Auto stock deduction** — Stock reduces on order creation

---

## 🔧 Tech Stack

- **Backend**: FastAPI, SQLAlchemy, PyMySQL, Pydantic
- **Database**: MySQL 8+
- **Frontend**: HTML/CSS/JS, Chart.js (no framework needed)
