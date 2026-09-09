/**
 * 传输加密会话（dev-plan P24 / api-spec §7）。
 *
 * - 首次请求前与后端握手：获取 RSA 公钥 → 生成 AES-256 会话密钥 → 公钥封装上报
 * - 之后所有 /api 请求体/响应体走 AES-256-GCM 信封，Authorization 头同步密文化
 * - 密钥仅存在于前端内存与后端进程内存，不落盘不落地
 */
import axios from 'axios'

const encoder = new TextEncoder()
const decoder = new TextDecoder()

let session: { id: string; key: CryptoKey } | null = null
let booting: Promise<void> | null = null

// WebCrypto subtle 仅在安全上下文（HTTPS / localhost）暴露；HTTP 裸 IP 访问（NAS 局域网
// 常见形态）下为 undefined，握手无法进行。此时降级为明文传输，需部署侧配合
// ENCRYPT_ENABLED=false（后端中间件整体旁路）；若后端仍开加密会以 1100 拒绝，
// 由 request.ts 给出明确指引而非无意义重试。
const insecureContext = typeof crypto === 'undefined' || !crypto.subtle
if (insecureContext) {
  console.warn('[secure] 非安全上下文（HTTP）：WebCrypto 不可用，已降级为明文传输')
}

// 服务端关闭传输加密（ENCRYPT_ENABLED=false）时由握手接口告知，安全上下文下同样走明文
let serverPlaintext: boolean | null = null

/** 是否处于明文传输降级模式（HTTP 访问，或服务端已关闭传输加密）。 */
export function isPlaintextTransport(): boolean {
  return insecureContext || serverPlaintext === true
}

function toB64(buf: ArrayBufferLike | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin)
}

/** 兼容 PEM（去头尾去空白）与裸 base64 两种公钥格式。 */
function normalizePublicKey(publicKey: string): string {
  return publicKey.includes('BEGIN')
    ? publicKey.replace(/-----(BEGIN|END) PUBLIC KEY-----/g, '').replace(/\s+/g, '')
    : publicKey
}

function fromB64(text: string): ArrayBuffer {
  const bin = atob(text)
  const buf = new ArrayBuffer(bin.length)
  const bytes = new Uint8Array(buf)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return buf
}

/** 豁免路径：健康检查与握手本身（不含敏感数据） */
export function isExemptPath(url: string): boolean {
  return url === '/health' || url.startsWith('/crypto')
}

export async function ensureSession(): Promise<void> {
  if (session || insecureContext || serverPlaintext) return
  booting ??= (async () => {
    const info = await axios.get('/api/crypto/public-key').then((r) => r.data.data)
    // 服务端已关闭传输加密：即使当前是安全上下文（HTTPS）也不握手、不加密请求体
    if (info && info.enabled === false) {
      serverPlaintext = true
      return
    }
    // 响应形态异常（旧后端/代理篡改等）：public_key 缺失时无法封装会话密钥，
    // 与其抛 TypeError 中断所有请求（083 公司隧道登录报 reading 'includes'），
    // 不如降级明文——后端加密开启时公钥必然存在，走到这里即后端实际未加密
    if (!info || typeof info.public_key !== 'string' || !info.public_key) {
      console.warn('[secure] 握手响应缺少公钥，降级为明文传输')
      serverPlaintext = true
      return
    }
    const key = (await crypto.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      true,
      ['encrypt', 'decrypt'],
    )) as CryptoKey
    const raw = await crypto.subtle.exportKey('raw', key)
    let wrapped: ArrayBuffer
    try {
      const pub = await crypto.subtle.importKey(
        'spki',
        fromB64(normalizePublicKey(info.public_key)),
        { name: 'RSA-OAEP', hash: 'SHA-256' },
        false,
        ['encrypt'],
      )
      wrapped = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, pub, raw)
    } catch {
      // 公钥解析/封装失败（格式损坏等）：降级明文；若后端实际开着加密，
      // 后续请求会以 1100 拒绝并由 request.ts 给出部署错配指引
      console.warn('[secure] 会话密钥封装失败，降级为明文传输')
      serverPlaintext = true
      return
    }
    const id = toB64(crypto.getRandomValues(new Uint8Array(8)).buffer)
    await axios.post('/api/crypto/handshake', { sid: id, key: toB64(wrapped) })
    session = { id, key }
  })().catch((err) => {
    booting = null
    throw err
  })
  await booting
}

export function resetSession(): void {
  session = null
  booting = null
}

/** 当前会话 id（未握手时为空串）。每个非豁免请求都必须随头携带。 */
export function currentSessionId(): string {
  return session?.id ?? ''
}

/** 加密请求体为信封；豁免路径或无请求体时原样返回。 */
export async function encryptBody(
  url: string,
  data: unknown,
): Promise<{ body: unknown; sessionId: string }> {
  await ensureSession()
  if (!session || isExemptPath(url) || data === undefined || data === null) {
    return { body: data, sessionId: '' }
  }
  const nonce = crypto.getRandomValues(new Uint8Array(12))
  const payload = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce as BufferSource },
    session.key,
    encoder.encode(JSON.stringify(data)),
  )
  return {
    body: { enc: 1, n: toB64(nonce.buffer), p: toB64(payload) },
    sessionId: session.id,
  }
}

/** 解密响应信封；非密文原样返回。 */
export async function decryptBody(data: unknown): Promise<unknown> {
  if (session && data && typeof data === 'object' && (data as Record<string, unknown>)['enc'] === 1) {
    const env = data as { n: string; p: string }
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: fromB64(env.n) as BufferSource },
      session.key,
      fromB64(env.p),
    )
    return JSON.parse(decoder.decode(plain))
  }
  return data
}

/** 加密 Authorization 头值（格式：ENC <nonce>:<payload>）；明文降级时原样返回。 */
export async function encryptHeaderValue(value: string): Promise<string> {
  await ensureSession()
  if (!session) return value
  const nonce = crypto.getRandomValues(new Uint8Array(12))
  const payload = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce as BufferSource },
    session!.key,
    encoder.encode(value),
  )
  return `ENC ${toB64(nonce.buffer)}:${toB64(payload)}`
}
