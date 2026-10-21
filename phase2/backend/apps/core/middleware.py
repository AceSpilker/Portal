"""Django 中间件（二期 D0.5）。

LocaleMiddleware：按 Accept-Language 设置本请求的文案语言（一期 main.py 同款语义）。
审计中间件（D2.12）随后加入——置于加密 ASGI 层内侧，天然读到解密后的 Bearer。
"""

from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.i18n import set_locale


def simple_locale_middleware(get_response: Callable[[HttpRequest], HttpResponse]):
    def middleware(request: HttpRequest) -> HttpResponse:
        set_locale(request.headers.get("Accept-Language", ""))
        return get_response(request)

    return middleware


class LocaleMiddleware:
    """同步/异步双形态：设置 i18n contextvar 后放行。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        set_locale(request.headers.get("Accept-Language", ""))
        return self.get_response(request)
