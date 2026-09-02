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

function toB64(buf: ArrayBufferLike | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin)
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
  if (session) return
  booting ??= (async () => {
    const info = await axios.get('/api/crypto/public-key').then((r) => r.data.data)
    const key = (await crypto.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      true,
      ['encrypt', 'decrypt'],
    )) as CryptoKey
    const raw = await crypto.subtle.exportKey('raw', key)
    const pub = await crypto.subtle.importKey(
      'spki',
      fromB64(info.public_key),
      { name: 'RSA-OAEP', hash: 'SHA-256' },
      false,
      ['encrypt'],
    )
    const wrapped = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, pub, raw)
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

/** 加密 Authorization 头值（格式：ENC <nonce>:<payload>）。 */
export async function encryptHeaderValue(value: string): Promise<string> {
  await ensureSession()
  const nonce = crypto.getRandomValues(new Uint8Array(12))
  const payload = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce as BufferSource },
    session!.key,
    encoder.encode(value),
  )
  return `ENC ${toB64(nonce.buffer)}:${toB64(payload)}`
}
