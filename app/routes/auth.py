from dotenv import load_dotenv
import os
import jwt
import bcrypt
import logging
import mysql.connector
from datetime import datetime, timedelta, timezone
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import APIRouter, Depends, HTTPException

from app.models.auth_models import SignupIn, LoginIn, MeOut, TokenOut
from app.db.mysql_pool import get_db

# --- Setup global constants ---

load_dotenv()  # loads .env if present

logger = logging.getLogger("auth")

JWT_ALG = "HS256"
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

security = HTTPBearer()

# --- Auth Routes ---

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/signup", response_model=MeOut, status_code=201)
def signup(body: SignupIn, conn=Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    existing = get_user_by_email(conn, body.email)
    if existing:
        raise HTTPException(409, "Email already registered")
    user_id = create_user(conn, body.email, body.name or "", body.password)
    if not user_id:
        raise HTTPException(409, "Email already registered")
    return MeOut(id=user_id, email=body.email, name=body.name or "")

@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, conn=Depends(get_db)):
    row = get_user_by_email(conn, body.email)
    if not row or not verify_password(body.password, row["password_hash"]):
        logger.warning("Failed login attempt for email=%s", body.email)
        # Generic message → don’t reveal if email exists
        raise HTTPException(401,"Invalid email or password")
    return create_token(row["id"], row["email"])

@router.get("/me", response_model=MeOut)
def me(creds: HTTPAuthorizationCredentials = Depends(security), conn=Depends(get_db)):
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email, name FROM users WHERE id=%s", (uid,))
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(404, "User not found")
    return MeOut(**row)

# --- Authentication Helper Function ---

def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_token(user_id: int, email: str) -> TokenOut:
    exp = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "email": email, "exp": exp}
    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALG)
    return TokenOut(access_token=token, expires_in=JWT_EXPIRE_MINUTES * 60)

def get_user_by_email(conn, email: str):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email, name, password_hash FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    return row

def create_user(conn, email: str, name: str, password: str):
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (%s,%s,%s)",
            (email, name, hash_password(password)),
        )
        user_id = cur.lastrowid
        return user_id
    except mysql.connector.errors.IntegrityError as e:
        logger.error(
            "MySQL error while creating user (email=%s): code=%s, sqlstate=%s, msg=%s",
            email,
            getattr(e, "errno", None),
            getattr(e, "sqlstate", None),
            getattr(e, "msg", str(e)),
        )
        return None
    finally:
        cur.close()