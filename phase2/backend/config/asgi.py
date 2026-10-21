"""ASGI 入口（dev-plan D0.3）：加密中间件（纯 ASGI，一期逐行移植）包裹 Django。

D4 起改为 Channels ProtocolTypeRouter 结构（http 面保持加密包裹、websocket 面独立）。
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from apps.core.encryption import TransportEncryptionMiddleware  # noqa: E402

application = TransportEncryptionMiddleware(django_asgi_app)
