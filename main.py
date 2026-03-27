from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import models, schemas, crud
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
    payload = json.dumps({
        "id": user_id,
        "role": role,
        "ts": datetime.utcnow().isoformat()
    })
    token = base64.b64encode(payload.encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"

def verify_token(token: str):
    try:
        token_part, sig = token.split(".")
        expected = hmac.new(SECRET_KEY.encode(), token_part.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.b64decode(token_part).decode())
    except:
        return None

# ─── DB DEPENDENCY ───────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── CREATE DEFAULT ADMIN ────────────────────────────────
def create_default_admin():
    db = SessionLocal()
    try:
        user = db.query(models.AdminUser).filter(models.AdminUser.email == "admin@erp.com").first()

        if not user:
            admin = models.AdminUser(
                name="Admin",
                email="admin@erp.com",
                hashed_password=hash_password("admin123"),
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("✅ Default admin created: admin@erp.com / admin123")
    finally:
        db.close()

create_default_admin()

# ─── APP INIT ────────────────────────────────────────────
app = FastAPI(title="ERP System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── FRONTEND ROUTES ─────────────────────────────────────
@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))

@app.get("/login")
def login_page():
    return FileResponse(os.path.join(BASE_DIR, "login.html"))

# ─── AUTH ROUTES ─────────────────────────────────────────
@app.post("/api/auth/login")
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.email == req.email).first()

    if not user or user.hashed_password != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")

    token = make_token(user.id, user.role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active   # ✅ ADD THIS
        }
    }

# ─── TEST ROUTE ──────────────────────────────────────────
@app.get("/api/test")
def test():
    return {"status": "ERP running successfully 🚀"}
