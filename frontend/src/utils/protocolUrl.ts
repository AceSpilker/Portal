/** 地址输入的协议识别/拼接（ProtocolUrlInput 组件共享逻辑，纯函数便于测试）。 */

const PROTO_RE = /^(https?|wss?|ftp|ftps):\/\//

/** 剥离协议前缀；无协议原样返回。接受 unknown 以兼容弱类型表单字段。 */
export function stripProtocol(value: unknown): string {
  return String(value ?? '').replace(PROTO_RE, '')
}

/** 拆分为协议与剩余部分；无协议则 proto 为空串。 */
export function splitProtocol(value: unknown): { proto: string; rest: string } {
  const v = String(value ?? '')
  const m = PROTO_RE.exec(v)
  return m ? { proto: m[0], rest: v.slice(m[0].length) } : { proto: '', rest: v }
}

/** 拼接协议与地址；地址为空（或只剩协议）返回空串，避免产出无地址的纯协议值。 */
export function joinProtocol(proto: string, rest: string): string {
  const r = stripProtocol(rest)
  return r ? proto + r : ''
}
