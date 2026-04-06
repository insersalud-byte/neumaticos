from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import sys

def get_base_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')
        if os.path.isdir(internal_dir):
            return internal_dir
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Neon PostgreSQL (produccion)
NEON_DATABASE_URL = "postgresql://napi_97em6fe0kgzln0j88trm4jcnnk2qnlp7z6l7fw6iuu7213hqwj5zgv8xcdrwvkw0@ep-royal-violence-92041440.us-east-2.aws.neon.tech/neondb?sslmode=require"

# Usar PostgreSQL en produccion (VPS o si existe variable NEON_URL)
USE_NEON = os.environ.get("USE_NEON", "true").lower() == "true"

if USE_NEON:
    SQLALCHEMY_DATABASE_URL = NEON_DATABASE_URL
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
else:
    DB_PATH = os.path.join(get_base_path(), "giorda.db")
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
