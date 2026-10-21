"""账户模型（二期 D2：自一期 models/user.py、models/api_token.py 移植）。

表名/列名与一期一致（users / user_sessions / api_tokens），D1 接管既有库时
做 schema diff 校准。认证不使用 Django auth 体系（JWT 自研，见 security.py），
故 User 为普通模型（D1 决策点：是否迁到 AUTH_USER_MODEL——当前无 Django 依赖面）。
"""

from __future__ import annotations

from django.db import models


class User(models.Model):
    username = models.CharField(max_length=32, unique=True, db_index=True)
    password_hash = models.CharField(max_length=128)
    role = models.CharField(max_length=16, default="user")  # admin / user
    is_active = models.BooleanField(default=True)
    totp_secret = models.CharField(max_length=64, null=True, blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_recovery = models.TextField(default="[]")  # 恢复码 SHA-256 列表（JSON）
    prefs = models.CharField(max_length=1024, default="{}")  # JSON 个人偏好
    remark = models.TextField(default="", blank=True)  # 管理员备注
    password_changed_at = models.DateTimeField(null=True, blank=True)  # 审计用
    token_version = models.IntegerField(default=0)  # 改密踢会话：旧版本 token 失效

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.username


class UserSession(models.Model):
    """登录会话清单：登录设备/会话管理/强制下线的载体（jti = refresh token 唯一 ID）。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", db_index=True)
    jti = models.CharField(max_length=64, unique=True)
    device = models.TextField(default="", blank=True)  # User-Agent 截断
    ip = models.CharField(max_length=64, default="", blank=True)
    revoked = models.BooleanField(default=False, db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_sessions"

    def __str__(self) -> str:
        return f"session#{self.pk} user={self.user_id}"


class ApiToken(models.Model):
    """开放 API Token：plt_ 前缀，SHA-256 哈希存储，只读/读写两档（CRUD 端点 D2.10）。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", db_index=True)
    name = models.CharField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True)
    token_prefix = models.CharField(max_length=12, default="", blank=True)  # 展示用前 8 位
    scope = models.CharField(max_length=8, default="ro")  # ro / rw
    revoked = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(default="", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "api_tokens"

    def __str__(self) -> str:
        return f"plt_{self.token_prefix}…({self.name})"
