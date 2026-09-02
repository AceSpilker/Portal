"""网络环境 Schema（P3；api-spec §3.3/§4.3）。"""

from pydantic import BaseModel, Field, field_validator

from app.core.i18n import t
from app.services.network import compile_cidrs

ACCESS_TYPES = ("domain", "lan", "ssh", "vpn", "custom")


class NetworkProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    match_type: str = Field(default="cidr", pattern="^(cidr|default)$")
    cidrs: list[str] = []
    prefer_types: list[str] = []
    sort: int = 0
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError(t("v.profile_name_empty"))
        return v

    @field_validator("cidrs")
    @classmethod
    def _valid_cidrs(cls, v: list[str], info) -> list[str]:
        if info.data.get("match_type") == "default":
            return []
        v = [c.strip() for c in v if c.strip()]
        if not v:
            raise ValueError(t("v.cidr_required"))
        try:
            compile_cidrs(v)
        except ValueError:
            raise ValueError(t("v.cidr_invalid"))
        return v

    @field_validator("prefer_types")
    @classmethod
    def _valid_prefer(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError(t("v.prefer_duplicated"))
        for item in v:
            if item not in ACCESS_TYPES:
                raise ValueError(t("v.prefer_invalid"))
        return v


class NetworkProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    match_type: str | None = Field(default=None, pattern="^(cidr|default)$")
    cidrs: list[str] | None = None
    prefer_types: list[str] | None = None
    sort: int | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError(t("v.profile_name_empty"))
        return v

    @field_validator("cidrs")
    @classmethod
    def _valid_cidrs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        v = [c.strip() for c in v if c.strip()]
        if not v:
            raise ValueError(t("v.cidr_required"))
        try:
            compile_cidrs(v)
        except ValueError:
            raise ValueError(t("v.cidr_invalid"))
        return v

    @field_validator("prefer_types")
    @classmethod
    def _valid_prefer(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(set(v)) != len(v):
            raise ValueError(t("v.prefer_duplicated"))
        for item in v:
            if item not in ACCESS_TYPES:
                raise ValueError(t("v.prefer_invalid"))
        return v


class NetworkProfileOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    match_type: str
    cidrs: list[str]
    prefer_types: list[str]
    is_default: bool
    sort: int
    enabled: bool


class NetworkProfileSortItem(BaseModel):
    id: int
    sort: int


class NetworkProfileSortRequest(BaseModel):
    items: list[NetworkProfileSortItem]
