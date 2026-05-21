from typing import Optional

from pydantic import BaseModel, EmailStr, Field

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
    code: str = Field(min_length=6, max_length=8)
