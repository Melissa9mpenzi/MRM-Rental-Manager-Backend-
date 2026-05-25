from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.schemas.auth import UserRegister

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        if not plain or not hashed:
            return False
        try:
            return pwd_context.verify(plain, hashed)
        except (ValueError, TypeError):
            return False

    def set_password(self, db: Session, user: User, password: str):
        user.password_hash = self.hash_password(password)
        db.commit()

    def create_user(
        self,
        db: Session,
        payload: UserRegister,
        verification_token: str,
        token_expiry: datetime,
        *,
        verification_otp: Optional[str] = None,
    ) -> User:
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            phone=payload.phone,
            role=payload.role,
            password_hash=self.hash_password(payload.password),
            email_verified=False,
            trusted_for_commerce=False,
            kyc_review_status="none",
            verification_token=verification_token,
            verification_token_expiry=token_expiry,
            verification_otp=verification_otp,
            verification_otp_expiry=token_expiry if verification_otp else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def authenticate(self, db: Session, email: str, password: str) -> Optional[User]:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return None
        if not self.verify_password(password, user.password_hash):
            return None
        if getattr(user, "gov_suspended", False):
            return None
        return user

    def create_access_token(self, user_id: int) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
        return jwt.encode(
            {"sub": str(user_id), "exp": expire, "type": "access"},
            settings.secret_key,
            algorithm=settings.algorithm,
        )

    def create_refresh_token(self, user_id: int) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        return jwt.encode(
            {"sub": str(user_id), "exp": expire, "type": "refresh"},
            settings.secret_key,
            algorithm=settings.algorithm,
        )

    def create_tokens(self, db: Session, user: User) -> dict:
        access  = self.create_access_token(user.id)
        refresh = self.create_refresh_token(user.id)
        user.refresh_token = refresh
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "user": user,
        }

    def decode_token(self, token: str) -> Optional[int]:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
            user_id = payload.get("sub")
            return int(user_id) if user_id else None
        except JWTError:
            return None


auth_service = AuthService()