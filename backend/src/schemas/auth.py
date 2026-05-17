from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr | None = None
    password: str
    full_name: str
    role: str  # public registration only accepts "caregiver"


class LoginRequest(BaseModel):
    identifier: str
    password: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    email: str | None = None
    username: str | None = None
    full_name: str


class UserOut(BaseModel):
    id: int
    email: str | None = None
    username: str | None = None
    full_name: str
    role: str

    class Config:
        from_attributes = True
