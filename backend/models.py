from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum, Date, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

# ─── ENUMS ───────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin = "admin"
    sales = "sales"
    inventory = "inventory"
    manufacturing = "manufacturing"

class ProductType(str, enum.Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    FINISHED_GOOD = "FINISHED_GOOD"

class OrderStatus(str, enum.Enum):
    # ── Sales Department Actions ─────────────────────────────────
    pending             = "pending"              # Initial state on creation
    order_confirmed     = "order_confirmed"      # Sales confirms the order
    payment_received    = "payment_received"     # Payment collected
    ready_to_process    = "ready_to_process"     # Triggers inventory check → enters Manufacturing
    start_processing    = "start_processing"     # Manufacturing is actively working
    ready_to_dispatch   = "ready_to_dispatch"    # Goods ready, pending shipment
    dispatched          = "dispatched"           # Shipped → moves to Completed Orders list
    paused              = "paused"               # Temporary hold
    other               = "other"               # Miscellaneous intermediate state
    cancelled           = "cancelled"            # Order cancelled
    # ── Legacy / compatibility ───────────────────────────────────
    completed           = "completed"            # Legacy completed state
    need_purchase       = "need_purchase"        # Legacy: material shortage flagged
    inventory_approved  = "inventory_approved"   # Legacy: inventory approved
    manufacturing       = "manufacturing"        # Legacy: manufacturing running
    manufactured        = "manufactured"         # Legacy: manufactured done

# ─── ADMIN USER ───────────────────────────────────────────────────────────────

class AdminUser(Base):
    __tablename__ = "admin_users"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(255), nullable=False)
    email           = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(String(50), default="sales")   # default to sales/lowest privilege
    is_active       = Column(Boolean, default=True)
    created_by      = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

# ─── CATEGORY ────────────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False)
    description = Column(Text)

    products = relationship("Product", back_populates="category")

