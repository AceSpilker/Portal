"""URL 总路由（dev-plan D0.7）：/api → Ninja；顶层骨架 /icons /tunnel /files + SPA 兜底。

生产部署中这些顶层路径由 nginx 反代到本服务（迁移方案 §11.2）。
"""

from django.urls import path, re_path

from apps.core import spa
from config.api import api

urlpatterns = [
    path("api/", api.urls),
    # /icons：数据卷内上传图标静态托管（一期 main.py L543-547 同语义）
    re_path(r"^icons/(?P<path>.*)$", spa.icons_view),
    # /tunnel/{id}/...：SSH 隧道 HTTP 反代（D5 完整实现，此处占位）
    re_path(r"^tunnel/", spa.tunnel_placeholder, name="tunnel-placeholder"),
    # /files/raw?token=：文件预览签名直链（D6 完整实现，此处占位）
    path("files/raw", spa.files_raw_placeholder, name="files-raw-placeholder"),
    # 兜底：可选的本地直连 SPA 视图（生产前端在 nginx，见迁移方案 §11.1）
    re_path(r"^.*$", spa.spa_view, name="spa"),
]
