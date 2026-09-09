# ruff: noqa: E501
"""知识库模块（091）：local 数据源生命周期 + 目录树 + 读取分类 + 文本写回 + 路径穿越拒绝。
git 同步依赖网络，不在单测范围（dulwich 走 https 公库，部署后手工验证）。
文件名 z 前缀：字母序置于 test_auth/test_crypto 之后（auth 链路要求全新库）。"""

import tempfile
from pathlib import Path

import pytest

ADMIN = "admin"
ADMIN_PASS = "portal-p11"
_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3

    from app.core.config import settings
    from app.core.security import hash_password

    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ?, is_active = 1 WHERE username = ?",
                (hash_password(ADMIN_PASS), ADMIN),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'admin', 1, '{}', 0)",
                (ADMIN, hash_password(ADMIN_PASS)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client):
    _reset_db_state()
    _tokens.clear()


def _admin(client) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


@pytest.fixture(scope="module")
def docs_dir() -> Path:
    base = Path(tempfile.mkdtemp(prefix="kb-docs-"))
    (base / "指南.md").write_text("# Hello\n\n知识库正文", encoding="utf-8")
    (base / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (base / "数据.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    sub = base / "sub"
    sub.mkdir()
    (sub / "note.txt").write_text("nested", encoding="utf-8")
    yield base


def test_01_local_source_crud_and_tree(client, docs_dir):
    """local 源：创建（目录校验）→ 列表 → 树 → 子目录树。"""
    r = client.post("/api/knowledge/sources", json={"name": "文档库", "kind": "local", "path": str(docs_dir)}, headers=_admin(client))
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    bad = client.post("/api/knowledge/sources", json={"name": "坏目录", "kind": "local", "path": "/nonexistent-xyz"}, headers=_admin(client))
    assert bad.status_code == 422

    rows = client.get("/api/knowledge/sources", headers=_admin(client)).json()["data"]
    assert any(x["id"] == sid and x["name"] == "文档库" for x in rows)

    tree = client.get(f"/api/knowledge/{sid}/tree", headers=_admin(client)).json()["data"]
    names = {x["name"] for x in tree}
    assert {"指南.md", "app.py", "数据.csv", "sub"} <= names

    subtree = client.get(f"/api/knowledge/{sid}/tree", params={"path": "sub"}, headers=_admin(client)).json()["data"]
    assert subtree[0]["name"] == "note.txt"


def test_02_read_kinds_and_write(client, docs_dir):
    """读取分类：markdown/text/code 返回文本且 local 可编辑；写回生效。"""
    sid = client.get("/api/knowledge/sources", headers=_admin(client)).json()["data"][0]["id"]
    md = client.get(f"/api/knowledge/{sid}/read", params={"path": "指南.md"}, headers=_admin(client)).json()["data"]
    assert md["kind"] == "markdown" and md["editable"] is True and "知识库正文" in md["text"]
    code = client.get(f"/api/knowledge/{sid}/read", params={"path": "app.py"}, headers=_admin(client)).json()["data"]
    assert code["kind"] == "code"
    w = client.put(
        f"/api/knowledge/{sid}/file",
        params={"path": "sub/note.txt"},
        json={"content": "改过的内容"},
        headers=_admin(client),
    )
    assert w.status_code == 200, w.text
    got = client.get(f"/api/knowledge/{sid}/read", params={"path": "sub/note.txt"}, headers=_admin(client)).json()["data"]
    assert got["text"] == "改过的内容"


def test_03_path_traversal_rejected(client):
    """../ 穿越、绝对路径注入一律 422 拒绝。"""
    sid = client.get("/api/knowledge/sources", headers=_admin(client)).json()["data"][0]["id"]
    for evil in ("../escape.txt", "..%2Fescape.txt", "/etc/passwd", "sub/../../x"):
        r = client.get(f"/api/knowledge/{sid}/read", params={"path": evil}, headers=_admin(client))
        assert r.status_code in (404, 422), f"{evil} -> {r.status_code}"


def test_04_office_render(client, docs_dir):
    """docx/xlsx/pptx 服务端转 HTML（用 python-docx/openpyxl/pptx 现场造文件）。"""
    import zipfile

    from openpyxl import Workbook
    from pptx import Presentation

    d = Path(tempfile.mkdtemp(prefix="kb-office-"))
    # docx=zip(word/document.xml)：免装 python-docx，mammoth 直接读
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>标题</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>正文段落</w:t></w:r></w:p></w:body></w:document>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    ctypes = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    with zipfile.ZipFile(d / "a.docx", "w") as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc_xml)
    wb = Workbook()
    wb.active["A1"] = "单元格"
    wb.save(d / "b.xlsx")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "页标题"
    prs.save(d / "c.pptx")

    r = client.post("/api/knowledge/sources", json={"name": "office库", "kind": "local", "path": str(d)}, headers=_admin(client))
    sid = r.json()["data"]["id"]
    # 092 起 office 由前端组件库渲染，服务端只返回类型
    for f, kind in (("a.docx", "docx"), ("b.xlsx", "xlsx"), ("c.pptx", "pptx")):
        resp = client.get(f"/api/knowledge/{sid}/read", params={"path": f}, headers=_admin(client))
        data = resp.json()["data"]
        assert data, resp.text
        assert data["kind"] == kind and "html" not in data, f


def test_05_local_dirs_browser(client, docs_dir):
    """目录选择框端点：默认推荐根（存在者）；指定路径返回一级子目录与上级；不存在 exists=False。"""
    r = client.get("/api/knowledge/local-dirs", headers=_admin(client)).json()["data"]
    assert isinstance(r["roots"], list)
    r2 = client.get(
        "/api/knowledge/local-dirs", params={"path": str(docs_dir)}, headers=_admin(client)
    ).json()["data"]
    assert r2["exists"] is True and any(d.endswith("/sub") for d in r2["dirs"])
    assert r2["parent"] == str(docs_dir.parent)
    r3 = client.get(
        "/api/knowledge/local-dirs", params={"path": "/nonexistent-xyz"}, headers=_admin(client)
    ).json()["data"]
    assert r3["exists"] is False and r3["dirs"] == []


def test_05_disable_then_reenable(client, docs_dir):
    """停用 → 保存 → 再编辑重新启用：不能被 404 卡死（092 用户反馈）。"""
    r = client.post("/api/knowledge/sources", json={"name": "开关库", "kind": "local", "path": str(docs_dir)}, headers=_admin(client))
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    off = client.put(f"/api/knowledge/sources/{sid}", json={"enabled": False}, headers=_admin(client))
    assert off.status_code == 200 and off.json()["data"]["enabled"] is False
    on = client.put(f"/api/knowledge/sources/{sid}", json={"enabled": True}, headers=_admin(client))
    assert on.status_code == 200, on.text
    assert on.json()["data"]["enabled"] is True
    # 停用态仍可删除
    off2 = client.put(f"/api/knowledge/sources/{sid}", json={"enabled": False}, headers=_admin(client))
    assert off2.status_code == 200
    dele = client.delete(f"/api/knowledge/sources/{sid}", headers=_admin(client))
    assert dele.status_code == 200
