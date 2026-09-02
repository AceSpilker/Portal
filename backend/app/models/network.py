"""网络环境模型（M04-7；api-spec §3.3；dev-plan P3.1）。"""

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NetworkProfile(Base, TimestampMixin):
    """网络环境档案（M04-7）：家庭内网/公司/VPN 等环境定义与入口优先顺序。

    - match_type='cidr'：按 cidrs 网段匹配来源 IP（sort, id 顺序，先命中先用）；
    - match_type='default'：兜底档案（未命中任何 cidr 档案时使用，全库唯一）；
    - prefer_types：智能解析的入口类型优先顺序（五类入口的子集排列，可空）。
    """

    __tablename__ = "network_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    match_type: Mapped[str] = mapped_column(String(16), default="cidr")  # cidr / default
    cidrs: Mapped[list] = mapped_column(JSON, default=list)  # ["192.168.1.0/24"]
    prefer_types: Mapped[list] = mapped_column(JSON, default=list)  # ["lan","domain","vpn"]
    is_default: Mapped[bool] = mapped_column(default=False)  # 与 match_type='default' 联动
    sort: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
