"""自定义图标 Schema（图标库管理）。"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.i18n import t


def _validate_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(t("v.icon_name_empty"))
    return v


def _validate_data(v: Any) -> Any:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(t("v.icon_data_empty"))
    return v


class CustomIconCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    filename: str = ""
    data: str  # base64 图片内容

    _v_name = field_validator("name")(_validate_name)
    _v_data = field_validator("data")(_validate_data)


class CustomIconUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    filename: str = ""
    data: str | None = None  # 提供则更换图片

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str | None) -> str | None:
        return _validate_name(v) if v is not None else v

    @field_validator("data")
    @classmethod
    def _v_data(cls, v: str | None) -> str | None:
        return _validate_data(v) if v is not None else v


class CustomIconOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    path: str
