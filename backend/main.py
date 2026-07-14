from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
import models, schemas, crud
from database import SessionLocal, engine
import os, hashlib
from datetime import datetime, date, timedelta
from collections import defaultdict
from models import Product, OrderItem, Customer, Order
from sqlalchemy import text, inspect, func

# ─── JWT + BCRYPT ────────────────────────────────────────
from jose import JWTError, jwt
import bcrypt as _bcrypt

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    """Verify password against a bcrypt hash or legacy SHA256 hash."""
    # Support legacy SHA256 hashes — auto-detected by hash format
    import hashlib
    if not hashed.startswith("$2b$") and not hashed.startswith("$2a$"):
        legacy_hash = hashlib.sha256((plain + SECRET_KEY).encode()).hexdigest()
        return hashed == legacy_hash
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def make_token(user_id: int, role: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# ─── INIT DB ─────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)

def ensure_mto_schema():
    """One-time migration: add product_type column to existing products tables.
    SQLAlchemy create_all() does not ALTER existing tables, so we handle it here.
    Safe to call on every startup — no-op if column already exists.
    """
    try:
        product_cols = {col["name"] for col in inspect(engine).get_columns("products")}
        if "product_type" not in product_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE products ADD COLUMN product_type VARCHAR(20) NOT NULL DEFAULT 'FINISHED_GOOD'"
                ))
            print("[OK] MTO migration: product_type column added to products")
    except Exception as exc:
        print(f"[WARN] MTO migration check skipped: {exc}")

ensure_mto_schema()

def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def parse_manufacture_qty(value):
    qty = to_float(value)
    if qty <= 0 or not qty.is_integer():
        raise HTTPException(status_code=400, detail="Manufacturing quantity must be a positive whole number")
    return int(qty)

def material_qty_per_unit(value, default=1.0):
    qty = to_float(value, default)
    return qty if qty > 0 else default

def material_response(material):
    if material.material:
        return {
            "id": material.id,
            "material_name": material.material.name,
            "unit": material.material.unit or "pcs",
            "quantity_per_unit": material_qty_per_unit(material.quantity_per_unit),
            "stock_quantity": to_float(material.material.stock_quantity),
            "min_stock_level": to_float(material.material.min_stock_level),
            "status": material.material.status or "ok"
        }
    return {
        "id": material.id,
        "material_name": material.material_name,
        "unit": material.unit or "pcs",
        "quantity_per_unit": material_qty_per_unit(material.quantity_per_unit),
        "stock_quantity": to_float(material.stock_quantity),
        "min_stock_level": to_float(material.min_stock_level),
        "status": "low" if to_float(material.stock_quantity) <= to_float(material.min_stock_level) else "ok"
    }

def manufacture_requirements(product_id: int, qty: int, db: Session):
    materials = db.query(models.ProductMaterial).filter(
        models.ProductMaterial.parent_product_id == product_id
    ).all()
    rows = []
    can_manufacture = True
    for material in materials:
        per_unit = material_qty_per_unit(material.quantity_per_unit)
        needed = round(per_unit * qty, 4)
        available = to_float(material.material.stock_quantity if material.material else material.stock_quantity)
        sufficient = available >= needed
        if not sufficient:
            can_manufacture = False
        rows.append({
            "id": material.id,
            "material_name": material.material.name if material.material else material.material_name,
            "unit": (material.material.unit if material.material else material.unit) or "pcs",
            "quantity_per_unit": per_unit,
            "needed": needed,
            "available": available,
            "sufficient": sufficient,
            "shortage": round(max(0, needed - available), 4)
        })
    return rows, can_manufacture

def apply_order_inventory(order, db: Session, deduct: bool):
    items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
    for item in items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if not product:
            continue
        quantity = int(item.quantity or 0)

        if item.materials:
            for item_mat in item.materials:
                material = db.query(models.ProductMaterial).filter(models.ProductMaterial.id == item_mat.material_id).first()
                if not material:
                    continue
                needed = round(item_mat.quantity_per_unit * quantity, 4)
                if deduct:
                    if material.stock_quantity < needed:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Insufficient stock for material {material.material_name}. Available: {material.stock_quantity}, required: {needed}"
                        )
                    material.stock_quantity = round(material.stock_quantity - needed, 4)
                else:
                    material.stock_quantity = round(material.stock_quantity + needed, 4)
        else:
            if deduct:
                if int(product.stock_quantity or 0) < quantity:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient stock for {product.name}. Available: {product.stock_quantity}, required: {quantity}"
                    )
                product.stock_quantity = int(product.stock_quantity or 0) - quantity
            else:
                product.stock_quantity = int(product.stock_quantity or 0) + quantity

# ─── DB ──────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── CREATE DEFAULT ADMIN ────────────────────────────────
def create_default_admin():
    """Create the default admin only if it doesn't already exist.
    Automatically re-hashes SHA256 legacy passwords to bcrypt on startup.
    """
    db = SessionLocal()
    try:
        existing = db.query(models.AdminUser).filter(
            models.AdminUser.email == "admin@erp.com"
        ).first()
        if not existing:
            admin = models.AdminUser(
                name="Admin",
                email="admin@erp.com",
                hashed_password=hash_password("admin123"),
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("[OK] Default admin created: admin@erp.com / admin123")
        else:
            # Migrate legacy SHA256 hash → bcrypt if needed
            if not existing.hashed_password.startswith("$2b$"):
                existing.hashed_password = hash_password("admin123")
                db.commit()
                print("[OK] Default admin password migrated to bcrypt")
            else:
                print("[INFO] Default admin already exists, skipping creation")
    finally:
        db.close()

create_default_admin()

# ─── APP ─────────────────────────────────────────────────
app = FastAPI(title="Krishna Poly Net ERP", version="2.0.0")

# CORS — restrict via ALLOWED_ORIGINS env var in production
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

# ─── AUTH DEPENDENCY ─────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.AdminUser).filter(models.AdminUser.id == int(user_id)).first()
    if not user or not user.is_active:
        raise credentials_exception
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role or "sales"}

def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user

