from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import models, schemas, crud
from database import SessionLocal, engine
import os, hashlib, hmac, base64, json
from datetime import datetime

models.Base.metadata.create_all(bind=engine)

SECRET_KEY = os.getenv("SECRET_KEY", "change-this")

# ─── AUTH HELPERS ───
def hash_password(password: str):
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def make_token(user_id, role):
    payload = json.dumps({"id": user_id, "role": role})
    token = base64.b64encode(payload.encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"

def verify_token(token):
    try:
        token_part, sig = token.split(".")
        expected = hmac.new(SECRET_KEY.encode(), token_part.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.b64decode(token_part).decode())
    except:
        return None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── APP ───
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))

@app.get("/login")
def login_page():
    return FileResponse(os.path.join(BASE_DIR, "login.html"))

# ─── AUTH ───
@app.post("/api/login")
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.email == req.email).first()

    if not user or user.hashed_password != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = make_token(user.id, user.role)
    return {"token": token}

# ─── TEST ROUTE ───
@app.get("/api/test")
def test():
    return {"status": "ERP running successfully 🚀"}