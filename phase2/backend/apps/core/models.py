"""core 应用数据模型：站点键值配置（D2 起各域共用；自一期 models/setting.py 移植）。

表名/列名与一期一致（settings: key/value + 时间戳），D1 inspectdb 六步法
接管既有库时以此为准做 schema diff。
"""

from __future__ import annotations

from django.db import models


class Setting(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    value = models.TextField(default="null")  # JSON 字符串

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "settings"

    def get_value(self):
        import json

        return json.loads(self.value)

    def __str__(self) -> str:
        return self.key
