"""参数校验错误 message 人性化格式化测试（2001：message 携带用户可读明细）。

校验错误在进入端点逻辑前返回，不依赖数据库/账号状态。
"""


def _message(client, resp) -> str:
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
    return resp.json()["message"]


def test_01_weak_password_readable(client):
    """弱口令 → 校验器中文 message 原样呈现，不带原始结构。"""
    resp = client.post("/api/auth/init", json={"username": "admin", "password": "12345678"})
    msg = _message(client, resp)
    assert msg == "参数校验失败：密码至少 8 位，且同时包含字母与数字"
    assert "loc" not in msg and "[{" not in msg


def test_02_missing_field_labeled(client):
    """缺字段 → 中文标签 + 必填项提示。"""
    resp = client.post("/api/auth/init", json={"password": "abc12345"})
    msg = _message(client, resp)
    assert msg == "参数校验失败：用户名 为必填项"


def test_03_value_error_self_describing(client):
    """用户名规则 → 自描述中文 message。"""
    resp = client.post(
        "/api/auth/init",
        json={"username": "this-username-is-way-too-long-for-the-rule", "password": "abc12345"},
    )
    msg = _message(client, resp)
    assert msg == "参数校验失败：用户名需 3~32 位，仅限字母/数字/下划线/中划线"
