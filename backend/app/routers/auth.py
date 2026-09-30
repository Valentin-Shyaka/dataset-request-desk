from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import COOKIE_NAME, get_current_user
from app.models import User
from app.schemas import LoginIn, UserOut
from app.security import DUMMY_HASH, create_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    password_ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not password_ok or not user.is_active:
        # Same message for every failure so the response does not reveal which emails exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    response.set_cookie(
        COOKIE_NAME,
        create_token(user.id),
        httponly=True,      # JavaScript cannot read it, so an XSS bug cannot steal the session
        samesite="strict",  # the browser won't send it on cross-site requests (CSRF protection)
        secure=settings.cookie_secure,
        max_age=settings.token_ttl_minutes * 60,
    )
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
