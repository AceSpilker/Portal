"""Django Ninja 聚合器（dev-plan D0.2）——对外路径与一期 /api/... 完全一致。

信封为 ADP 原生形态 {code, msg, data}（成功 code=200，迁移方案 §5.1）；
业务错误码 1001–5006 与一期逐项相同（apps/core/response.py）。
"""

from django.conf import settings
from ninja import NinjaAPI
from ninja.errors import ValidationError as NinjaValidationError

from apps.accounts.api import router as accounts_router
from apps.core.api import router as core_router
from apps.core.response import BizError, fail, format_validation_errors

_openapi = "/api/openapi.json" if settings.DEBUG else None
_docs = "/api/docs" if settings.DEBUG else None

api = NinjaAPI(openapi_url=_openapi, docs_url=_docs)


@api.exception_handler(BizError)
def on_biz_error(request, exc: BizError):
    """业务异常 → 统一失败信封（HTTP 状态双轨制同一期）。"""
    return fail(exc.code, exc.message, exc.http_status)


@api.exception_handler(NinjaValidationError)
def on_validation_error(request, exc: NinjaValidationError):
    """参数校验失败 → 2001 + 当前语言的可读文案（一期 response.py 同款格式化）。"""
    return fail(2001, format_validation_errors(exc.errors), 422)


# 各域 router 在此聚合（D3+ 逐域追加：portal/monitor_hub/...）
api.add_router("/", core_router)
api.add_router("/", accounts_router)
