import os
import jwt
import bcrypt
import logging
import mysql.connector
from datetime import datetime, timedelta, timezone
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import APIRouter, Depends, HTTPException

from app.models.auth_models import SignupIn, LoginIn, MeOut, TokenOut
from app.models.error_models import HTTPError
from app.db.mysql_pool import get_db

from fastapi import UploadFile, File, Form
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from pydantic import BaseModel

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

class ForgotPasswordIn(BaseModel):
    email: str


class ProfileUpdateIn(BaseModel):
    name: str
    email: str


class ResetPasswordIn(BaseModel):
    email: str
    reset_token: str
    new_password: str


S3_BUCKET = os.getenv("AWS_S3_BUCKET_NAME", "trip-opt-bucket2")
S3_REGION = os.getenv("AWS_REGION", "ap-southeast-2")
s3_client = boto3.client("s3", region_name=S3_REGION)

# --- Setup global constants ---

logger = logging.getLogger("auth")

JWT_ALG = "HS256"
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

security = HTTPBearer()
# --- Function for Email Sending ---

# --- Email Setup ---
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))


def send_reset_email(to_email: str, reset_link: str):
    """Send a password reset email using Gmail SMTP."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.error("Email credentials not configured properly.")
        raise HTTPException(500, "Email sending is not configured.")

    subject = "Trip Planner - Password Reset Request"
    text_body = f"""
    You requested to reset your password.
    Click the link below to reset it (valid for 15 minutes):

    {reset_link}

    If you did not request this, you can safely ignore this message.
    """
    html_body = f"""
    <html>
      <body>
        <p>Hi there,</p>
        <p>Click below to reset your password (valid for 15 minutes):</p>
        <p><a href="{reset_link}">{reset_link}</a></p>
        <p>If you didn’t request this, just ignore this email.</p>
        <br>
        <p>— Trip Planner Team</p>
      </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr(("Trip Planner", EMAIL_SENDER))
        msg["To"] = to_email
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)

        logger.info(f"Password reset email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        raise HTTPException(500, "Failed to send reset email")


# --- Auth Routes ---

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=201, responses={
    201: {"model": MeOut, "description": "Successful Creation"},
    400: {"model": HTTPError, "description": "Password < 8 characters"},
    409: {"model": HTTPError, "description": "Email already registered"}
})
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


@router.post("/login", responses={
    200: {"model": TokenOut, "description": "Successful Response"},
    401: {"model": HTTPError, "description": "Invalid email or password"}
})
def login(body: LoginIn, conn=Depends(get_db)):
    row = get_user_by_email(conn, body.email)
    if not row or not verify_password(body.password, row["password_hash"]):
        logger.warning("Failed login attempt for email=%s", body.email)
        raise HTTPException(401, "Invalid email or password")
    return create_token(row["id"], row["email"])


@router.get("/me", responses={
    200: {"model": MeOut, "description": "Successful Response"},
    401: {"model": HTTPError, "description": "Invalid or expired token"},
    404: {"model": HTTPError, "description": "User not found"}
})
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


@router.get("/profile-picture", responses={
    200: {"description": "Returns user's profile picture URL"},
    401: {"model": HTTPError, "description": "Invalid or expired token"},
    404: {"model": HTTPError, "description": "User not found or no picture set"}
})
def get_profile_picture(creds: HTTPAuthorizationCredentials = Depends(security), conn=Depends(get_db)):
    """Return the user's current profile picture URL."""
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT profile_picture_url FROM users WHERE id=%s", (uid,))
    row = cur.fetchone()
    cur.close()

    if not row or not row["profile_picture_url"]:
        raise HTTPException(404, "Profile picture not found")

    return {"profile_picture_url": row["profile_picture_url"]}


@router.get("/profile", responses={
    200: {"description": "Combined user profile info"},
    401: {"model": HTTPError, "description": "Invalid or expired token"},
    404: {"model": HTTPError, "description": "User not found"}
})
def get_full_profile(creds: HTTPAuthorizationCredentials = Depends(security), conn=Depends(get_db)):
    """Return combined user info including profile picture."""
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email, name, profile_picture_url FROM users WHERE id=%s", (uid,))
    row = cur.fetchone()
    cur.close()

    if not row:
        raise HTTPException(404, "User not found")

    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "profile_picture_url": row.get("profile_picture_url")
    }


