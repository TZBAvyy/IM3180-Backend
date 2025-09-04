from pydantic import BaseModel, EmailStr
from typing import Optional

# --- Authentication Models ---

class SignupIn(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = ""

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class MeOut(BaseModel):
    id: int
    email: EmailStr
    name: str

