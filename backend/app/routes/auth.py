from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password, require_user, verify_password
from app.db import get_db
from app.models.user import User

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=255)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=255)


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    is_admin: bool
    is_active: bool
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_username(username: str) -> str:
    return username.strip()


def _serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(payload.email)
    username = _normalize_username(payload.username)

    if not email or not username:
        raise HTTPException(status_code=400, detail="Email and username are required")

    existing = await db.execute(
        select(User).where(
            or_(func.lower(User.email) == email, func.lower(User.username) == username.lower())
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email or username already in use")

    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return AuthResponse(
        access_token=create_access_token(user.id, user.is_admin),
        user=_serialize_user(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(payload.email)
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    return AuthResponse(
        access_token=create_access_token(user.id, user.is_admin),
        user=_serialize_user(user),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(require_user)):
    return _serialize_user(current_user)