@router.post("/reset-password", responses={
    200: {"description": "Password reset successful"},
    400: {"model": HTTPError, "description": "Invalid token or bad input"},
    404: {"model": HTTPError, "description": "User not found"},
})
def reset_password(body: ResetPasswordIn, conn=Depends(get_db)):
    """Verify reset token, match email, and update password."""
    try:
        payload = jwt.decode(body.reset_token, SECRET_KEY, algorithms=[JWT_ALG])
        if payload.get("action") != "password_reset":
            raise HTTPException(400, "Invalid token action")
        uid = int(payload["sub"])
        token_email = payload.get("email")
    except jwt.ExpiredSignatureError:
        raise HTTPException(400, "Reset token expired")
    except Exception:
        raise HTTPException(400, "Invalid reset token")

    # --- Validate input ---
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    # Optional: include email in the request model and match it
    # Update ResetPasswordIn accordingly:
    # class ResetPasswordIn(BaseModel):
    #     email: str
    #     reset_token: str
    #     new_password: str

    # Validate email matches token email
    if hasattr(body, "email"):
        if body.email.lower() != token_email.lower():
            raise HTTPException(400, "Email does not match reset token")

    # --- Verify that user exists ---
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user:
        cur.close()
        raise HTTPException(404, "User not found")

    # --- Update password ---
    cur.execute(
        "UPDATE users SET password_hash=%s WHERE id=%s",
        (hash_password(body.new_password), uid)
    )
    conn.commit()
    cur.close()

    return {"message": "Password reset successful"}


@router.post("/forgot-password", responses={
    200: {"description": "Password reset email sent"},
    404: {"model": HTTPError, "description": "User not found"},
})
def forgot_password(body: ForgotPasswordIn, conn=Depends(get_db)):
    """Generate a short-lived password reset token and email it to the user."""
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email FROM users WHERE email=%s", (body.email,))
    user = cur.fetchone()
    cur.close()

    if not user:
        raise HTTPException(404, "User not found")

    # Create reset token
    exp = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"sub": str(user["id"]), "email": user["email"], "exp": exp, "action": "password_reset"}
    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALG)

    # Build the frontend link
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    reset_link = f"{FRONTEND_URL}/PasswordReset?token={token}"

    # Send email
    send_reset_email(user["email"], reset_link)

    return {"message": "Password reset email sent successfully."}


@router.put("/update-profile-picture", responses={
    200: {"description": "Profile picture updated successfully"},
    400: {"model": HTTPError, "description": "Upload failed"},
    401: {"model": HTTPError, "description": "Invalid or expired token"},
})
def update_profile_picture(
    creds: HTTPAuthorizationCredentials = Depends(security),
    file: UploadFile = File(...),
    conn=Depends(get_db)
):
    """Upload a new profile picture to S3 and update the user's URL."""
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    try:
        key = f"user-{uid}/{file.filename}"
        s3_client.upload_fileobj(file.file, S3_BUCKET, key)
        s3_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}"
    except (BotoCoreError, ClientError) as e:
        logger.error(f"S3 upload error for user {uid}: {e}")
        raise HTTPException(400, "Failed to upload profile picture")

    cur = conn.cursor()
    cur.execute("UPDATE users SET profile_picture_url=%s WHERE id=%s", (s3_url, uid))
    conn.commit()
    cur.close()

    return {"message": "Profile picture updated", "profile_picture_url": s3_url}


@router.put("/update-profile", responses={
    200: {"description": "Profile updated successfully"},
    400: {"model": HTTPError, "description": "Invalid input"},
    401: {"model": HTTPError, "description": "Invalid or expired token"},
    409: {"model": HTTPError, "description": "Email already taken"},
})
def update_profile(
    name: str = Form(...),
    email: str = Form(...),
    creds: HTTPAuthorizationCredentials = Depends(security),
    conn=Depends(get_db),
):
    """Update user's name and email."""
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM users WHERE email=%s AND id!=%s", (email, uid))
    existing = cur.fetchone()

    if existing:
        cur.close()
        raise HTTPException(409, "Email already taken")

    cur.execute("UPDATE users SET name=%s, email=%s WHERE id=%s", (name, email, uid))
    conn.commit()
    cur.close()

    return {"message": "Profile updated successfully", "name": name, "email": email}


# --- Authentication Helper Functions ---

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
