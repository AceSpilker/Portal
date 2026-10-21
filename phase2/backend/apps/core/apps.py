"""core 应用配置（D4：APScheduler 启动点，含 manage 命令守卫）。"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Portal Core"
