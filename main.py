from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import models, schemas
from database import SessionLocal, engine
import os, hashlib, hmac, base64, json
from datetime import datetime

# ─── INIT DB ─────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)

# ─── SECURITY ────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "change-this")

def hash_password(password: str):
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def make_token(user_id: int, role: str):
    payload = json.dumps({"id": user_id, "role": role})
    token = base64.b64encode(payload.encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"

# ─── DB ──────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── CREATE DEFAULT ADMIN ────────────────────────────────
def create_default_admin():
    db = SessionLocal()

    # DELETE OLD USER (important)
    db.query(models.AdminUser).filter(models.AdminUser.email == "admin@erp.com").delete()
    db.commit()

    # CREATE NEW USER
    admin = models.AdminUser(
        name="Admin",
        email="admin@erp.com",
        hashed_password=hash_password("admin123"),
        role="admin",
        is_active=True
    )

    db.add(admin)
    db.commit()
    db.close()

    print("✅ Admin reset: admin@erp.com / admin123")

create_default_admin()

# ─── APP ────────────────────────────────────────────────
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── FRONTEND ───────────────────────────────────────────
@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))

@app.get("/login")
def login_page():
    return FileResponse(os.path.join(BASE_DIR, "login.html"))

# ─── LOGIN ──────────────────────────────────────────────
@app.post("/api/auth/login")
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.email == req.email).first()

    if not user or user.hashed_password != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "access_token": make_token(user.id, user.role),
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active
        }
    }

# ─── CUSTOMERS ──────────────────────────────────────────
@app.post("/api/customers")
def create_customer(req: dict, db: Session = Depends(get_db)):
    customer = models.Customer(
        name=req.get("name"),
        email=req.get("email"),
        phone=req.get("phone"),
        address=req.get("address"),
        city=req.get("city"),
        country=req.get("country", "India")
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer

@app.get("/api/customers")
def get_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).all()

# ─── PRODUCTS ───────────────────────────────────────────
@app.post("/api/products")
def create_product(req: dict, db: Session = Depends(get_db)):
    product = models.Product(
        name=req.get("name"),
        sku=req.get("sku"),
        description=req.get("description"),
        price=float(req.get("price", 0)),
        cost_price=float(req.get("cost_price", 0)),
        stock_quantity=int(req.get("stock_quantity", 0)),
        min_stock_level=int(req.get("min_stock_level", 10)),
        category_id=req.get("category_id"),
        unit=req.get("unit", "pcs")
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product

@app.get("/api/products")
def get_products(db: Session = Depends(get_db)):
    return db.query(models.Product).all()

# ─── DASHBOARD ──────────────────────────────────────────
@app.get("/api/dashboard/stats")
def stats(db: Session = Depends(get_db)):

    customers = db.query(models.Customer).count()
    products = db.query(models.Product).count()
    orders = db.query(models.Order).count()

    revenue = db.query(models.Order).with_entities(models.Order.total).all()
    total_revenue = sum([r[0] for r in revenue if r[0]])

    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "revenue": total_revenue
    }

@app.get("/api/dashboard/monthly-revenue")
def monthly_revenue(db: Session = Depends(get_db)):

    orders = db.query(models.Order).all()

    monthly = {}

    for o in orders:
        month = o.order_date.strftime("%b")
        monthly[month] = monthly.get(month, 0) + (o.total or 0)

    result = []
    for m, v in monthly.items():
        result.append({"month": m, "revenue": v})

    return result

@app.get("/api/dashboard/monthly-revenue")
def monthly_revenue(db: Session = Depends(get_db)):

    orders = db.query(models.Order).all()

    monthly = {}

    for o in orders:
        month = o.order_date.strftime("%b")
        monthly[month] = monthly.get(month, 0) + (o.total or 0)

    result = []
    for m, v in monthly.items():
        result.append({"month": m, "revenue": v})

    return result

@app.get("/api/inventory")
def get_inventory(db: Session = Depends(get_db)):
    products = db.query(models.Product).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "stock": p.stock_quantity,
            "min_stock": p.min_stock_level,
            "unit": p.unit
        }
        for p in products
    ]

@app.get("/api/admin/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(models.AdminUser).all()

    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active
        }
        for u in users
    ]

@app.post("/api/admin/users")
def create_user(req: dict, db: Session = Depends(get_db)):
    user = models.AdminUser(
        name=req.get("name"),
        email=req.get("email"),
        hashed_password=hash_password(req.get("password")),
        role=req.get("role", "subadmin"),
        is_active=True
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "User created"}

@app.get("/api/orders")
def get_orders(db: Session = Depends(get_db)):
    orders = db.query(models.Order).all()

    result = []
    for o in orders:
        result.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer": o.customer.name if o.customer else None,
            "status": o.status,
            "total": o.total,
            "date": o.order_date
        })

    return result

@app.post("/api/orders")
def create_order(req: dict, db: Session = Depends(get_db)):

    # generate order number
    order_number = f"ORD-{int(datetime.utcnow().timestamp())}"

    order = models.Order(
        order_number=order_number,
        customer_id=req.get("customer_id"),
        status="pending",
        subtotal=0,
        tax=0,
        discount=0,
        total=0
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    total = 0

    # add items
    for item in req.get("items", []):
        product = db.query(models.Product).filter(models.Product.id == item["product_id"]).first()

        if not product:
            continue

        quantity = int(item["quantity"])
        price = product.price
        item_total = quantity * price

        order_item = models.OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=price,
            total_price=item_total
        )

        total += item_total

        # update stock
        product.stock_quantity -= quantity

        db.add(order_item)

    order.total = total

    db.commit()

    return {"message": "Order created", "order_id": order.id}

#delete customer and update

@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, req: dict, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    customer.name = req.get("name", customer.name)
    customer.email = req.get("email", customer.email)
    customer.phone = req.get("phone", customer.phone)
    customer.address = req.get("address", customer.address)
    customer.city = req.get("city", customer.city)

    db.commit()
    db.refresh(customer)

    return customer


@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    db.delete(customer)
    db.commit()

    return {"message": "Customer deleted"}

#order update and delete
@app.put("/api/products/{product_id}")
def update_product(product_id: int, req: dict, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.name = req.get("name", product.name)
    product.price = float(req.get("price", product.price))
    product.stock_quantity = int(req.get("stock_quantity", product.stock_quantity))

    db.commit()
    db.refresh(product)

    return product


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    db.delete(product)
    db.commit()

    return {"message": "Product deleted"}

#update status

@app.put("/api/orders/{order_id}/status")
def update_order_status(order_id: int, req: dict, db: Session = Depends(get_db)):

    order = db.query(models.Order).filter(models.Order.id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # update status
    order.status = req.get("status", order.status)

    db.commit()
    db.refresh(order)

    return {
        "message": "Order status updated",
        "order_id": order.id,
        "status": order.status
    }


    
# ─── TEST ───────────────────────────────────────────────
@app.get("/api/test")
def test():
    return {"status": "ERP running successfully 🚀"}
