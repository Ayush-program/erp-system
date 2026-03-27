from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, date

# ─── CUSTOMER ─────────────────────────────────────────────────────────────────
class CustomerCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = "India"

class Customer(CustomerCreate):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# ─── CATEGORY ─────────────────────────────────────────────────────────────────
class CategoryBase(BaseModel):
    name: str
    description: Optional[str] = None

class Category(CategoryBase):
    id: int
    class Config:
        from_attributes = True

# ─── PRODUCT ──────────────────────────────────────────────────────────────────
class ProductCreate(BaseModel):
    name: str
    sku: str
    description: Optional[str] = None
    price: float
    cost_price: Optional[float] = None
    stock_quantity: int = 0
    min_stock_level: int = 10
    category_id: Optional[int] = None
    unit: Optional[str] = "pcs"

class Product(ProductCreate):
    id: int
    created_at: Optional[datetime] = None
    category: Optional[Category] = None

    class Config:
        from_attributes = True

# ─── ORDER ITEM ───────────────────────────────────────────────────────────────
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: float

class OrderItem(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float
    total_price: float
    product: Optional[Product] = None

    class Config:
        from_attributes = True

# ─── ORDER ────────────────────────────────────────────────────────────────────
class OrderCreate(BaseModel):
    customer_id: int
    items: List[OrderItemCreate]
    discount: Optional[float] = 0
    tax: Optional[float] = 18  # GST %
    notes: Optional[str] = None
    delivery_date: Optional[date] = None

class OrderFull(BaseModel):
    id: int
    order_number: str
    customer_id: int
    status: str
    subtotal: float
    tax: float
    discount: float
    total: float
    notes: Optional[str] = None
    order_date: Optional[datetime] = None
    delivery_date: Optional[date] = None
    customer: Optional[Customer] = None
    items: List[OrderItem] = []

    class Config:
        from_attributes = True

# ─── MISC ─────────────────────────────────────────────────────────────────────
class StatusUpdate(BaseModel):
    status: str

class InventoryUpdate(BaseModel):
    quantity: int

# ─── AUTH ──────────────────────────────────────────────────────────────────────
class AdminUserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "subadmin"

class AdminUserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: AdminUserOut
