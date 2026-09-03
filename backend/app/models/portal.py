"""门户核心模型：分组/应用/访问入口（api-spec §3.2；dev-plan P2）。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    """应用分组（M03-2）。"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # icon: emoji 字符（历史数据）/ Element Plus 图标名，随 icon_type 区分
    icon: Mapped[str | None] = mapped_column(Text, default=None)
    # icon_type: NULL 视为历史 emoji；新数据走 element
    icon_type: Mapped[str | None] = mapped_column(String(16), default=None)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    collapsed: Mapped[bool] = mapped_column(default=False)  # 首页折叠默认态（P4 使用）

    apps: Mapped[list["App"]] = relationship(back_populates="category")


class App(Base, TimestampMixin):
    """应用（M03-1）：门户管理的核心对象。"""

    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    # icon: URL 路径 / 外链 / emoji 字符 / Element Plus 图标名（icon_type=element）
    icon: Mapped[str | None] = mapped_column(Text, default=None)
    # icon_type: url / upload / emoji / element
    icon_type: Mapped[str] = mapped_column(String(16), default="url")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), default=None, index=True
    )
    sort: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    # 探活配置（P6 起使用，字段先行落地）
    health_type: Mapped[str] = mapped_column(String(16), default="")  # ''/http/tcp/keyword
    health_target: Mapped[str | None] = mapped_column(String(512), default=None)  # URL 或 host:port
    health_interval: Mapped[int] = mapped_column(Integer, default=60)
    open_mode: Mapped[str] = mapped_column(String(16), default="newtab")  # newtab/current/iframe
    visibility: Mapped[str] = mapped_column(String(16), default="all")  # all/users/admin/public
    # visibility=users 时生效：可访问的用户 id 数组（JSON）
    visible_users: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    favorite: Mapped[bool] = mapped_column(default=False)  # P4 收藏置顶使用
    tags: Mapped[list] = mapped_column(JSON, default=list)  # M2 标签；JSON 跨库兼容（P23）
    remark: Mapped[str] = mapped_column(Text, default="")
    doc_url: Mapped[str | None] = mapped_column(Text, default=None)
    # 回收站（M2 提供恢复/彻底删除入口，删除动作本身在 P2 落地）
    deleted: Mapped[bool] = mapped_column(default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    category: Mapped[Category | None] = relationship(back_populates="apps")
    urls: Mapped[list["AppUrl"]] = relationship(
        back_populates="app",
        cascade="all, delete-orphan",
        order_by="AppUrl.sort, AppUrl.id",
    )


class AppUrl(Base, TimestampMixin):
    """访问入口（M04-1~6）：一个应用可挂 1..N 个不同网络环境的地址。"""

    __tablename__ = "app_urls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    access_type: Mapped[str] = mapped_column(String(16))  # domain/lan/ssh/vpn/custom
    url: Mapped[str] = mapped_column(String(2048))
    label: Mapped[str] = mapped_column(String(64), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)

    app: Mapped[App] = relationship(back_populates="urls")


class Icon(Base, TimestampMixin):
    """图标库实体（v2）：内置与自定义图标统一入库管理，全部支持改名/换图/删除。

    - source='builtin'：来自 Element Plus 图标集（element_name 渲染矢量组件）；
      删除为软删除（hidden=True），前端重新播种时不会复活
    - source='custom'：用户上传图片（path 指向 /icons/ 静态文件）；删除为物理删除
    - builtin 也可上传自定义图片覆盖显示（path 置位后优先渲染图片）
    - 引用保护：被 apps/categories 引用（icon_type='element'/'upload'）时禁止删除
    """

    __tablename__ = "icons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    # source: builtin / custom
    source: Mapped[str] = mapped_column(String(16), default="custom")
    element_name: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    # path: 覆盖图（builtin）/ 自定义图（custom）的静态路径
    path: Mapped[str | None] = mapped_column(String(256), unique=True, default=None)
    hidden: Mapped[bool] = mapped_column(default=False)  # 内置图标软删除标记
