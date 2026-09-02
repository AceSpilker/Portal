"""首页仪表盘布局模型（M02-2/5；api-spec §3.2 dashboard_layouts；dev-plan P4.2）。"""

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DashboardLayout(Base, TimestampMixin):
    """每用户每标签页一份布局（磁贴顺序/尺寸/分组折叠/区块顺序）。

    layout(JSON) 结构（P4）：
      {"order": [appId...], "sizes": {appId: 1|2}, "collapsed": {categoryId: bool}}
    tab 预留 M02-5 多标签页（当前固定 "default"）；M16-5 移动端独立布局用 tab 区分。
    """

    __tablename__ = "dashboard_layouts"
    __table_args__ = (UniqueConstraint("user_id", "tab", name="uq_layout_user_tab"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tab: Mapped[str] = mapped_column(String(32), default="default")
    sort: Mapped[int] = mapped_column(Integer, default=0)  # M2 多标签页排序预留
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
