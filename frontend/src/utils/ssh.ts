/**
 * SSH 本地转发命令构造（M04-15；dev-plan P3.7）。
 *
 * 入口地址约定：`user@host` / `user@host:port` / `host` / `host:port`（跳板机）。
 * 生成命令：`ssh -L {本地端口}:{内网目标} user@jump [-p 端口]`，
 * 用户复制后在本地执行即可通过 127.0.0.1:{本地端口} 访问内网目标。
 */
import type { AppUrl } from '../api/portal'

export interface SshTarget {
  user: string
  host: string
  port: number
}

/** 解析跳板机地址；无法解析返回 null。 */
export function parseJump(url: string): SshTarget | null {
  const text = (url || '').trim()
  if (!text) return null
  // 省略 scheme 的 authority 写法（user@host:22）；user/host 均不允许空白
  const m = text.match(/^(?:([^@\s/]+)@)?([^\s:/]+)(?::(\d+))?$/)
  if (!m) return null
  return {
    user: m[1] ?? '',
    host: m[2],
    port: m[3] ? Number(m[3]) : 22,
  }
}

/** 从内网目标地址提取 host 与 port（无显式端口时按 http 80 / https 443 兜底）。 */
export function parseInner(url: string): { host: string; port: number } | null {
  const text = (url || '').trim()
  if (!text) return null
  const m = text.match(
    /^(?:(https?):\/\/)?(?:[^@/]+@)?\[?([^\]/]+?)\]?(?::(\d+))?(?:[/?]|$)/i,
  )
  if (!m || !m[2]) return null
  const fallback = m[1]?.toLowerCase() === 'https' ? 443 : 80
  return { host: m[2], port: m[3] ? Number(m[3]) : fallback }
}

/** 本地端口建议：18000 + 入口 id 尾数，稳定且避开常用端口段。 */
export function suggestLocalPort(urlId: number): number {
  return 18000 + (urlId % 1000)
}

/**
 * 生成 `ssh -L` 命令。inner 为内网目标入口（优先 lan），jump 为 ssh 入口；
 * 任一端无法解析时返回 null（调用方提示手动填写）。
 */
export function buildSshCommand(
  jump: AppUrl,
  inner: AppUrl | null,
  localPort: number,
): string | null {
  const t = parseJump(jump.url)
  if (!t) return null
  const parts = ['ssh']
  if (inner) {
    const target = parseInner(inner.url)
    if (!target) return null
    parts.push('-L', `${localPort}:${target.host}:${target.port}`)
  }
  parts.push(t.user ? `${t.user}@${t.host}` : t.host)
  if (t.port !== 22) parts.push('-p', String(t.port))
  return parts.join(' ')
}
