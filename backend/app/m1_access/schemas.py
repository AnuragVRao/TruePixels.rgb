"""Pydantic schemas for Module M1 request/response validation."""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120, description="Full name after trimming")
    email: EmailStr = Field(..., description="Unique email address")
    password: str = Field(..., min_length=10, description="Password meeting security criteria")

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        trimmed = v.strip()
        if len(trimmed) < 2 or len(trimmed) > 120:
            raise ValueError("Full name must be between 2 and 120 characters after trimming.")
        return trimmed

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserRegisterResponse(BaseModel):
    user_id: int
    message: str = "Account created successfully."
    requires_2fa: bool = False


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserLoginResponse(BaseModel):
    token: str = ""
    role: Literal["User", "Admin"]
    expires_at: datetime
    user_id: int
    requires_otp: bool = False


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)
    # INTEGRATION (changes.md 6.15): which challenge this code redeems.
    purpose: Literal["login", "register"] = "login"


class OTPVerifyResponse(BaseModel):
    message: str
    token: Optional[str] = None
    role: Optional[Literal["User", "Admin"]] = None
    expires_at: Optional[datetime] = None
    user_id: Optional[int] = None


class UserStatusUpdateRequest(BaseModel):
    action: Literal["enable", "disable", "remove"]


class UserStatusUpdateResponse(BaseModel):
    user_id: int
    account_status: Literal["active", "disabled", "removed"]


class UserListItemResponse(BaseModel):
    user_id: int
    full_name: str
    email: str
    role: Literal["User", "Admin"]
    account_status: Literal["active", "disabled", "removed"]
    registered_at: datetime
    is_email_verified: bool

    model_config = ConfigDict(from_attributes=True)


class ImageUploadResponse(BaseModel):
    image_id: int
    validation_status: Literal["valid", "invalid", "pending"]
    content_sha256: str
    width: Optional[int] = None
    height: Optional[int] = None
    file_format: str


class ImageMetadataResponse(BaseModel):
    image_id: int
    user_id: int
    file_reference: str
    content_sha256: str
    file_format: str
    file_size: int
    width: Optional[int] = None
    height: Optional[int] = None
    upload_timestamp: datetime
    validation_status: str
    rejection_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
