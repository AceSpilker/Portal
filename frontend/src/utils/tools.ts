/** 工具箱纯前端工具函数（P7.3）：编解码 / 时间戳 / 密码生成。 */

/** UTF-8 安全的 Base64 编码 */
export function base64Encode(text: string): string {
  const bytes = new TextEncoder().encode(text)
  let bin = ''
  bytes.forEach((b) => (bin += String.fromCharCode(b)))
  return btoa(bin)
}

/** UTF-8 安全的 Base64 解码；非法输入抛错由调用方处理 */
export function base64Decode(text: string): string {
  const bin = atob(text.trim())
  const bytes = Uint8Array.from(bin, (ch) => ch.charCodeAt(0))
  return new TextDecoder().decode(bytes)
}

/** URL 编码 / 解码 */
export const urlEncode = (text: string) => encodeURIComponent(text)
export const urlDecode = (text: string) => decodeURIComponent(text)

const p2 = (n: number) => String(n).padStart(2, '0')

/** 本地时间格式化：YYYY-MM-DD HH:mm:ss */
export function formatDate(d: Date): string {
  return (
    `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ` +
    `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`
  )
}

/** 时间戳（秒或毫秒，自动识别）→ 本地时间字符串；非法返回空串 */
export function unixToDate(ts: string): string {
  const n = Number(ts.trim())
  if (!ts.trim() || !Number.isFinite(n)) return ''
  const ms = Math.abs(n) > 1e11 ? n : n * 1000
  const d = new Date(ms)
  return Number.isNaN(d.getTime()) ? '' : formatDate(d)
}

/** 本地时间（datetime-local 值）→ 秒级时间戳；非法返回空串 */
export function dateToUnix(localValue: string): string {
  if (!localValue.trim()) return ''
  const d = new Date(localValue)
  return Number.isNaN(d.getTime()) ? '' : String(Math.floor(d.getTime() / 1000))
}

export interface PasswordOptions {
  length: number
  upper: boolean
  lower: boolean
  digits: boolean
  symbols: boolean
}

const SETS = {
  upper: 'ABCDEFGHJKLMNPQRSTUVWXYZ',
  lower: 'abcdefghijkmnpqrstuvwxyz',
  digits: '23456789',
  symbols: '!@#$%^&*()-_=+[]{};:,.?',
}

/** 密码生成器：crypto 安全随机；保证每种勾选字符集至少出现一次 */
export function generatePassword(opts: PasswordOptions): string {
  const pools: string[] = []
  if (opts.upper) pools.push(SETS.upper)
  if (opts.lower) pools.push(SETS.lower)
  if (opts.digits) pools.push(SETS.digits)
  if (opts.symbols) pools.push(SETS.symbols)
  if (!pools.length) return ''
  const all = pools.join('')
  const rand = (max: number) => {
    const buf = new Uint32Array(1)
    crypto.getRandomValues(buf)
    return buf[0] % max
  }
  const chars: string[] = pools.map((pool) => pool[rand(pool.length)])
  while (chars.length < opts.length) chars.push(all[rand(all.length)])
  // Fisher–Yates 洗牌，避免保底字符固定在开头
  for (let i = chars.length - 1; i > 0; i--) {
    const j = rand(i + 1)
    ;[chars[i], chars[j]] = [chars[j], chars[i]]
  }
  return chars.slice(0, opts.length).join('')
}
