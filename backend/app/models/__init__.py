"""SQLAlchemy 模型集合（新增模型后在此导出以注册建表）。"""

from app.models.ai import AiConversation, AiMessage
from app.models.base import Base
from app.models.flow import Flow, FlowRun
from app.models.layout import DashboardLayout
from app.models.monitor import AlertRule, MonitorSample
from app.models.network import NetworkProfile
from app.models.notify import NotifyChannel, NotifyRule
from app.models.port import PortEvent, PortMonitor
from app.models.portal import App, AppUrl, Category, Icon
from app.models.probe import AppStatus, Notification, ProbeEvent, UrlProbeSample
from app.models.schedule import CalendarEvent, Todo
from app.models.setting import DEFAULT_SETTINGS, Setting
from app.models.tools import WolTarget
from app.models.user import User

__all__ = [
    "App",
    "AppStatus",
    "AppUrl",
    "Base",
    "CalendarEvent",
    "Category",
    "DashboardLayout",
    "DEFAULT_SETTINGS",
    "Icon",
    "AiConversation",
    "AiMessage",
    "AlertRule",
    "MonitorSample",
    "NotifyChannel",
    "Flow",
    "FlowRun",
    "NotifyRule",
    "PortEvent",
    "PortMonitor",
    "NetworkProfile",
    "Notification",
    "ProbeEvent",
    "UrlProbeSample",
    "Setting",
    "WolTarget",
    "Todo",
    "User",
]
