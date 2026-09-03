/**
 * 监控工具函数（M17；P5.5/P5.6）：单位换算与 WS 地址构造（纯函数供单测）。
 */

/** 字节 → 可读单位（B/KB/MB/GB/TB，1024 进制；B 不带小数，其余 1 位）。 */
export function formatBytes(n: number, digits = 1): string {
  if (!Number.isFinite(n) || n < 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : digits)} ${units[i]}`
}

/** 字节/秒速率 → 可读单位（如 1.5 MB/s）。 */
export function formatRate(bytesPerSec: number): string {
  return `${formatBytes(bytesPerSec)}/s`
}

/** 运行时长（秒）→ 本地化文本：X天X小时X分 / Xd Xh Xm。 */
export function formatUptime(seconds: number, locale = 'zh-CN'): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '-'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (locale.startsWith('zh')) {
    if (d > 0) return `${d}天${h}小时${m}分`
    if (h > 0) return `${h}小时${m}分`
    return `${m}分钟`
  }
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

/** 监控 WS 地址：跟随页面协议与 host，token 走 query（WS 不受加密信封约束）。 */
export function buildMonitorWsUrl(token: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/monitor?token=${encodeURIComponent(token)}`
}

export type HistoryMetric = 'cpu' | 'mem' | 'net' | 'disk' | 'temp' | 'io' | 'gpu'
export type HistoryRange = '24h' | '7d' | '30d'
export const HISTORY_RANGES: HistoryRange[] = ['24h', '7d', '30d']
