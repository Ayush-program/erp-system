from pydantic import BaseModel
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
    gst_number: Optional[str] = None

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

# ─── PRODUCT MATERIAL (Legacy Fixed BOM — kept for compatibility only) ────────

class ProductMaterialCreate(BaseModel):
    material_id: Optional[int] = None
    material_name: Optional[str] = None
    unit: Optional[str] = None
    quantity_per_unit: float = 1.0
    price: Optional[float] = 0.0

class ProductMaterialOut(BaseModel):
    id: int
    parent_product_id: int
    material_id: Optional[int] = None
    material_name: Optional[str] = None
    unit: Optional[str] = None
    quantity_per_unit: float = 1.0
    price: float = 0.0
    stock_quantity: Optional[float] = 0
    min_stock_level: Optional[float] = 0

    class Config:
        from_attributes = True

# ─── PRODUCT ──────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    sku: str
    description: Optional[str] = None
    price: float = 0.0
    cost_price: Optional[float] = None
    stock_quantity: int = 0
    min_stock_level: int = 10
    category_id: Optional[int] = None
    unit: Optional[str] = "pcs"
    product_type: Optional[str] = "FINISHED_GOOD"
    components: List[ProductMaterialCreate] = []

class Product(ProductCreate):
    id: int
    created_at: Optional[datetime] = None
    category: Optional[Category] = None
    components_detail: List[ProductMaterialOut] = []

    class Config:
        from_attributes = True

# ─── MATERIAL MASTER (Standalone Raw Materials Catalog) ───────────────────────

class MaterialCreate(BaseModel):
    name: str
    code: str
    unit: Optional[str] = "pcs"
    stock_quantity: Optional[float] = 0.0
    min_stock_level: Optional[float] = 10.0
    rate: Optional[float] = 0.00
    status: Optional[str] = "ok"
    is_active: Optional[bool] = True

class MaterialOut(BaseModel):
    id: int
    name: str
    code: str
    unit: Optional[str]
    stock_quantity: float
    min_stock_level: float
    rate: float
    status: str
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class MaterialPurchaseRequest(BaseModel):
    quantity: float
    remarks: Optional[str] = None

# ─── ORDER DYNAMIC MATERIAL (Order Materials Grid) ────────────────────────────

class OrderMaterialCreate(BaseModel):
    material_id: int
    required_qty: float
    unit: Optional[str] = "pcs"
    rate: Optional[float] = 0.00
    remarks: Optional[str] = None

class OrderMaterialOut(BaseModel):
    id: int
    order_id: int
    material_id: int
    material_name: Optional[str] = None
    material_code: Optional[str] = None
    required_qty: float
    used_qty: float
    unit: Optional[str]
    rate: float
    amount: float
    remarks: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

# ─── ORDER ITEM ───────────────────────────────────────────────────────────────

class OrderItemMaterialOut(BaseModel):
    material_id: int
    material_name: Optional[str] = None
    quantity_per_unit: float

    class Config:
        from_attributes = True

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: float
    unit: Optional[str] = "pcs"
    materials: Optional[List[OrderMaterialCreate]] = []
    description: Optional[str] = None

class OrderItem(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float
    total_price: float
    unit: Optional[str] = "pcs"
    description: Optional[str] = None
    product: Optional[Product] = None
    materials: List[OrderItemMaterialOut] = []
    order_materials: List[OrderMaterialOut] = []

    class Config:
        from_attributes = True

# ─── ORDER DYNAMIC EXTRA ITEM (Extra Items Grid) ──────────────────────────────

class OrderExtraItemCreate(BaseModel):
    item_name: str
    quantity: Optional[float] = 1.0
    price: float
    amount: Optional[float] = None

class OrderExtraItemOut(BaseModel):
    id: int
    order_id: int
    item_name: str
    quantity: float
    price: float
    amount: float
    created_at: Optional[datetime]

    class Config:
        from_attributes = True

# ─── ORDER TIMELINE (History trail logs) ──────────────────────────────────────

class OrderTimelineOut(BaseModel):
    id: int
    order_id: int
    action: str
    user_id: Optional[int]
    user_name: Optional[str]
    role: Optional[str]
    timestamp: datetime
    remarks: Optional[str]

    class Config:
        from_attributes = True

# ─── ORDER ────────────────────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    customer_id: int
    items: List[OrderItemCreate]
    materials: Optional[List[OrderMaterialCreate]] = []
    extra_items: Optional[List[OrderExtraItemCreate]] = []
    description: Optional[str] = None
    priority: Optional[str] = "medium"
    delivery_date: Optional[date] = None

class OrderFull(BaseModel):
    id: int
    order_number: str
    customer_id: int
    status: str
    subtotal: float
    total: float
    description: Optional[str] = None
    priority: str = "medium"
    order_date: Optional[datetime] = None
    delivery_date: Optional[date] = None
    customer: Optional[Customer] = None
    items: List[OrderItem] = []
    order_materials: List[OrderMaterialOut] = []
    extra_items: List[OrderExtraItemOut] = []
    timeline: List[OrderTimelineOut] = []

    class Config:
        from_attributes = True

# ─── INVENTORY CHECK DTO ──────────────────────────────────────────────────────

class InventoryCheckItem(BaseModel):
    material_id: int
    material_name: str
    material_code: str
    required_qty: float
    available_qty: float
    shortage_qty: float
    status: str  # 'ok' or 'shortage'

class InventoryCheckResponse(BaseModel):
    order_id: int
    can_approve: bool
    items: List[InventoryCheckItem]

# ─── MISC ─────────────────────────────────────────────────────────────────────

class StatusUpdate(BaseModel):
    status: str
    remarks: Optional[str] = None

class InventoryUpdate(BaseModel):
    quantity: int

# ─── AUTH ──────────────────────────────────────────────────────────────────────

class AdminUserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "sales"

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
