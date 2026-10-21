"""顶层骨架视图（二期 D0.7）。

- icons_view：data/icons 静态托管（一期 _mount_icons 同语义；目录缺失时 404 JSON）
- tunnel_placeholder / files_raw_placeholder：D5/D6 完整实现前的占位（明确 501 语义）
- spa_view：可选的本地直连 SPA 视图（一期 _SpaStaticFiles 语义简化版；
  生产前端由 nginx 托管，本视图仅在 FRONTEND_DIST 配置时生效）
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.views.static import serve as static_serve

# PWA autoUpdate 依赖：入口类文件禁缓存（一期 _NO_CACHE_NAMES 同款）
_NO_CACHE_NAMES = {
    "index.html",
    "sw.js",
    "registerSW.js",
    "manifest.webmanifest",
}


def _no_cache(resp: HttpResponse, filename: str) -> HttpResponse:
    if filename in _NO_CACHE_NAMES or filename.startswith("workbox-"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def icons_view(request: HttpRequest, path: str):
    icons_dir = Path(settings.DATA_DIR) / "icons"
    if not icons_dir.is_dir():
        return JsonResponse({"code": 404, "msg": "icons dir not found", "data": None}, status=404)
    resp = static_serve(request, path, document_root=str(icons_dir))
    return _no_cache(resp, Path(path).name)


def tunnel_placeholder(request: HttpRequest) -> HttpResponse:
    """SSH 隧道 HTTP 反代（D5 落地：t/cookie 签名校验 + asyncssh 本地端口转发）。"""
    return JsonResponse(
        {"code": 5001, "msg": "tunnel proxy arrives in D5", "data": None}, status=501
    )


def files_raw_placeholder(request: HttpRequest) -> HttpResponse:
    """文件预览签名直链（D6 落地：file JWT + 白名单二次校验）。"""
    return JsonResponse(
        {"code": 5001, "msg": "files/raw arrives in D6", "data": None}, status=501
    )


def spa_view(request: HttpRequest) -> HttpResponse:
    """可选本地直连 SPA：GET + text/html + 非 API 前缀 → index.html（深链接回退）。

    生产由 nginx 承担（迁移方案 §11.2 try_files）；后端仅在 FRONTEND_DIST 指向存在
    的 dist 目录时启用，API 未知路径仍返回 JSON 404。
    """
    dist = settings.FRONTEND_DIST
    if request.method != "GET" or not dist:
        return JsonResponse({"code": 404, "msg": "not found", "data": None}, status=404)
    if request.path.startswith(("/api", "/ws", "/icons", "/tunnel", "/files")):
        return JsonResponse({"code": 404, "msg": "not found", "data": None}, status=404)
    accept = request.headers.get("Accept", "")
    if "text/html" not in accept:
        return JsonResponse({"code": 404, "msg": "not found", "data": None}, status=404)
    index = Path(dist) / "index.html"
    if not index.is_file():
        return JsonResponse({"code": 404, "msg": "frontend dist missing", "data": None}, status=404)
    return _no_cache(FileResponse(open(index, "rb"), content_type="text/html"), "index.html")
