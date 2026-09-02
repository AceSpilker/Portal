"""SQLAlchemy 模型集合（新增模型后在此导出以注册建表）。"""

from app.models.base import Base
from app.models.portal import App, AppUrl, Category
from app.models.setting import DEFAULT_SETTINGS, Setting
from app.models.user import User

__all__ = ["App", "AppUrl", "Base", "Category", "DEFAULT_SETTINGS", "Setting", "User"]
