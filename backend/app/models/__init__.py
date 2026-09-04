"""SQLAlchemy 模型集合（新增模型后在此导出以注册建表）。"""

from app.models.ai import AiConversation, AiMessage
from app.models.api_token import ApiToken, UserSession
from app.models.base import Base
from app.models.flow import Flow, FlowRun
from app.models.layout import DashboardLayout
from app.models.monitor import AlertRule, MonitorSample
from app.models.network import NetworkProfile
from app.models.notify import NotifyChannel, NotifyRule
from app.models.port import PortEvent, PortListenHistory, PortMonitor, PortProbeSample
from app.models.portal import App, AppUrl, Category, Icon
from app.models.probe import AppStatus, Notification, ProbeEvent, UrlProbeSample
from app.models.schedule import CalendarEvent, Todo
from app.models.setting import DEFAULT_SETTINGS, Setting
from app.models.sync import SyncState
from app.models.tools import WolTarget
from app.models.tunnel import SSHCredential, Tunnel
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
    "ApiToken",
    "UserSession",
    "AiMessage",
    "AlertRule",
    "MonitorSample",
    "NotifyChannel",
    "Flow",
    "FlowRun",
    "NotifyRule",
    "PortEvent",
    "PortMonitor",
    "PortListenHistory",
    "PortProbeSample",
    "NetworkProfile",
    "Notification",
    "ProbeEvent",
    "UrlProbeSample",
    "Setting",
    "SyncState",
    "SSHCredential",
    "Tunnel",
    "WolTarget",
    "Todo",
    "User",
]