def require_sales(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ["admin", "sales"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sales access required")
    return current_user

def require_inventory(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ["admin", "inventory"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inventory access required")
    return current_user

def require_manufacturing(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manufacturing"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manufacturing access required")
    return current_user

# ─── FRONTEND ────────────────────────────────────────────
@app.get("/")
def home():
    return FileResponse(os.path.join(FRONTEND_DIR, "dashboard.html"))

@app.get("/login")
def login_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

# ─── TEST ────────────────────────────────────────────────
@app.get("/api/test")
def test():
    return {"status": "ERP running successfully 🚀", "version": "2.0.0"}

# ─── LOGIN ───────────────────────────────────────────────
@app.post("/api/auth/login")
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Auto-upgrade legacy SHA256 hash to bcrypt on successful login
    if not user.hashed_password.startswith("$2b$"):
        user.hashed_password = hash_password(req.password)
        db.commit()

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

# ─── INPUT VALIDATORS ────────────────────────────────────
def validate_phone(phone: str):
    """Exactly 10 digits (spaces/dashes stripped)."""
    if phone:
        digits_only = ''.join(filter(str.isdigit, phone))
        if len(digits_only) != 10:
            raise HTTPException(
                status_code=400,
                detail="Phone number must be exactly 10 digits"
            )

def validate_email_format(email: str):
    """Basic RFC-style email format check."""
    import re
    if email:
        pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid email format: '{email}'"
            )

def validate_gst(gst: str):
    """Indian GST number: 15-char, format 22AAAAA0000A1Z5."""
    import re
    if gst:
        pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
        if not re.match(pattern, gst.upper()):
            raise HTTPException(
                status_code=400,
                detail="Invalid GST number format. Expected format: 22AAAAA0000A1Z5"
            )

# ─── CUSTOMERS ───────────────────────────────────────────
@app.post("/api/customers")
def create_customer(
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    email = req.get("email", "").strip()
    phone = req.get("phone", "").strip()
    gst   = req.get("gst_number", "").strip().upper() or None

    validate_email_format(email)
    validate_phone(phone)
    validate_gst(gst)

    if email:
        existing = db.query(models.Customer).filter(
            models.Customer.email == email
        ).first()

        if existing:
            if existing.is_deleted:
                existing.name       = req.get("name", existing.name)
                existing.phone      = phone or existing.phone
                existing.address    = req.get("address", existing.address)
                existing.city       = req.get("city", existing.city)
                existing.country    = req.get("country", "India")
                existing.gst_number = gst if gst is not None else existing.gst_number
                existing.is_deleted = False
                db.commit()
                db.refresh(existing)
                return existing
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"A customer with email '{email}' already exists"
                )

    customer = models.Customer(
        name=req.get("name"),
        email=email or None,
        phone=phone or None,
        address=req.get("address"),
        city=req.get("city"),
        country=req.get("country", "India"),
        gst_number=gst
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer

@app.get("/api/customers")
def get_customers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return (
        db.query(Customer)
        .filter(Customer.is_deleted == False)
        .offset(skip)
        .limit(limit)
        .all()
    )

@app.put("/api/customers/{customer_id}")
def update_customer(
    customer_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    phone     = req.get("phone", "").strip()
    new_email = req.get("email", customer.email).strip()
    gst       = req.get("gst_number", "").strip().upper() or None

    validate_email_format(new_email)
    validate_phone(phone)
    validate_gst(gst)

    if new_email != customer.email:
        conflict = db.query(models.Customer).filter(
            models.Customer.email == new_email,
            models.Customer.id != customer_id,
            models.Customer.is_deleted == False
        ).first()
        if conflict:
            raise HTTPException(status_code=400, detail=f"Email '{new_email}' is already used by another customer")

    customer.name       = req.get("name", customer.name)
    customer.email      = new_email
    customer.phone      = phone or customer.phone
    customer.address    = req.get("address", customer.address)
    customer.city       = req.get("city", customer.city)
    customer.gst_number = gst if gst is not None else customer.gst_number
    db.commit()
    db.refresh(customer)
    return customer

@app.delete("/api/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    orders = db.query(Order).filter(Order.customer_id == customer_id).all()
    if orders:
        active_orders = [o for o in orders if o.status not in ["delivered", "cancelled"]]
        if active_orders:
            raise HTTPException(
                status_code=400,
                detail="Customer has active orders (pending/processing). Cannot delete."
            )

    customer.is_deleted = True
    db.commit()
    return {"message": "Customer deleted (hidden)"}

# ─── PRODUCTS ────────────────────────────────────────────
def resolve_and_create_material(db: Session, comp: dict) -> int:
    m_code = comp.get("material_code")
    if m_code:
        m_code = m_code.strip()
    m_name = comp.get("material_name") or ""
    m_unit = comp.get("unit") or "pcs"
    m_rate = float(comp.get("price") if comp.get("price") is not None else 0.00)
    m_stock = float(comp.get("stock_quantity") if comp.get("stock_quantity") is not None else 0.00)
    m_min = float(comp.get("min_stock_level") if comp.get("min_stock_level") is not None else 10.00)

    if not m_code:
        if m_name:
            import re, hashlib
            clean_name = re.sub(r'[^A-Za-z0-9]', '', m_name).upper()
            m_code = f"MAT-{clean_name[:15]}" if clean_name else f"MAT-{hashlib.md5(m_name.encode()).hexdigest()[:8].upper()}"
        else:
            mat_id = comp.get("material_id")
            if mat_id:
                db_mat = db.query(models.Material).filter(models.Material.id == mat_id).first()
                if db_mat:
                    db_mat.is_deleted = False
                    db_mat.is_active = True
                    return db_mat.id
            return None

    db_mat = db.query(models.Material).filter(models.Material.code == m_code).first()
    if db_mat:
        db_mat.name = m_name or db_mat.name
        db_mat.unit = m_unit or db_mat.unit
        db_mat.rate = m_rate
        db_mat.min_stock_level = m_min
        db_mat.is_deleted = False
        db_mat.is_active = True
        db_mat.status = "ok" if db_mat.stock_quantity > db_mat.min_stock_level else "low"
    else:
        db_mat = models.Material(
            name=m_name or m_code,
            code=m_code,
            unit=m_unit,
            rate=m_rate,
            stock_quantity=m_stock,
            min_stock_level=m_min,
            status="ok" if m_stock > m_min else "low",
            is_active=True
        )
        db.add(db_mat)
        db.flush()
    return db_mat.id

@app.post("/api/products")
def create_product(
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    product = models.Product(
        name=req.get("name"),
        sku=req.get("sku"),
        price=float(req.get("price", 0)),
        cost_price=float(req.get("cost_price", 0)) if req.get("cost_price") else None,
        stock_quantity=int(req.get("stock_quantity", 0)),
        min_stock_level=int(req.get("min_stock_level", 10)),
        category_id=req.get("category_id"),
        unit=req.get("unit", "pcs"),
        product_type=req.get("product_type", "FINISHED_GOOD")
    )
    db.add(product)
    db.flush()

    for comp in req.get("components", []):
        material_name = comp.get("material_name") or ""
        unit = comp.get("unit") or "pcs"
        price = float(comp.get("price") if comp.get("price") is not None else 0.00)
        qty = float(comp.get("quantity_per_unit") or 1.0)
        
        # Dynamically search or create the raw material
        material_id = resolve_and_create_material(db, comp)
        if material_id:
            db_mat = db.query(models.Material).filter(models.Material.id == material_id).first()
            if db_mat:
                material_name = db_mat.name
                unit = db_mat.unit
                price = db_mat.rate

        db.add(models.ProductMaterial(
            parent_product_id=product.id,
            material_id=material_id,
            material_name=material_name,
            unit=unit,
            quantity_per_unit=qty,
            price=price,
            stock_quantity=float(comp.get("stock_quantity") or 0.00),
            min_stock_level=float(comp.get("min_stock_level") or 10.00)
        ))

    db.commit()
    db.refresh(product)
    return product

@app.get("/api/products")
def get_products(
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    products = (
        db.query(models.Product)
        .filter(models.Product.is_deleted == False)
        .offset(skip)
        .limit(limit)
        .all()
    )
    result = []
    for p in products:
        p_dict = {
            "id": p.id, "name": p.name, "sku": p.sku,
            "price": p.price, "cost_price": p.cost_price, "stock_quantity": p.stock_quantity,
            "min_stock_level": p.min_stock_level, "category_id": p.category_id,
            "unit": p.unit, "product_type": p.product_type or "FINISHED_GOOD", "created_at": p.created_at,
            "components": []
        }
        comps = db.query(models.ProductMaterial).filter(models.ProductMaterial.parent_product_id == p.id).all()
        for c in comps:
            p_dict["components"].append({
                "id": c.id,
                "material_id": c.material_id,
                "material_name": c.material.name if c.material else c.material_name,
                "material_code": c.material.code if c.material else "",
                "unit": c.material.unit if c.material else c.unit,
                "quantity_per_unit": c.quantity_per_unit,
                "price": c.material.rate if c.material else c.price,
                "stock_quantity": c.material.stock_quantity if c.material else c.stock_quantity,
                "min_stock_level": c.material.min_stock_level if c.material else c.min_stock_level
            })
        result.append(p_dict)
    return result

@app.put("/api/products/{product_id}")
def update_product(
    product_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.name = req.get("name", product.name)
    product.sku = req.get("sku", product.sku)
    product.price = float(req.get("price", product.price))
    product.stock_quantity = int(req.get("stock_quantity", product.stock_quantity))
    product.min_stock_level = int(req.get("min_stock_level", product.min_stock_level))
    if "product_type" in req:
        product.product_type = req["product_type"]

    db.query(models.ProductMaterial).filter(models.ProductMaterial.parent_product_id == product.id).delete()
    for comp in req.get("components", []):
        material_name = comp.get("material_name") or ""
        unit = comp.get("unit") or "pcs"
        price = float(comp.get("price") if comp.get("price") is not None else 0.00)
        qty = float(comp.get("quantity_per_unit") or 1.0)
        
        material_id = resolve_and_create_material(db, comp)
        if material_id:
            db_mat = db.query(models.Material).filter(models.Material.id == material_id).first()
            if db_mat:
                material_name = db_mat.name
                unit = db_mat.unit
                price = db_mat.rate

        db.add(models.ProductMaterial(
            parent_product_id=product.id,
            material_id=material_id,
            material_name=material_name,
            unit=unit,
            quantity_per_unit=qty,
            price=price,
            stock_quantity=float(comp.get("stock_quantity") or 0.00),
            min_stock_level=float(comp.get("min_stock_level") or 10.00)
        ))

    db.commit()
    db.refresh(product)
    return product

@app.delete("/api/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    order_items = db.query(OrderItem).filter(OrderItem.product_id == product_id).all()
    if order_items:
        active_orders = [i for i in order_items if i.order.status not in ["delivered", "cancelled"]]
        if active_orders:
            raise HTTPException(
                status_code=400,
                detail="Product is in active orders (pending/processing). Cannot delete."
            )

    product.is_deleted = True
    db.commit()
    db.refresh(product)
    return {"message": "Product marked as deleted"}

# ─── DASHBOARD ───────────────────────────────────────────
@app.get("/api/dashboard/stats")
def stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    customers = db.query(models.Customer).filter(models.Customer.is_deleted == False).count()
    products = db.query(models.Product).filter(models.Product.is_deleted == False).count()
    orders = db.query(models.Order).count()
    pending_orders = db.query(models.Order).filter(models.Order.status == "pending").count()
    delivered_orders = db.query(models.Order).filter(models.Order.status == "delivered").count()
    cancelled_orders = db.query(models.Order).filter(models.Order.status == "cancelled").count()

    delivered_orders_list = db.query(models.Order).filter(models.Order.status == "delivered").all()
    total_revenue = sum([o.total for o in delivered_orders_list if o.total])

    low_stock = db.query(models.Product).filter(
        models.Product.is_deleted == False,
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
def monthly_revenue(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    orders = db.query(models.Order).filter(models.Order.status == "delivered").all()
    monthly = defaultdict(lambda: {"revenue": 0, "orders": 0})

    for o in orders:
        month_name = o.order_date.strftime("%b")
        monthly[month_name]["revenue"] += o.total
        monthly[month_name]["orders"] += 1

    months_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    result = {}
    for m in months_order:
        result[m] = {"revenue": round(monthly[m]["revenue"], 2), "orders": monthly[m]["orders"]}

    return result

@app.get("/api/dashboard/recent-orders")
def recent_orders(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
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
            "delivery_date": o.delivery_date.strftime("%Y-%m-%d") if o.delivery_date else None,
            "customer_id": o.customer_id
        })
    return result

# ─── INVENTORY ───────────────────────────────────────────
@app.get("/api/inventory")
def get_inventory(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    products = db.query(models.Product).filter(models.Product.is_deleted == False).all()
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
def update_inventory(
    product_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.stock_quantity = req.get("quantity", product.stock_quantity)
    db.commit()
    return {"message": "Inventory updated", "product_id": product_id, "quantity": product.stock_quantity}

# ─── MATERIAL INVENTORY ──────────────────────────────────
@app.get("/api/inventory/materials")
def get_material_inventory(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Return all materials grouped by their parent product."""
    products = db.query(models.Product).filter(models.Product.is_deleted == False).all()
    result = []
    for p in products:
        materials = db.query(models.ProductMaterial).filter(
            models.ProductMaterial.parent_product_id == p.id
        ).all()
        if not materials:
            continue
        result.append({
            "product_id": p.id,
            "product_name": p.name,
            "product_sku": p.sku,
            "materials": [material_response(m) for m in materials]
        })
    return result

@app.put("/api/inventory/material/{material_id}")
def update_material_inventory(
    material_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    material = db.query(models.ProductMaterial).filter(models.ProductMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    if "quantity" in req:
        quantity = to_float(req["quantity"], -1)
        if quantity < 0:
            raise HTTPException(status_code=400, detail="Material stock cannot be negative")
        material.stock_quantity = quantity
        if material.material:
            material.material.stock_quantity = quantity
    if "min_stock_level" in req:
        min_stock_level = to_float(req["min_stock_level"], -1)
        if min_stock_level < 0:
            raise HTTPException(status_code=400, detail="Minimum stock level cannot be negative")
        material.min_stock_level = min_stock_level
        if material.material:
            material.material.min_stock_level = min_stock_level
            material.material.status = "ok" if material.material.stock_quantity > min_stock_level else "low"
    if "quantity_per_unit" in req:
        quantity_per_unit = to_float(req["quantity_per_unit"], -1)
        if quantity_per_unit <= 0:
            raise HTTPException(status_code=400, detail="Quantity per product must be greater than 0")
        material.quantity_per_unit = quantity_per_unit
    db.commit()
    return {
        "message": "Material stock updated",
        "material_id": material_id,
        "stock_quantity": material.stock_quantity,
        "min_stock_level": material.min_stock_level,
        "quantity_per_unit": material.quantity_per_unit
    }

# ─── MANUFACTURING ───────────────────────────────────────
@app.get("/api/manufacture/products")
def get_manufacture_products(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    products = db.query(models.Product).filter(models.Product.is_deleted == False).all()
    result = []
    for product in products:
        materials = db.query(models.ProductMaterial).filter(
            models.ProductMaterial.parent_product_id == product.id
        ).all()
        result.append({
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "unit": product.unit or "pcs",
            "stock_quantity": product.stock_quantity or 0,
            "materials": [material_response(material) for material in materials]
        })
    return result

@app.post("/api/manufacture/check")
def check_manufacture(
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    product = db.query(models.Product).filter(
        models.Product.id == req.get("product_id"),
        models.Product.is_deleted == False
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    qty = parse_manufacture_qty(req.get("qty"))
    materials, can_manufacture = manufacture_requirements(product.id, qty, db)
    return {
        "product_id": product.id,
        "product_name": product.name,
        "qty": qty,
        "can_manufacture": can_manufacture,
        "materials": materials
    }

@app.post("/api/manufacture/execute")
def execute_manufacture(
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    product = db.query(models.Product).filter(
        models.Product.id == req.get("product_id"),
        models.Product.is_deleted == False
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    qty = parse_manufacture_qty(req.get("qty"))
    requirements, can_manufacture = manufacture_requirements(product.id, qty, db)
    if not can_manufacture:
        raise HTTPException(
            status_code=400,
            detail={"message": "Insufficient material stock", "materials": requirements}
        )

    for requirement in requirements:
        material = db.query(models.ProductMaterial).filter(
            models.ProductMaterial.id == requirement["id"]
        ).first()
        if material:
            material.stock_quantity = round(to_float(material.stock_quantity) - requirement["needed"], 4)

    product.stock_quantity = int(product.stock_quantity or 0) + qty
    db.commit()
    db.refresh(product)

    return {
        "message": f"Manufactured {qty} units of {product.name}",
        "product_id": product.id,
        "product_stock_quantity": product.stock_quantity,
        "materials": requirements
    }

@app.put("/api/manufacture/material/{material_id}/stock")
def update_manufacture_material(
    material_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    material = db.query(models.ProductMaterial).filter(models.ProductMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    if "stock_quantity" in req:
        stock_quantity = to_float(req.get("stock_quantity"), -1)
        if stock_quantity < 0:
            raise HTTPException(status_code=400, detail="Material stock cannot be negative")
        material.stock_quantity = stock_quantity

    if "quantity_per_unit" in req:
        quantity_per_unit = to_float(req.get("quantity_per_unit"), -1)
        if quantity_per_unit <= 0:
            raise HTTPException(status_code=400, detail="Quantity per product must be greater than 0")
        material.quantity_per_unit = quantity_per_unit

    if "min_stock_level" in req:
        min_stock_level = to_float(req.get("min_stock_level"), -1)
        if min_stock_level < 0:
            raise HTTPException(status_code=400, detail="Minimum stock level cannot be negative")
        material.min_stock_level = min_stock_level

    db.commit()
    db.refresh(material)
    return {"message": "Material production settings updated", "material": material_response(material)}

# ─── ORDERS ──────────────────────────────────────────────
# ─── ORDERS ──────────────────────────────────────────────
@app.get("/api/orders")
def get_orders(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    query = db.query(models.Order)
    if status:
        query = query.filter(models.Order.status == status)
    
    orders = query.order_by(models.Order.id.desc()).offset(skip).limit(limit).all()

    result = []
    for o in orders:
        customer = db.query(models.Customer).filter(models.Customer.id == o.customer_id).first()
        items = db.query(models.OrderItem).filter(models.OrderItem.order_id == o.id).all()
        result.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer": {"id": customer.id, "name": customer.name} if customer else None,
            "customer_id": o.customer_id,
            "status": o.status,
            "total": o.total,
            "description": o.description,
            "priority": o.priority,
            "order_date": o.order_date.strftime("%Y-%m-%d") if o.order_date else None,
            "delivery_date": o.delivery_date.strftime("%Y-%m-%d") if o.delivery_date else None,
            "items": [
                {
                    "product_id": i.product_id,
                    "product_name": i.product.name if i.product else None,
                    "quantity": i.quantity,
                    "unit": i.unit or "pcs",
                    "unit_price": i.unit_price,
                    "total_price": i.total_price
                }
                for i in items
            ]
        })
    return result

@app.delete("/api/orders/{order_id}")
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    db.delete(order)
    db.commit()
    return {"message": "Order deleted successfully"}

# ─── ADMIN USERS ─────────────────────────────────────────
@app.get("/api/admin/users")
def get_users(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
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
def create_user(
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
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
def update_user(
    user_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    user = db.query(models.AdminUser).filter(models.AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.name  = req.get("name", user.name)
    user.email = req.get("email", user.email)
    user.role  = req.get("role", user.role)

    if req.get("password"):
        user.hashed_password = hash_password(req.get("password"))

    db.commit()
    db.refresh(user)
    return {"message": "User updated"}

@app.patch("/api/admin/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    user = db.query(models.AdminUser).filter(models.AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"is_active": user.is_active}

@app.delete("/api/admin/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    user = db.query(models.AdminUser).filter(models.AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}




# ═══════════════════════════════════════════════════════════════════════════════
# MAKE-TO-ORDER ERP UPGRADE — API Routes
# ═══════════════════════════════════════════════════════════════════════════════

# ─── MATERIAL MASTER (RAW MATERIALS) ──────────────────────────────────────────

@app.get("/api/materials", response_model=List[schemas.MaterialOut])
def list_raw_materials(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Retrieve raw materials catalog list."""
    # Anyone authenticated can view materials
    return crud.get_materials(db, skip=skip, limit=limit)

@app.post("/api/materials", response_model=schemas.MaterialOut)
def add_new_material(
    material: schemas.MaterialCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_sales)
):
    """Create a new raw material item."""
    # Check for duplicate code
    existing = crud.get_material_by_code(db, material.code)
    if existing:
        raise HTTPException(status_code=400, detail=f"Material with code '{material.code}' already exists")
    
    return crud.create_material(db, material)

@app.put("/api/materials/{material_id}", response_model=schemas.MaterialOut)
def edit_material(
    material_id: int,
    material: schemas.MaterialCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """Update raw material properties (Admin only)."""
    # Check code clash if code changed
    existing = crud.get_material_by_code(db, material.code)
    if existing and existing.id != material_id:
        raise HTTPException(status_code=400, detail=f"Material with code '{material.code}' already exists")
        
    return crud.update_material(db, material_id, material)

@app.delete("/api/materials/{material_id}")
def deactivate_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """Deactivate / Soft-delete raw material item (Admin only)."""
    crud.delete_material(db, material_id)
    return {"message": "Material deleted / deactivated successfully"}

@app.post("/api/materials/{material_id}/purchase", response_model=schemas.MaterialOut)
def restock_material(
    material_id: int,
    req: schemas.MaterialPurchaseRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_inventory) # Inventory can update stock
):
    """Restock / Add stock to a raw material item."""
    db_material = crud.get_material(db, material_id)
    if not db_material or db_material.is_deleted:
        raise HTTPException(status_code=404, detail="Material not found")
        
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Restock quantity must be greater than 0")
        
    db_material.stock_quantity = round((db_material.stock_quantity or 0.0) + req.quantity, 4)
    db_material.status = "ok" if db_material.stock_quantity > db_material.min_stock_level else "low"
    db.commit()
    db.refresh(db_material)
    return db_material

# ─── EXTENDED ORDER CREATION & EDITING (Sales / Admin) ─────────────────────────

@app.post("/api/orders")
def create_customer_order(
    req: schemas.OrderCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_sales)
):
    """Create customer order with dynamic items, materials (product-wise), and extra items grids."""
    import random
    import string

    def generate_order_number():
        prefix = "ORD"
        suffix = ''.join(random.choices(string.digits, k=6))
        return f"{prefix}-{datetime.now().strftime('%Y%m')}-{suffix}"

    # Calculate item subtotal
    subtotal = sum(item.quantity * item.unit_price for item in req.items)
    
    # Calculate extra items total
    extra_total = sum(item.quantity * item.price for item in req.extra_items)
    
    # Calculate dynamic materials total (product-wise)
    materials_total = 0.0
    for item in req.items:
        for mat in item.materials:
            materials_total += mat.required_qty * (mat.rate or 0.0)
    
    total = round(subtotal + extra_total + materials_total, 2)

    order = models.Order(
        order_number=generate_order_number(),
        customer_id=req.customer_id,
        status="pending", # Order Status = Pending
        subtotal=round(subtotal, 2),
        total=total,
        description=req.description,
        priority=req.priority or "medium",
        inventory_deducted=False,
        delivery_date=req.delivery_date
    )
    db.add(order)
    db.flush()

    # Add items and their materials
    for item in req.items:
        order_item = models.OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit=item.unit or "pcs",
            unit_price=item.unit_price,
            total_price=round(item.quantity * item.unit_price, 2),
            description=item.description
        )
        db.add(order_item)
        db.flush()
        
        # Save product-wise materials
        for mat in item.materials:
            mat_dict = {
                "material_id": mat.material_id,
                "material_name": mat.material_name,
                "material_code": mat.material_code,
                "unit": mat.unit,
                "price": mat.rate,
                "stock_quantity": 0.0,
                "min_stock_level": 10.0
            }
            resolved_id = resolve_and_create_material(db, mat_dict)
            if not resolved_id:
                raise HTTPException(status_code=400, detail="Could not resolve raw material reference")
            
            db_material = db.query(models.Material).filter(models.Material.id == resolved_id).first()
            if not db_material or db_material.is_deleted:
                raise HTTPException(status_code=400, detail=f"Invalid material reference")
                
            order_material = models.OrderMaterial(
                order_id=order.id,
                order_item_id=order_item.id,
                material_id=resolved_id,
                required_qty=mat.required_qty,
                used_qty=0.0,
                unit=mat.unit or db_material.unit or "pcs",
                rate=mat.rate or db_material.rate or 0.00,
                amount=round(mat.required_qty * (mat.rate or db_material.rate or 0.00), 2),
                remarks=mat.remarks
            )
            db.add(order_material)

    # Add extra items
    for item in req.extra_items:
        extra_item = models.OrderExtraItem(
            order_id=order.id,
            item_name=item.item_name,
            quantity=item.quantity,
            price=item.price,
            amount=round(item.quantity * item.price, 2)
        )
        db.add(extra_item)

    db.commit()
    db.refresh(order)

    # Create audit log timeline
    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action="Order Created",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=f"Order created with total value Rs {total}"
    )

    return {"message": "Order created successfully", "order_id": order.id, "order_number": order.order_number}

@app.put("/api/orders/{order_id}")
def update_customer_order(
    order_id: int,
    req: schemas.OrderCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_sales)
):
    """Modify customer order dynamic grids (Sales / Admin only)."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    # Orders are always editable regardless of status (by sales/admin)

    # Clear old lists
    db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).delete()
    db.query(models.OrderMaterial).filter(models.OrderMaterial.order_id == order.id).delete()
    db.query(models.OrderExtraItem).filter(models.OrderExtraItem.order_id == order.id).delete()

    # Recalculate totals
    subtotal = sum(item.quantity * item.unit_price for item in req.items)
    extra_total = sum(item.quantity * item.price for item in req.extra_items)
    
    materials_total = 0.0
    for item in req.items:
        for mat in item.materials:
            materials_total += mat.required_qty * (mat.rate or 0.0)
            
    total = round(subtotal + extra_total + materials_total, 2)

    # Re-insert items and their materials
    for item in req.items:
        order_item = models.OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit=item.unit or "pcs",
            unit_price=item.unit_price,
            total_price=round(item.quantity * item.unit_price, 2),
            description=item.description
        )
        db.add(order_item)
        db.flush()
        
        # Save product-wise materials
        for mat in item.materials:
            mat_dict = {
                "material_id": mat.material_id,
                "material_name": mat.material_name,
                "material_code": mat.material_code,
                "unit": mat.unit,
                "price": mat.rate,
                "stock_quantity": 0.0,
                "min_stock_level": 10.0
            }
            resolved_id = resolve_and_create_material(db, mat_dict)
            if not resolved_id:
                raise HTTPException(status_code=400, detail="Could not resolve raw material reference")
            
            db_material = db.query(models.Material).filter(models.Material.id == resolved_id).first()
            if not db_material or db_material.is_deleted:
                raise HTTPException(status_code=400, detail=f"Invalid material reference")
                
            order_material = models.OrderMaterial(
                order_id=order.id,
                order_item_id=order_item.id,
                material_id=resolved_id,
                required_qty=mat.required_qty,
                used_qty=0.0,
                unit=mat.unit or db_material.unit or "pcs",
                rate=mat.rate or db_material.rate or 0.00,
                amount=round(mat.required_qty * (mat.rate or db_material.rate or 0.00), 2),
                remarks=mat.remarks
            )
            db.add(order_material)

    # Re-insert extra items
    for item in req.extra_items:
        extra_item = models.OrderExtraItem(
            order_id=order.id,
            item_name=item.item_name,
            quantity=item.quantity,
            price=item.price,
            amount=round(item.quantity * item.price, 2)
        )
        db.add(extra_item)

    order.customer_id = req.customer_id
    order.description = req.description
    order.priority = req.priority or "medium"
    order.delivery_date = req.delivery_date
    order.subtotal = round(subtotal, 2)
    order.total = total
    
    db.commit()
    db.refresh(order)

    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action="Order Modified",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks="Order items and custom BOM grids modified."
    )

    return {"message": "Order updated successfully", "order_id": order.id}


# ─── UNIVERSAL ORDER STATUS UPDATE (3-Department Workflow) ────────────────────

# Allowed transitions per role
_SALES_STATUSES = [
    "order_confirmed", "payment_received", "ready_to_process",
    "start_processing", "ready_to_dispatch", "dispatched",
    "paused", "other", "cancelled", "pending"
]
_MANUFACTURING_STATUSES = [
    "start_processing", "ready_to_dispatch", "dispatched", "other", "cancelled"
]

@app.post("/api/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    req: schemas.StatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Universal order status update for the 3-department workflow.
    Sales: can set any status in their list.
    Manufacturing: can set start_processing, ready_to_dispatch, dispatched, other, cancelled.
    When ready_to_process is set, auto-runs inventory check and includes result in response.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    role = current_user["role"]
    new_status = req.status.strip().lower()

    # Validate role permissions
    if role in ["admin", "sales"]:
        if new_status not in _SALES_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}' for sales role.")
    elif role == "manufacturing":
        if new_status not in _MANUFACTURING_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}' for manufacturing role.")
    else:
        raise HTTPException(status_code=403, detail="You do not have permission to update order status.")

    prev_status = order.status
    
    # ─── New Workflow Trigger logic ───
    if new_status == "ready_to_process":
        # Check stock availability for all materials in order
        short_materials = []
        for om in order.order_materials:
            material = om.material
            if not material or material.is_deleted:
                continue
            required = to_float(om.required_qty)
            available = to_float(material.stock_quantity)
            if available < required:
                # Set material status in database to low
                material.status = "low"
                short_materials.append(material.name)
        
        if short_materials:
            db.commit() # Commit the material status update to low
            raise HTTPException(
                status_code=400,
                detail=f"Low material stock"
            )
    if new_status == "start_processing":
        # Deduct stock if not already done
        if not order.inventory_deducted:
            for om in order.order_materials:
                material = om.material
                if not material or material.is_deleted:
                    raise HTTPException(status_code=400, detail="BOM contains invalid material reference")
                required = to_float(om.required_qty)
                available = to_float(material.stock_quantity)
                if available < required:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Stock check failed: {material.name} requires {required} but only {available} available."
                    )
            
            # Deduct materials
            for om in order.order_materials:
                material = om.material
                required = to_float(om.required_qty)
                material.stock_quantity = round(to_float(material.stock_quantity) - required, 4)
                material.status = "ok" if material.stock_quantity > material.min_stock_level else "low"
                om.used_qty = required
                
            order.inventory_deducted = True
            
            # Create manufacturing run log
            mfg_log = models.ManufacturingLog(
                order_id=order.id,
                started_at=datetime.utcnow(),
                started_by=current_user["id"],
                remarks=req.remarks or "Manufacturing started via status update."
            )
            db.add(mfg_log)

    elif new_status == "ready_to_dispatch":
        if prev_status != "start_processing":
            raise HTTPException(
                status_code=400,
                detail="Order must be in 'start_processing' (Processing) state before it can be marked as 'ready_to_dispatch'."
            )

    elif new_status in ["dispatched", "completed"]:
        if new_status == "dispatched" and prev_status != "ready_to_dispatch":
            raise HTTPException(
                status_code=400,
                detail="Order must be in 'ready_to_dispatch' state before it can be marked as 'dispatched'."
            )
        mfg_log = db.query(models.ManufacturingLog).filter(
            models.ManufacturingLog.order_id == order.id,
            models.ManufacturingLog.completed_at == None
        ).order_by(models.ManufacturingLog.id.desc()).first()
        if mfg_log:
            mfg_log.completed_at = datetime.utcnow()
            mfg_log.completed_by = current_user["id"]
            mfg_log.remarks = f"{mfg_log.remarks or ''} | Closed via dispatched/completed status update."

    order.status = new_status
    db.commit()

    # Log timeline entry
    status_labels = {
        "order_confirmed": "Order Confirmed",
        "payment_received": "Payment Received",
        "ready_to_process": "Ready to Process",
        "start_processing": "Start Processing",
        "ready_to_dispatch": "Ready to Dispatch",
        "dispatched": "Dispatched",
        "paused": "Order Paused",
        "other": "Other Update",
        "cancelled": "Order Cancelled",
        "pending": "Reset to Pending"
    }
    action_label = status_labels.get(new_status, new_status.replace("_", " ").title())
    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action=action_label,
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=req.remarks or f"Status changed from '{prev_status}' to '{new_status}'."
    )

    # If ready_to_process: run background inventory check and return result
    inv_check = None
    if new_status == "ready_to_process":
        can_approve = True
        check_items = []
        for om in order.order_materials:
            material = om.material
            if not material or material.is_deleted:
                continue
            required = to_float(om.required_qty)
            available = to_float(material.stock_quantity)
            shortage = max(0.0, round(required - available, 4))
            is_sufficient = available >= required
            if not is_sufficient:
                can_approve = False
            check_items.append({
                "material_name": material.name,
                "required_qty": required,
                "available_qty": available,
                "shortage_qty": shortage,
                "status": "ok" if is_sufficient else "shortage"
            })
        inv_check = {"can_process": can_approve, "items": check_items}

    return {
        "message": f"Order status updated to '{new_status}'",
        "order_id": order_id,
        "status": new_status,
        "inventory_check": inv_check
    }


# ─── MANUFACTURING DEPARTMENT QUEUE (Manufacturing / Admin) ───────────────────

@app.get("/api/orders/manufacturing")
def get_manufacturing_orders(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Returns all orders currently in the manufacturing pipeline:
    ready_to_process, start_processing, ready_to_dispatch.
    Used exclusively by the Manufacturing Department screen.
    """
    mfg_statuses = ["ready_to_process", "start_processing", "ready_to_dispatch"]
    orders = (
        db.query(models.Order)
        .filter(models.Order.status.in_(mfg_statuses))
        .order_by(models.Order.id.desc())
        .all()
    )
    result = []
    for o in orders:
        customer = db.query(models.Customer).filter(models.Customer.id == o.customer_id).first()
        items = db.query(models.OrderItem).filter(models.OrderItem.order_id == o.id).all()
        item_list = []
        for i in items:
            prod_name = i.product.name if i.product else f"Product #{i.product_id}"
            mats = []
            for om in i.order_materials:
                mat_name = om.material.name if om.material else f"Material #{om.material_id}"
                mats.append({
                    "material_name": mat_name,
                    "required_qty": om.required_qty,
                    "unit": om.unit,
                    "rate": om.rate
                })
            item_list.append({
                "product_name": prod_name,
                "quantity": i.quantity,
                "unit": i.unit or "pcs",
                "description": i.description,
                "materials": mats
            })
        result.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer": {"id": customer.id, "name": customer.name} if customer else None,
            "status": o.status,
            "priority": o.priority,
            "total": o.total,
            "description": o.description,
            "order_date": o.order_date.strftime("%Y-%m-%d") if o.order_date else None,
            "delivery_date": o.delivery_date.strftime("%Y-%m-%d") if o.delivery_date else None,
            "items": item_list
        })
    return result


@app.get("/api/orders/{order_id}", response_model=schemas.OrderFull)
def get_order_details(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Retrieve full order details with timeline audit trail."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Serialize customer details
    cust = None
    if order.customer and not order.customer.is_deleted:
        cust = order.customer

    # Map dynamic materials (flat catalog at root level for compatibility)
    om_list = []
    for om in order.order_materials:
        material_name = om.material.name if om.material else f"Material #{om.material_id}"
        material_code = om.material.code if om.material else "-"
        om_list.append({
            "id": om.id,
            "order_id": om.order_id,
            "order_item_id": om.order_item_id,
            "material_id": om.material_id,
            "material_name": material_name,
            "material_code": material_code,
            "required_qty": om.required_qty,
            "used_qty": om.used_qty,
            "unit": om.unit,
            "rate": om.rate,
            "amount": om.amount,
            "remarks": om.remarks,
            "created_at": om.created_at,
            "updated_at": om.updated_at
        })

    # Map extra items
    ei_list = []
    for ei in order.extra_items:
        ei_list.append({
            "id": ei.id,
            "order_id": ei.order_id,
            "item_name": ei.item_name,
            "quantity": ei.quantity,
            "price": ei.price,
            "amount": ei.amount,
            "created_at": ei.created_at
        })

    # Map timeline entries (sorted by timestamp)
    tl_list = sorted(
        [
            {
                "id": t.id,
                "order_id": t.order_id,
                "action": t.action,
                "user_id": t.user_id,
                "user_name": t.user_name,
                "role": t.role,
                "timestamp": t.timestamp,
                "remarks": t.remarks
            }
            for t in order.timeline
        ],
        key=lambda x: x["timestamp"]
    )

    # Map order items (including product-wise materials)
    items_list = []
    for item in order.items:
        prod = None
        if item.product and not item.product.is_deleted:
            prod = item.product
            
        item_mats = []
        for om in item.order_materials:
            material_name = om.material.name if om.material else f"Material #{om.material_id}"
            material_code = om.material.code if om.material else "-"
            item_mats.append({
                "id": om.id,
                "order_id": om.order_id,
                "order_item_id": om.order_item_id,
                "material_id": om.material_id,
                "material_name": material_name,
                "material_code": material_code,
                "required_qty": om.required_qty,
                "used_qty": om.used_qty,
                "unit": om.unit,
                "rate": om.rate,
                "amount": om.amount,
                "remarks": om.remarks,
                "created_at": om.created_at,
                "updated_at": om.updated_at
            })
            
        items_list.append({
            "id": item.id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total_price": item.total_price,
            "unit": item.unit,
            "description": item.description,
            "product": prod,
            "materials": [],
            "order_materials": item_mats
        })

    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "status": order.status,
        "subtotal": order.subtotal,
        "total": order.total,
        "description": order.description,
        "priority": order.priority,
        "order_date": order.order_date,
        "delivery_date": order.delivery_date,
        "inventory_deducted": order.inventory_deducted,
        "customer": cust,
        "items": items_list,
        "order_materials": om_list,
        "extra_items": ei_list,
        "timeline": tl_list
    }

# ─── INVENTORY MODULE ACTIONS (Inventory / Admin) ─────────────────────────────

@app.get("/api/orders/{order_id}/inventory-check", response_model=schemas.InventoryCheckResponse)
def check_order_inventory(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Retrieve detailed material stock status and shortages for the order."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    can_approve = True
    check_items = []
    
    for om in order.order_materials:
        material = om.material
        if not material or material.is_deleted:
            continue
        
        required = to_float(om.required_qty)
        available = to_float(material.stock_quantity)
        shortage = max(0.0, round(required - available, 4))
        is_sufficient = available >= required
        
        if not is_sufficient:
            can_approve = False
            
        check_items.append({
            "material_id": material.id,
            "material_name": material.name,
            "material_code": material.code,
            "required_qty": required,
            "available_qty": available,
            "shortage_qty": shortage,
            "status": "ok" if is_sufficient else "shortage"
        })

    return {
        "order_id": order_id,
        "can_approve": can_approve,
        "items": check_items
    }

@app.post("/api/orders/{order_id}/inventory/approve")
def approve_order_inventory(
    order_id: int,
    req: schemas.StatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_inventory)
):
    """Set order status to 'Inventory Approved' (Inventory / Admin)."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status not in ["pending", "need_purchase"]:
        raise HTTPException(status_code=400, detail=f"Cannot approve inventory from status '{order.status}'")

    order.status = "inventory_approved"
    db.commit()

    # Timeline entry log
    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action="Inventory Approved",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=req.remarks or "All dynamic raw materials are marked as verified."
    )

    return {"message": "Inventory successfully approved", "order_id": order_id, "status": "inventory_approved"}

@app.post("/api/orders/{order_id}/inventory/reject")
def reject_order_inventory(
    order_id: int,
    req: schemas.StatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_inventory)
):
    """Reject inventory approval: transitions to 'Need Purchase' or 'Cancelled'."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = req.status.lower()
    if new_status not in ["need_purchase", "cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid target status. Use: 'need_purchase' or 'cancelled'")

    order.status = new_status
    db.commit()

    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action=f"Inventory Rejected ({new_status})",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=req.remarks or f"Order flagged as: {new_status}."
    )

    return {"message": f"Inventory flagged as {new_status}", "order_id": order_id, "status": new_status}

# ─── MANUFACTURING WORKS WORKFLOWS (Manufacturing / Admin) ─────────────────────

@app.post("/api/orders/{order_id}/manufacture/start")
def start_order_manufacturing(
    order_id: int,
    req: schemas.StatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_manufacturing)
):
    """
    Validate stocks and start manufacturing.
    Deducts custom dynamic raw materials from materials master.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != "inventory_approved":
        raise HTTPException(status_code=400, detail=f"Cannot start manufacturing on a status '{order.status}' order.")

    # Re-validate stock pre-flight check
    for om in order.order_materials:
        material = om.material
        if not material or material.is_deleted:
            raise HTTPException(status_code=400, detail="Dynamic BOM contains invalid material reference")
            
        required = to_float(om.required_qty)
        available = to_float(material.stock_quantity)
        if available < required:
            raise HTTPException(
                status_code=400,
                detail=f"Stock check failed: {material.name} requires {required} but only {available} available."
            )

    # Perform deduction
    for om in order.order_materials:
        material = om.material
        required = to_float(om.required_qty)
        material.stock_quantity = round(to_float(material.stock_quantity) - required, 4)
        material.status = "ok" if material.stock_quantity > material.min_stock_level else "low"
        om.used_qty = required # record used_qty
        
    order.status = "manufacturing"
    order.inventory_deducted = True # Mark true to show stock consumption occurred

    # Create Manufacturing run log
    mfg_log = models.ManufacturingLog(
        order_id=order.id,
        started_at=datetime.utcnow(),
        started_by=current_user["id"],
        remarks=req.remarks or "Manufacturing started. Material stocks deducted."
    )
    db.add(mfg_log)
    db.commit()

    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action="Manufacturing Started",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=req.remarks or "Material stock deduction completed. Manufacturing underway."
    )

    return {"message": "Manufacturing started successfully", "order_id": order_id, "status": "manufacturing"}

@app.post("/api/orders/{order_id}/manufacture/complete")
def complete_order_manufacturing(
    order_id: int,
    req: schemas.StatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_manufacturing)
):
    """Complete manufacturing: transition to 'Manufactured' (no finished goods increase)."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != "manufacturing":
        raise HTTPException(status_code=400, detail="Order must be currently in 'manufacturing' state.")

    order.status = "manufactured"
    
    # Update end logs
    mfg_log = db.query(models.ManufacturingLog).filter(
        models.ManufacturingLog.order_id == order.id,
        models.ManufacturingLog.completed_at == None
    ).order_by(models.ManufacturingLog.id.desc()).first()
    
    if mfg_log:
        mfg_log.completed_at = datetime.utcnow()
        mfg_log.completed_by = current_user["id"]
        if req.remarks:
            mfg_log.remarks = f"{mfg_log.remarks or ''} | Comp: {req.remarks}"

    db.commit()

    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action="Manufacturing Completed",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=req.remarks or "Product successfully manufactured. Awaiting final closure."
    )

    return {"message": "Manufacturing completed successfully", "order_id": order_id, "status": "manufactured"}

# ─── ADMIN COMPLETION WORKFLOW (Admin only) ───────────────────────────────────

@app.post("/api/orders/{order_id}/complete")
def finalize_order(
    order_id: int,
    req: schemas.StatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """Finalize order: sets status to 'completed' (Admin only)."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != "manufactured":
        raise HTTPException(status_code=400, detail="Only manufactured orders can be marked as completed.")

    order.status = "completed"
    db.commit()

    crud.create_timeline_entry(
        db,
        order_id=order.id,
        action="Order Completed",
        user_id=current_user["id"],
        user_name=current_user["name"],
        role=current_user["role"],
        remarks=req.remarks or "Order completed and fully finalized."
    )

    return {"message": "Order marked as completed", "order_id": order_id, "status": "completed"}

# ─── REPORTS API MODULES ───────────────────────────────────────────────────────

@app.get("/api/reports/orders")
def get_order_report(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Return summary analytics on order status, count, and totals."""
    results = db.query(
        models.Order.status,
        func.count(models.Order.id).label("count"),
        func.sum(models.Order.total).label("total_value")
    ).group_by(models.Order.status).all()
    
    return [
        {
            "status": r.status,
            "count": r.count,
            "total_value": round(r.total_value or 0.00, 2)
        }
        for r in results
    ]

@app.get("/api/reports/manufacturing")
def get_manufacturing_report(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Return historical log reports of completed and active manufacturing runs."""
    logs = db.query(models.ManufacturingLog).order_by(models.ManufacturingLog.started_at.desc()).all()
    result = []
    for l in logs:
        ord_num = l.order.order_number if l.order else f"Order #{l.order_id}"
        op_start = l.started_by_user.name if l.started_by_user else "-"
        op_comp = l.completed_by_user.name if l.completed_by_user else "-"
        duration = None
        if l.started_at and l.completed_at:
            duration = str(l.completed_at - l.started_at).split(".")[0] # friendly format
            
        result.append({
            "order_number": ord_num,
            "started_at": l.started_at.isoformat() if l.started_at else None,
            "completed_at": l.completed_at.isoformat() if l.completed_at else None,
            "started_by": op_start,
            "completed_by": op_comp,
            "duration": duration,
            "remarks": l.remarks
        })
    return result

@app.get("/api/reports/inventory")
def get_inventory_report(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List raw materials stock, status, alerts, and calculated stock valuation."""
    materials = db.query(models.Material).filter(models.Material.is_deleted == False).all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "code": m.code,
            "unit": m.unit,
            "stock_quantity": m.stock_quantity,
            "min_stock_level": m.min_stock_level,
            "rate": m.rate,
            "valuation": round(m.stock_quantity * m.rate, 2),
            "status": m.status
        }
        for m in materials
    ]

@app.get("/api/reports/material-consumption")
def get_material_consumption_report(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Aggregated raw materials consumption values based on manufactured/completed orders."""
    results = db.query(
        models.Material.name.label("material_name"),
        models.Material.code.label("material_code"),
        models.Material.unit.label("unit"),
        func.sum(models.OrderMaterial.used_qty).label("total_consumed"),
        func.sum(models.OrderMaterial.amount).label("total_cost")
    ).join(
        models.OrderMaterial, models.OrderMaterial.material_id == models.Material.id
    ).join(
        models.Order, models.Order.id == models.OrderMaterial.order_id
    ).filter(
        models.Order.status.in_([
            "manufacturing", "manufactured", "completed",
            "start_processing", "ready_to_dispatch", "dispatched"
        ])
    ).group_by(
        models.Material.name, models.Material.code, models.Material.unit
    ).all()
    
    return [
        {
            "material_name": r.material_name,
            "material_code": r.material_code,
            "unit": r.unit,
            "total_consumed": r.total_consumed or 0.00,
            "total_cost": round(r.total_cost or 0.00, 2)
        }
        for r in results
    ]

@app.get("/api/reports/customers")
def get_customer_report(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Customer analytics report containing total order counts and revenues."""
    results = db.query(
        models.Customer.name.label("customer_name"),
        models.Customer.email.label("customer_email"),
        func.count(models.Order.id).label("orders_count"),
        func.sum(models.Order.total).label("total_spend")
    ).join(
        models.Order, models.Order.customer_id == models.Customer.id
    ).filter(
        models.Customer.is_deleted == False
    ).group_by(
        models.Customer.name, models.Customer.email
    ).order_by(
        func.sum(models.Order.total).desc()
    ).all()

    return [
        {
            "customer_name": r.customer_name,
            "customer_email": r.customer_email,
            "orders_count": r.orders_count,
            "total_spend": round(r.total_spend or 0.00, 2)
        }
        for r in results
    ]


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