# ─── PRODUCT (Finished Goods Master) ─────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(255), nullable=False)
    sku             = Column(String(100), unique=True, index=True)
    price           = Column(Float, nullable=False, default=0.0)
    description     = Column(Text)
    cost_price      = Column(Float)
    stock_quantity  = Column(Integer, default=0)
    min_stock_level = Column(Integer, default=10)
    category_id     = Column(Integer, ForeignKey("categories.id"), nullable=True)
    unit            = Column(String(50), default="pcs")
    product_type    = Column(String(20), default="FINISHED_GOOD", nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    is_deleted      = Column(Boolean, default=False)

    category      = relationship("Category", back_populates="products")
    order_items   = relationship("OrderItem", back_populates="product")
    
    # Legacy fixed BOM relationship
    components    = relationship(
        "ProductMaterial",
        foreign_keys="[ProductMaterial.parent_product_id]",
        back_populates="parent_product",
        cascade="all, delete-orphan"
    )

# ─── PRODUCT MATERIAL (Legacy BOM — kept for compatibility only) ──────────────

class ProductMaterial(Base):
    __tablename__ = "product_materials"

    id                = Column(Integer, primary_key=True, index=True)
    parent_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    material_id       = Column(Integer, ForeignKey("materials.id"), nullable=True)
    material_name     = Column(String(255), nullable=True)
    unit              = Column(String(50), nullable=True)
    quantity_per_unit = Column(Float, default=1.0)
    price             = Column(Float, default=0.0)
    stock_quantity    = Column(Float, default=0)
    min_stock_level   = Column(Float, default=0)

    parent_product = relationship("Product", foreign_keys=[parent_product_id], back_populates="components")
    material       = relationship("Material")

# ─── CUSTOMER ────────────────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(255), nullable=False)
    email       = Column(String(255), unique=True, index=True)
    phone       = Column(String(50))
    address     = Column(Text)
    city        = Column(String(100))
    country     = Column(String(100), default="India")
    gst_number  = Column(String(20), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    is_deleted  = Column(Boolean, default=False)

    orders = relationship("Order", back_populates="customer")

# ─── MATERIAL MASTER (Raw Material Master) ────────────────────────────────────

class Material(Base):
    __tablename__ = "materials"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(255), nullable=False)
    code            = Column(String(100), unique=True, index=True, nullable=False)
    unit            = Column(String(50), default="pcs")
    stock_quantity  = Column(Float, default=0.0)
    min_stock_level = Column(Float, default=10.0)
    rate            = Column(Float, default=0.00)
    status          = Column(String(50), default="ok")  # 'ok' or 'low'
    is_active       = Column(Boolean, default=True)
    is_deleted      = Column(Boolean, default=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    order_materials = relationship("OrderMaterial", back_populates="material")

# ─── ORDER ───────────────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id                 = Column(Integer, primary_key=True, index=True)
    order_number       = Column(String(50), unique=True, index=True)
    customer_id        = Column(Integer, ForeignKey("customers.id"), nullable=False)
    status             = Column(String(50), default="pending")
    subtotal           = Column(Float, default=0)
    total              = Column(Float, default=0)
    description        = Column(Text)
    priority           = Column(String(50), default="medium")
    inventory_deducted = Column(Boolean, default=False)
    order_date         = Column(DateTime(timezone=True), server_default=func.now())
    delivery_date      = Column(Date, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), onupdate=func.now())

    customer        = relationship("Customer", back_populates="orders")
    items           = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    order_materials = relationship("OrderMaterial", back_populates="order", cascade="all, delete-orphan")
    extra_items     = relationship("OrderExtraItem", back_populates="order", cascade="all, delete-orphan")
    timeline        = relationship("OrderTimeline", back_populates="order", cascade="all, delete-orphan")

# ─── ORDER ITEM ──────────────────────────────────────────────────────────────

class OrderItem(Base):
    __tablename__ = "order_items"

    id          = Column(Integer, primary_key=True, index=True)
    order_id    = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id  = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity    = Column(Integer, nullable=False)
    unit_price  = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    unit        = Column(String(50), default="pcs")
    description = Column(Text, nullable=True)

    order           = relationship("Order", back_populates="items")
    product         = relationship("Product", back_populates="order_items")
    materials       = relationship("OrderItemMaterial", back_populates="order_item", cascade="all, delete-orphan")
    order_materials = relationship("OrderMaterial", back_populates="order_item", cascade="all, delete-orphan")

# ─── ORDER ITEM MATERIAL (Legacy BOM Items Mapping — Kept for compatibility) ──

class OrderItemMaterial(Base):
    __tablename__ = "order_item_materials"

    id                = Column(Integer, primary_key=True, index=True)
    order_item_id     = Column(Integer, ForeignKey("order_items.id"), nullable=False)
    material_id       = Column(Integer, ForeignKey("product_materials.id"), nullable=False)
    quantity_per_unit = Column(Float, default=1.0)

    order_item = relationship("OrderItem", back_populates="materials")
    material   = relationship("ProductMaterial")

# ─── ORDER MATERIAL (Make-to-Order Dynamic Materials BOM) ─────────────────────

class OrderMaterial(Base):
    __tablename__ = "order_materials"

    id                  = Column(Integer, primary_key=True, index=True)
    order_id            = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    order_item_id       = Column(Integer, ForeignKey("order_items.id", ondelete="CASCADE"), nullable=True)
    material_id         = Column(Integer, ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False)
    required_qty        = Column(Float, nullable=False, default=0.0)
    used_qty            = Column(Float, default=0.0)
    unit                = Column(String(50), default="pcs")
    rate                = Column(Float, default=0.00)
    amount              = Column(Float, default=0.00)
    remarks             = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    order      = relationship("Order", back_populates="order_materials")
    order_item = relationship("OrderItem", back_populates="order_materials")
    material   = relationship("Material", back_populates="order_materials")

    @property
    def material_name(self):
        return self.material.name if self.material else f"Material #{self.material_id}"

    @property
    def material_code(self):
        return self.material.code if self.material else "-"

# ─── ORDER EXTRA ITEM (Dynamic Extra Items Grid) ──────────────────────────────

class OrderExtraItem(Base):
    __tablename__ = "order_extra_items"

    id         = Column(Integer, primary_key=True, index=True)
    order_id   = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    item_name  = Column(String(255), nullable=False)
    quantity   = Column(Float, nullable=False, default=1.0)
    price      = Column(Float, nullable=False, default=0.00)
    amount     = Column(Float, nullable=False, default=0.00)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="extra_items")

# ─── MANUFACTURING LOG (Tracks start and end logs) ───────────────────────────

class ManufacturingLog(Base):
    __tablename__ = "manufacturing_logs"

    id           = Column(Integer, primary_key=True, index=True)
    order_id     = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    started_at   = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    started_by   = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    completed_by = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    remarks      = Column(Text, nullable=True)

    order             = relationship("Order")
    started_by_user   = relationship("AdminUser", foreign_keys=[started_by])
    completed_by_user = relationship("AdminUser", foreign_keys=[completed_by])

# ─── ORDER TIMELINE (Tracks detailed status history and actions) ─────────────

class OrderTimeline(Base):
    __tablename__ = "order_timeline"

    id         = Column(Integer, primary_key=True, index=True)
    order_id   = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    action     = Column(String(255), nullable=False)
    user_id    = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    user_name  = Column(String(255), nullable=True)
    role       = Column(String(100), nullable=True)
    timestamp  = Column(DateTime(timezone=True), server_default=func.now())
    remarks    = Column(Text, nullable=True)

    order = relationship("Order", back_populates="timeline")
    user  = relationship("AdminUser")
