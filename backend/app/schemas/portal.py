"""门户核心 Schema（P2；api-spec §3.2/§4.2）。"""

from pydantic import BaseModel, Field, field_validator


# ---- 分组（M03-2/4）----
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = None
    icon_type: str | None = Field(default=None, pattern="^(emoji|element|upload)$")
    sort: int = 0
    collapsed: bool = False

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("分组名不能为空")
        return v


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    icon: str | None = None
    icon_type: str | None = Field(default=None, pattern="^(emoji|element|upload)$")
    sort: int | None = None
    collapsed: bool | None = None


class CategoryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    icon: str | None
    icon_type: str | None
    sort: int
    collapsed: bool


class SortItem(BaseModel):
    id: int
    sort: int


class CategorySortRequest(BaseModel):
    items: list[SortItem]


# ---- 访问入口（M04-1~6）----
class AppUrlCreate(BaseModel):
    access_type: str = Field(pattern="^(domain|lan|ssh|vpn|custom)$")
    url: str = Field(min_length=1, max_length=2048)
    label: str = Field(default="", max_length=64)
    sort: int | None = None  # None → 追加到末尾

    @field_validator("url")
    @classmethod
    def _url_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("url 不能为空")
        return v

    @field_validator("label")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class AppUrlUpdate(BaseModel):
    access_type: str | None = Field(default=None, pattern="^(domain|lan|ssh|vpn|custom)$")
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    label: str | None = Field(default=None, max_length=64)
    sort: int | None = None


class AppUrlOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    app_id: int
    access_type: str
    url: str
    label: str
    sort: int


# ---- 应用（M03-1/4）----
class AppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    icon: str | None = None
    icon_type: str = Field(default="url", pattern="^(url|upload|emoji|element)$")
    category_id: int | None = None
    sort: int = 0
    enabled: bool = True
    health_type: str = Field(default="", pattern="^(|http|tcp|keyword)$")
    health_target: str | None = Field(default=None, max_length=512)
    health_interval: int = Field(default=60, ge=10, le=86400)
    open_mode: str = Field(default="newtab", pattern="^(newtab|current|iframe)$")
    visibility: str = Field(default="all", pattern="^(all|admin|users)$")
    tags: list[str] = []
    remark: str = ""
    doc_url: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("应用名不能为空")
        return v


class AppUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    icon: str | None = None
    icon_type: str | None = Field(default=None, pattern="^(url|upload|emoji|element)$")
    category_id: int | None = None
    sort: int | None = None
    enabled: bool | None = None
    health_type: str | None = Field(default=None, pattern="^(|http|tcp|keyword)$")
    health_target: str | None = Field(default=None, max_length=512)
    health_interval: int | None = Field(default=None, ge=10, le=86400)
    open_mode: str | None = Field(default=None, pattern="^(newtab|current|iframe)$")
    visibility: str | None = Field(default=None, pattern="^(all|admin|users)$")
    favorite: bool | None = None
    tags: list[str] | None = None
    remark: str | None = None
    doc_url: str | None = None


class AppOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str
    icon: str | None
    icon_type: str
    category_id: int | None
    sort: int
    enabled: bool
    health_type: str
    health_target: str | None
    health_interval: int
    open_mode: str
    visibility: str
    favorite: bool
    tags: list[str]
    remark: str
    doc_url: str | None
    urls: list[AppUrlOut] = []


class AppSortItem(SortItem):
    category_id: int | None = None


class AppSortRequest(BaseModel):
    items: list[AppSortItem]


# ---- 图标（M03-5/6）----
class IconUploadRequest(BaseModel):
    """图标以 base64 随加密信封上传（P24 全链路密文化：不使用明文 multipart）。"""

    filename: str = ""
    data: str


# ---- 导入导出（M03-13，格式 v1；id 全保留以便 round-trip 一致）----
class ExportAppUrl(BaseModel):
    access_type: str = Field(pattern="^(domain|lan|ssh|vpn|custom)$")
    url: str
    label: str = ""
    sort: int = 0


class ExportApp(BaseModel):
    id: int
    name: str
    description: str = ""
    icon: str | None = None
    icon_type: str = Field(default="url", pattern="^(url|upload|emoji|element)$")
    category_id: int | None = None
    sort: int = 0
    enabled: bool = True
    health_type: str = Field(default="", pattern="^(|http|tcp|keyword)$")
    health_target: str | None = None
    health_interval: int = Field(default=60, ge=10, le=86400)
    open_mode: str = Field(default="newtab", pattern="^(newtab|current|iframe)$")
    visibility: str = Field(default="all", pattern="^(all|admin|users)$")
    favorite: bool = False
    tags: list[str] = []
    remark: str = ""
    doc_url: str | None = None
    urls: list[ExportAppUrl] = []


class ExportCategory(BaseModel):
    id: int
    name: str
    icon: str | None = None
    icon_type: str | None = None
    sort: int = 0
    collapsed: bool = False


class ExportPayload(BaseModel):
    version: int = 1
    exported_at: str | None = None
    categories: list[ExportCategory] = []
    apps: list[ExportApp] = []


class ImportResult(BaseModel):
    categories: int
    apps: int
    urls: int
