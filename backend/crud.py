"""
crud.py — Database Helper Utilities
=====================================
This module contains reusable CRUD helper functions originally intended to be
called from FastAPI route handlers.

CURRENT STATUS:
  All active route logic lives directly in main.py.
  These helpers are NOT currently wired to any API routes and exist
  for reference/future refactoring only.

If you wish to refactor main.py into a cleaner layered architecture,
these functions are the right starting point — just import and call them
from the route handlers in main.py.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime
from typing import Optional, List
import models, schemas
import random
import string

def generate_order_number():
    prefix = "EPR"
    suffix = ''.join(random.choices(string.digits, k=6))
    return f"{prefix}-{datetime.now().strftime('%Y%m')}-{suffix}"

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
def get_dashboard_stats(db: Session):
    total_orders = db.query(models.Order).count()
    pending_orders = db.query(models.Order).filter(models.Order.status == "pending").count()
    total_revenue = db.query(func.sum(models.Order.total)).filter(
        models.Order.status != "cancelled"
    ).scalar() or 0
    # Bug fix: exclude soft-deleted records from counts
    total_customers = db.query(models.Customer).filter(models.Customer.is_deleted == False).count()
    total_products = db.query(models.Product).filter(models.Product.is_deleted == False).count()
    low_stock = db.query(models.Product).filter(
        models.Product.is_deleted == False,
        models.Product.stock_quantity <= models.Product.min_stock_level
    ).count()
    delivered = db.query(models.Order).filter(models.Order.status == "delivered").count()
    cancelled = db.query(models.Order).filter(models.Order.status == "cancelled").count()

    return {
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "total_revenue": round(total_revenue, 2),
        "total_customers": total_customers,
        "total_products": total_products,
        "low_stock_alerts": low_stock,
        "delivered_orders": delivered,
        "cancelled_orders": cancelled,
    }

def get_monthly_revenue(db: Session):
    results = db.query(
        extract('month', models.Order.order_date).label('month'),
        func.sum(models.Order.total).label('revenue'),
        func.count(models.Order.id).label('orders')
    ).filter(
        models.Order.status != 'cancelled',
        extract('year', models.Order.order_date) == datetime.now().year
    ).group_by('month').all()

    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    data = {m: {"revenue": 0, "orders": 0} for m in months}
    for r in results:
        idx = int(r.month) - 1
        data[months[idx]] = {"revenue": round(r.revenue or 0, 2), "orders": r.orders}
    return data

def get_recent_orders(db: Session):
    orders = db.query(models.Order).order_by(
        models.Order.created_at.desc()
    ).limit(10).all()
    return orders

# ─── CUSTOMERS ────────────────────────────────────────────────────────────────
def get_customers(db: Session, skip=0, limit=100):
    # Bug fix: exclude soft-deleted customers
    return db.query(models.Customer).filter(models.Customer.is_deleted == False).offset(skip).limit(limit).all()

def get_customer(db: Session, customer_id: int):
    return db.query(models.Customer).filter(models.Customer.id == customer_id).first()

def create_customer(db: Session, customer: schemas.CustomerCreate):
    db_customer = models.Customer(**customer.dict())
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer

def update_customer(db: Session, customer_id: int, customer: schemas.CustomerCreate):
    db_customer = get_customer(db, customer_id)
    if not db_customer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Customer not found")
    for k, v in customer.dict().items():
        setattr(db_customer, k, v)
    db.commit()
    db.refresh(db_customer)
    return db_customer

def delete_customer(db: Session, customer_id: int):
    # Bug fix: use soft delete (is_deleted=True) to match main.py behavior
    # Previously this hard-deleted the record causing permanent data loss
    db_customer = get_customer(db, customer_id)
    if db_customer:
        db_customer.is_deleted = True
        db.commit()

# ─── PRODUCTS ─────────────────────────────────────────────────────────────────
def get_products(db: Session, skip=0, limit=100):
    # Bug fix: exclude soft-deleted products
    return db.query(models.Product).filter(models.Product.is_deleted == False).offset(skip).limit(limit).all()

def get_product(db: Session, product_id: int):
    return db.query(models.Product).filter(models.Product.id == product_id).first()

def create_product(db: Session, product: schemas.ProductCreate):
    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def update_product(db: Session, product_id: int, product: schemas.ProductCreate):
    db_product = get_product(db, product_id)
    if not db_product:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Product not found")
    for k, v in product.dict().items():
        setattr(db_product, k, v)
    db.commit()
    db.refresh(db_product)
    return db_product

def delete_product(db: Session, product_id: int):
    # Bug fix: use soft delete (is_deleted=True) to match main.py behavior
    # Previously this hard-deleted the record causing permanent data loss
    db_product = get_product(db, product_id)
    if db_product:
        db_product.is_deleted = True
        db.commit()

# ─── ORDERS ───────────────────────────────────────────────────────────────────
def get_orders(db: Session, skip=0, limit=100, status=None):
    q = db.query(models.Order)
    if status:
        q = q.filter(models.Order.status == status)
    return q.order_by(models.Order.created_at.desc()).offset(skip).limit(limit).all()

def get_order(db: Session, order_id: int):
    return db.query(models.Order).filter(models.Order.id == order_id).first()

def create_order(db: Session, order: schemas.OrderCreate):
    # Calculate totals
    subtotal = sum(item.quantity * item.unit_price for item in order.items)
    total = round(subtotal, 2)

    db_order = models.Order(
        order_number=generate_order_number(),
        customer_id=order.customer_id,
        subtotal=round(subtotal, 2),
        total=total,
        description=order.description,
        priority=order.priority,
        delivery_date=order.delivery_date,
        status="pending"
    )
    db.add(db_order)
    db.flush()

    for item in order.items:
        db_item = models.OrderItem(
            order_id=db_order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_price=round(item.quantity * item.unit_price, 2)
        )
        db.add(db_item)
        # Deduct stock
        product = get_product(db, item.product_id)
        if product:
            product.stock_quantity = max(0, product.stock_quantity - item.quantity)

    db.commit()
    db.refresh(db_order)
    return db_order

def update_order_status(db: Session, order_id: int, status: str):
    db_order = get_order(db, order_id)
    if not db_order:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Order not found")
    db_order.status = status
    db.commit()
    db.refresh(db_order)
    return db_order

def delete_order(db: Session, order_id: int):
    db_order = get_order(db, order_id)
    db.delete(db_order)
    db.commit()

# ─── INVENTORY ────────────────────────────────────────────────────────────────
def get_inventory(db: Session):
    # Bug fix: exclude soft-deleted products from inventory
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

def update_inventory(db: Session, product_id: int, quantity: int):
    product = get_product(db, product_id)
    if not product:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Product not found")
    product.stock_quantity = quantity
    db.commit()
    return {"message": "Inventory updated", "product_id": product_id, "quantity": product.stock_quantity}


# ─── MATERIAL MASTER (RAW MATERIALS) ──────────────────────────────────────────

def get_materials(db: Session, skip=0, limit=100):
    """Retrieve active and non-deleted raw materials from Master."""
    return db.query(models.Material).filter(models.Material.is_deleted == False).offset(skip).limit(limit).all()

def get_material(db: Session, material_id: int):
    """Retrieve raw material by ID."""
    return db.query(models.Material).filter(models.Material.id == material_id).first()

def get_material_by_code(db: Session, code: str):
    """Retrieve raw material by code (useful for uniqueness check)."""
    return db.query(models.Material).filter(
        models.Material.code == code,
        models.Material.is_deleted == False
    ).first()

def create_material(db: Session, material: schemas.MaterialCreate):
    """Create a new raw material in Master catalog."""
    db_material = models.Material(**material.dict())
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    return db_material

def update_material(db: Session, material_id: int, material: schemas.MaterialCreate):
    """Update raw material properties."""
    db_material = get_material(db, material_id)
    if not db_material:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Material not found")
    for k, v in material.dict().items():
        setattr(db_material, k, v)
    db_material.status = "ok" if (db_material.stock_quantity or 0) > (db_material.min_stock_level or 0) else "low"
    db.commit()
    db.refresh(db_material)
    return db_material

def delete_material(db: Session, material_id: int):
    """Soft-delete a raw material."""
    db_material = get_material(db, material_id)
    if db_material:
        db_material.is_deleted = True
        db.commit()

# ─── ORDER TIMELINE AUDIT LOGGING ─────────────────────────────────────────────

def create_timeline_entry(
    db: Session, 
    order_id: int, 
    action: str, 
    user_id: Optional[int], 
    user_name: Optional[str], 
    role: Optional[str], 
    remarks: Optional[str] = None
):
    """Create a timeline logging entry for audit log trail."""
    db_entry = models.OrderTimeline(
        order_id=order_id,
        action=action,
        user_id=user_id,
        user_name=user_name,
        role=role,
        remarks=remarks
    )
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry

