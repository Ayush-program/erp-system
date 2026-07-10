from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Fall back to local SQLite if DATABASE_URL is not provided
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    db_dir = os.path.dirname(os.path.abspath(__file__))
    DATABASE_URL = f"sqlite:///{os.path.join(db_dir, 'erp_local.db')}"

# SQLite needs check_same_thread=False; other DBs don't support that arg
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()