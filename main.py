from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import models, schemas
from database import SessionLocal, engine
import os, hashlib, hmac, base64, json
from datetime import datetime
from collections import defaultdict

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
    db.query(models.AdminUser).filter(models.AdminUser.email == "admin@erp.com").delete()
    db.commit()
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

# ─── PRODUCTS ───────────────────────────────────────────
@app.post("/api/products")
def create_product(req: dict, db: Session = Depends(get_db)):
    product = models.Product(
        name=req.get("name"),
        sku=req.get("sku"),
        description=req.get("description"),
        price=float(req.get("price", 0)),
        cost_price=float(req.get("cost_price", 0)) if req.get("cost_price") else None,
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

    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 🔍 Check order items using this product
    order_items = db.query(OrderItem).filter(
        OrderItem.product_id == product_id
    ).all()

    if order_items:
        statuses = [item.order.status for item in order_items]

        active_orders = [s for s in statuses if s not in ["delivered", "cancelled"]]

        if active_orders:
            raise HTTPException(
                status_code=400,
                detail="Product is in active orders (pending/processing). Cannot delete."
            )

    # ✅ Safe to delete
    db.delete(product)
    db.commit()

    return {"message": "Product deleted successfully"}

# ─── DASHBOARD ──────────────────────────────────────────
@app.get("/api/dashboard/stats")
def stats(db: Session = Depends(get_db)):
    customers = db.query(models.Customer).count()
    products = db.query(models.Product).count()
    orders = db.query(models.Order).count()
    pending_orders = db.query(models.Order).filter(models.Order.status == "pending").count()
    delivered_orders = db.query(models.Order).filter(models.Order.status == "delivered").count()
    cancelled_orders = db.query(models.Order).filter(models.Order.status == "cancelled").count()
    
    # Calculate revenue from delivered orders only
    delivered_orders_list = db.query(models.Order).filter(models.Order.status == "delivered").all()
    total_revenue = sum([o.total for o in delivered_orders_list if o.total])
    
    # Low stock count
    low_stock = db.query(models.Product).filter(
        models.Product.stock_quantity <= models.Product.min_stock_level
    ).count()
    
    return {
        "total_orders": orders,
        "pending_orders": pending_orders,
        "total_revenue": round(total_revenue, 2),
        "total_customers": customers,
        "total_products": products,
        "low_stock_alerts": low_stock,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
    }

@app.get("/api/dashboard/monthly-revenue")
def monthly_revenue(db: Session = Depends(get_db)):
    orders = db.query(models.Order).filter(models.Order.status == "delivered").all()
    monthly = defaultdict(lambda: {"revenue": 0, "orders": 0})
    
    for o in orders:
        month_name = o.order_date.strftime("%b")
        monthly[month_name]["revenue"] += o.total
        monthly[month_name]["orders"] += 1
    
    # Order months correctly
    months_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    result = {}
    for m in months_order:
        result[m] = {"revenue": round(monthly[m]["revenue"], 2), "orders": monthly[m]["orders"]}
    
    return result

@app.get("/api/dashboard/recent-orders")
def recent_orders(db: Session = Depends(get_db)):
    orders = db.query(models.Order).order_by(models.Order.id.desc()).limit(5).all()
    result = []
    for o in orders:
        customer = db.query(models.Customer).filter(models.Customer.id == o.customer_id).first()
        result.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer": customer.name if customer else None,
            "status": o.status,
            "total": o.total,
            "order_date": o.order_date.strftime("%Y-%m-%d") if o.order_date else None,
            "customer_id": o.customer_id
        })
    return result

# ─── INVENTORY ──────────────────────────────────────────
@app.get("/api/inventory")
def get_inventory(db: Session = Depends(get_db)):
    products = db.query(models.Product).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "stock_quantity": p.stock_quantity,
            "min_stock_level": p.min_stock_level,
            "price": p.price,
            "status": "low" if p.stock_quantity <= p.min_stock_level else "ok"
        }
        for p in products
    ]

