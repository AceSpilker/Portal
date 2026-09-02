"""图标服务（dev-plan P2.4；M03-5/6）。

- 上传：位图居中裁方压缩为 128px PNG；SVG 原样存储；存储于 data/icons，经 /icons 静态托管
- favicon：目标站 /favicon.ico → 页面 <link> 图标 → Google s2 兜底，全失败按业务失败（4004）返回
"""

import io
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image

from app.core.config import settings
from app.core.i18n import t
from app.core.response import CODE_TARGET_UNREACHABLE, CODE_VALIDATION, BizError

ICON_SIZE = 128
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_UA = "Mozilla/5.0 (compatible; PortalDashboard/1.0; +favicon-fetch)"

_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"([a-zA-Z-]+)\s*=\s*[\"']([^\"']*)[\"']")


def icons_dir() -> Path:
    d = Path(settings.data_dir) / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_icon(raw: bytes, filename: str = "") -> str:
    """保存并压缩图标，返回 /icons/<name> 相对 URL；非法图片抛 2001。"""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BizError(CODE_VALIDATION, t("err.icon_too_large"), 422)
    name = (filename or "").lower()
    head = raw.lstrip()[:5]
    is_svg = name.endswith(".svg") or head == b"<svg " or head == b"<?xml"
    if not is_svg:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                im = im.convert("RGBA")
                side = min(im.size)
                left = (im.width - side) // 2
                top = (im.height - side) // 2
                square = im.crop((left, top, left + side, top + side))
                square = square.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                buf = io.BytesIO()
                square.save(buf, "PNG")
                raw = buf.getvalue()
        except BizError:
            raise
        except Exception as exc:
            raise BizError(CODE_VALIDATION, t("err.icon_unrecognized"), 422) from exc
    target = f"{uuid.uuid4().hex[:12]}{'.svg' if is_svg else '.png'}"
    (icons_dir() / target).write_bytes(raw)
    return f"/icons/{target}"


def _extract_icon_hrefs(html: str) -> list[str]:
    """提取页面 <link rel*=icon> 的 href：apple-touch-icon 优先（尺寸更大）。"""
    apple: list[str] = []
    normal: list[str] = []
    for tag in _LINK_TAG_RE.findall(html):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "").strip()
        if "icon" in rel and href:
            (apple if "apple-touch" in rel else normal).append(href)
    return (apple + normal)[:3]


async def fetch_favicon(
    page_url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> bytes:
    """抓取目标站图标二进制；抓不到/超时抛 4004（业务失败），非法地址抛 2001。

    transport 仅供测试注入 MockTransport，生产始终走真实网络。
    """
    parts = urlsplit(page_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise BizError(CODE_VALIDATION, t("err.bad_url"), 422)

    origin = f"{parts.scheme}://{parts.netloc}"
    candidates = [f"{origin}/favicon.ico"]
    timeout = httpx.Timeout(3.0, connect=2.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}, transport=transport
        ) as client:
            try:
                resp = await client.get(page_url)
                if "html" in resp.headers.get("content-type", "").lower():
                    candidates += [urljoin(origin, href) for href in _extract_icon_hrefs(resp.text)]
            except httpx.HTTPError:
                pass  # 页面拉取失败仍可尝试 favicon.ico / s2 兜底
            # 外网兜底服务（网络受限环境会快速失败并返回 4004）
            hostname = parts.hostname or ""
            candidates.append(f"https://www.google.com/s2/favicons?domain={hostname}&sz=128")
            for candidate in candidates:
                try:
                    resp = await client.get(candidate)
                except httpx.HTTPError:
                    continue
                ctype = resp.headers.get("content-type", "").lower()
                starts_html = resp.content[:1] == b"<"
                if (
                    resp.status_code == 200
                    and resp.content
                    and not starts_html
                    and ("image" in ctype or not ctype)
                ):
                    return resp.content
    except httpx.HTTPError as exc:  # 客户端级异常（如整体超时）
        raise BizError(
            CODE_TARGET_UNREACHABLE, t("err.favicon_failed", reason=exc.__class__.__name__)
        ) from exc
    raise BizError(CODE_TARGET_UNREACHABLE, t("err.favicon_not_found"))
