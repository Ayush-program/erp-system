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

> [!NOTE]
> The project root is nested: `erp-system-main-2/erp-system-main/erp-system-main/`
> Always use the full path when navigating in the terminal.

### 1. MySQL Setup

```sql
-- Run schema.sql in your MySQL server
mysql -u root -p < backend/schema.sql
```

### 2. Backend Setup

```powershell
# Navigate to the correct backend directory (PowerShell / Windows)
cd D:\erp-system-main-2\erp-system-main\erp-system-main\backend

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
$env:DATABASE_URL = "mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/epr_orders"
$env:SECRET_KEY    = "your-very-secret-key-here"
$env:ALLOWED_ORIGINS = "http://localhost:8000,http://localhost:3000"

# Start the server
uvicorn main:app --reload --port 8000
```

```bash
# Linux / macOS
cd /path/to/erp-system-main-2/erp-system-main/erp-system-main/backend

export DATABASE_URL="mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/epr_orders"
export SECRET_KEY="your-very-secret-key-here"
export ALLOWED_ORIGINS="http://localhost:8000,http://localhost:3000"

uvicorn main:app --reload --port 8000
```

### 3. Frontend

Simply open `http://localhost:8000` in your browser after starting the backend.
Default credentials: **admin@erp.com** / **admin123**

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
