from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole


class CreateGovInvitationBody(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: Optional[str] = None
    agency: str = Field(description="nira | kcca | ura | platform")
    role: UserRole
    work_id: str = Field(min_length=3, max_length=64)


class AcceptGovInvitationBody(BaseModel):
    token: str
    password: str = Field(min_length=8)
    security_pin: str = Field(min_length=4, max_length=8)
    work_id_confirm: str = Field(min_length=3, max_length=64)


class GovernmentLoginBody(BaseModel):
    email: EmailStr
    password: str


class GovernmentTwoFaBody(BaseModel):
    code: str = Field(min_length=1, max_length=16)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, v: object) -> str:
        digits = "".join(c for c in str(v or "") if c.isdigit())
        if len(digits) < 6:
            raise ValueError("Enter the 6-digit code from your email.")
        return digits[:6]
