"""知识库文件系统服务（091）：路径安全、类型判定、目录树、读写。

安全边界：所有访问都收敛在数据源根目录内（resolve 后前缀校验，杜绝 ../ 穿越）；
hidden 文件（. 开头）与常见依赖目录不入树。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ---------- 类型判定（按扩展名） ----------

MD_EXTS = {".md", ".markdown", ".mdown"}
TEXT_EXTS = {
    ".txt", ".log", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".csv", ".tsv", ".xml", ".sql", ".properties", ".list",
}
CODE_EXTS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".css", ".scss",
    ".less", ".sh", ".bash", ".zsh", ".bat", ".ps1", ".go", ".rs", ".java", ".kt",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".dart", ".lua",
    ".dockerfile", ".makefile", ".cmake", ".gradle", ".proto", ".graphql",
}
HTML_EXTS = {".html", ".htm", ".xhtml"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".flv"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
OFFICE_LEGACY_EXTS = {".doc", ".ppt"}  # 老格式只能下载
ARCHIVE_EXTS = {".zip"}

HIDDEN_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", ".idea", ".vscode", ".DS_Store", "@eaDir",
}
JUNK_FILES = {"desktop.ini", "Thumbs.db"}


def file_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in MD_EXTS:
        return "markdown"
    if ext in HTML_EXTS:
        return "html"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext in (".xlsx", ".xls"):
        return "xlsx"
    if ext == ".pptx":
        return "pptx"
    if ext in ARCHIVE_EXTS:
        return "zip"
    if ext in OFFICE_LEGACY_EXTS:
        return "binary"
    if ext in CODE_EXTS:
        return "code"
    if ext in TEXT_EXTS:
        return "text"
    # 无扩展名/未收录：尝试按文本读取判定
    try:
        path.read_text(encoding="utf-8")[:0]
        return "code"
    except Exception:
        return "binary"


def safe_join(root: Path, sub: str) -> Path:
    """子路径收敛在 root 内；穿越/绝对路径注入一律拒绝。"""
    root = root.resolve()
    p = (root / sub.lstrip("/\\")).resolve()
    if p != root and root not in p.parents:
        raise PermissionError(f"path escapes source root: {sub}")
    return p


def list_tree(root: Path, sub: str = "") -> list[dict[str, Any]]:
    """目录清单：目录在前、名称排序；hidden/依赖目录不入树。"""
    base = safe_join(root, sub)
    if not base.is_dir():
        raise NotADirectoryError(str(sub))
    out: list[dict[str, Any]] = []
    for p in sorted(base.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.name.startswith(".") or p.name in HIDDEN_DIRS or p.name in JUNK_FILES:
            continue
        st = p.stat()
        out.append(
            {
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size": st.st_size if p.is_file() else None,
                "mtime": int(st.st_mtime),
            }
        )
    return out
