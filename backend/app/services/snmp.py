"""最小 SNMP v2c 采集（M17-19；dev-plan P21.3）。

纯标准库实现 BER 编解码的 GET 单请求（无外部依赖）：
- build_get(oid, community, request_id) → UDP 报文字节；
- parse_response(payload) → (error_status, oid, value)。
适用于 v2c 只读社区串的轻量探测（sysDescr.0 / sysUpTime.0 等）。
"""

from __future__ import annotations


def _ber_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    out = b""
    while length:
        out = bytes([length & 0xFF]) + out
        length >>= 8
    return bytes([0x80 | len(out)]) + out


def _tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(payload)) + payload


def _encode_oid(oid: str) -> bytes:
    parts = [int(x) for x in oid.strip(".").split(".")]
    first = parts[0] * 40 + parts[1]
    body = bytes([first])
    for p in parts[2:]:
        chunk = b""
        while True:
            chunk = bytes([(p & 0x7F) | (0x80 if chunk else 0)]) + chunk
            p >>= 7
            if not p:
                break
        body += chunk
    return _tlv(0x06, body)


def _encode_int(value: int) -> bytes:
    """非负整数 base-128 大端编码。"""
    out = bytes([value & 0x7F])
    value >>= 7
    while value:
        out = bytes([(value & 0x7F) | 0x80]) + out
        value >>= 7
    return _tlv(0x02, out)


def build_get(oid: str, community: str = "public", request_id: int = 1) -> bytes:
    """构造 SNMP v2c GET 报文。"""
    varbind = _tlv(0x30, _encode_oid(oid) + _tlv(0x05, b""))
    varbinds = _tlv(0x30, varbind)
    pdu = (
        _tlv(0x02, bytes([request_id & 0x7F]))
        + _tlv(0x02, b"\x00")  # error-status 0
        + _tlv(0x02, b"\x00")  # error-index 0
        + varbinds
    )
    return _tlv(0x30, _tlv(0x02, b"\x00") + _tlv(0x04, community.encode()) + _tlv(0xA0, pdu))


def parse_response(payload: bytes) -> tuple[int, str, object]:
    """解析 GET 响应：返回 (error_status, oid, value)。仅支持单 varbind。"""

    def _read_tlv(buf: bytes, off: int):
        tag = buf[off]
        off += 1
        length = buf[off]
        off += 1
        if length & 0x80:
            n = length & 0x7F
            length = int.from_bytes(buf[off : off + n], "big")
            off += n
        return tag, buf[off : off + length], off + length

    _tag, message, off = _read_tlv(payload, 0)  # 整体 SEQUENCE
    mo = 0
    _tag, _ver, mo = _read_tlv(message, mo)
    _tag, _community, mo = _read_tlv(message, mo)
    _pdu_tag, pdu, mo = _read_tlv(message, mo)
    # PDU: request_id, error_status, error_index, varbinds
    po = 0
    _tag, _req_id, po = _read_tlv(pdu, po)
    _tag, err_status, po = _read_tlv(pdu, po)
    err = err_status[0] if err_status else 0
    _tag, _err_index, po = _read_tlv(pdu, po)
    _tag, varbinds, po = _read_tlv(pdu, po)
    vo = 0
    _tag, varbind, vo = _read_tlv(varbinds, vo)  # 单个 varbind SEQUENCE
    vo2 = 0
    _tag, oid_tlv, vo2 = _read_tlv(varbind, vo2)
    vtag, val_body, _vo = _read_tlv(varbind, vo2)
    oid = _decode_oid(oid_tlv)
    value = _decode_value((vtag, val_body))
    return err, oid, value


def _decode_oid(raw: bytes) -> str:
    first = raw[0]
    parts = [first // 40, first % 40]
    p = 0
    for b in raw[1:]:
        p = (p << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(p)
            p = 0
    return ".".join(str(x) for x in parts)


def _decode_value(tlv: tuple[int, bytes]):
    tag, body = tlv
    if tag == 0x05:
        return None
    if tag == 0x04:
        return body.decode("utf-8", "replace")
    if tag in (0x02, 0x42, 0x41, 0x43, 0x46):  # int / counter / gauge / timeticks
        v = 0
        for b in body:
            v = (v << 8) | b
        return v
    return body.hex()