@app.put("/api/inventory/{product_id}")
def update_inventory(product_id: int, req: dict, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.stock_quantity = req.get("quantity", product.stock_quantity)
    db.commit()
    return {"message": "Inventory updated", "product_id": product_id, "quantity": product.stock_quantity}

# ─── ORDERS ─────────────────────────────────────────────
@app.get("/api/orders")
def get_orders(db: Session = Depends(get_db)):
    orders = db.query(models.Order).order_by(models.Order.id.desc()).all()
    result = []
    for o in orders:
        customer = db.query(models.Customer).filter(models.Customer.id == o.customer_id).first()
        items = db.query(models.OrderItem).filter(models.OrderItem.order_id == o.id).all()
        result.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer": customer.name if customer else None,
            "customer_id": o.customer_id,
            "status": o.status,
            "total": o.total,
            "order_date": o.order_date.strftime("%Y-%m-%d") if o.order_date else None,
            "items": [{"product_id": i.product_id, "quantity": i.quantity, "unit_price": i.unit_price} for i in items]
        })
    return result

@app.post("/api/orders")
def create_order(req: dict, db: Session = Depends(get_db)):
    import random
    import string
    
    def generate_order_number():
        prefix = "EPR"
        suffix = ''.join(random.choices(string.digits, k=6))
        return f"{prefix}-{datetime.now().strftime('%Y%m')}-{suffix}"
    
    # Calculate totals
    subtotal = 0
    for item in req.get("items", []):
        subtotal += item["quantity"] * item["unit_price"]
    
    tax = req.get("tax", 18)
    discount = req.get("discount", 0)
    tax_amount = round(subtotal * (tax / 100), 2)
    total = round(subtotal + tax_amount - discount, 2)
    
    order = models.Order(
        order_number=generate_order_number(),
        customer_id=req.get("customer_id"),
        status="pending",
        subtotal=round(subtotal, 2),
        tax=tax_amount,
        discount=discount,
        total=total,
        notes=req.get("notes"),
        delivery_date=req.get("delivery_date") if req.get("delivery_date") else None
    )
    
    db.add(order)
    db.flush()
    
    for item in req.get("items", []):
        order_item = models.OrderItem(
            order_id=order.id,
            product_id=item["product_id"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            total_price=round(item["quantity"] * item["unit_price"], 2)
        )
        db.add(order_item)
        
        # Deduct stock
        product = db.query(models.Product).filter(models.Product.id == item["product_id"]).first()
        if product:
            product.stock_quantity = max(0, product.stock_quantity - item["quantity"])
    
    db.commit()
    db.refresh(order)
    
    return {"message": "Order created", "order_id": order.id}

@app.put("/api/orders/{order_id}/status")
def update_order_status(order_id: int, req: dict, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = req.get("status", order.status)
    db.commit()
    db.refresh(order)
    return {"message": "Order status updated", "order_id": order.id, "status": order.status}

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(order)
    db.commit()
    return {"message": "Order deleted"}

# ─── ADMIN USERS ────────────────────────────────────────
@app.get("/api/admin/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(models.AdminUser).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at
        }
        for u in users
    ]

@app.post("/api/admin/users")
def create_user(req: dict, db: Session = Depends(get_db)):
    existing = db.query(models.AdminUser).filter(models.AdminUser.email == req.get("email")).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    
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
    return {"message": "User created", "id": user.id}

@app.put("/api/admin/users/{user_id}")
def update_user(user_id: int, req: dict, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.name = req.get("name", user.name)
    user.email = req.get("email", user.email)
    user.role = req.get("role", user.role)
    
    if req.get("password"):
        user.hashed_password = hash_password(req.get("password"))
    
    db.commit()
    db.refresh(user)
    return {"message": "User updated"}

@app.patch("/api/admin/users/{user_id}/toggle")
def toggle_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"is_active": user.is_active}

@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}

# ─── TEST ───────────────────────────────────────────────
@app.get("/api/test")
def test():
    return {"status": "ERP running successfully 🚀"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
