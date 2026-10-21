"""WSGI 入口（仅保底；生产为 uvicorn ASGI——加密中间件只在 ASGI 面）。"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
