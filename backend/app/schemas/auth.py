"""认证相关 Schema（P1）。"""

import re

from pydantic import BaseModel, field_validator

_USERNAME_RE = re.compile(r"^[\w\-]{3,32}$")
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


def validate_username(v: str) -> str:
    if not _USERNAME_RE.match(v):
        raise ValueError("用户名需 3~32 位，仅限字母/数字/下划线/中划线")
    return v


def validate_password(v: str) -> str:
    if not _PASSWORD_RE.match(v):
        raise ValueError("密码至少 8 位，且同时包含字母与数字")
    return v


class InitRequest(BaseModel):
    username: str
    password: str
    site_name: str = "Portal"

    _v_username = field_validator("username")(validate_username)
    _v_password = field_validator("password")(validate_password)


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

    _v_new = field_validator("new_password")(validate_password)


class UserInfo(BaseModel):
    id: int
    username: str
    role: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserInfo
