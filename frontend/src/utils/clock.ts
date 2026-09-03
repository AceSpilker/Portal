/**
 * 首页时钟格式化（P4.7 增强）。
 *
 * 时间一律取客户端本地时钟、前端每秒自跳（HomeView setInterval 1s），
 * 不走后端接口：网络往返（局域网几十毫秒、外网几百毫秒）只会让显示时间
 * 滞后于真实时间，且秒级轮询徒增服务器压力。仅当客户端时钟本身不可信时
 * 才需要服务端校时，属另一个话题。
 */

/** 时：分：秒，两位补零（09:26:45）；timeZone='system' 表示跟随浏览器时区。 */
export function formatClockTime(d: Date, locale = 'zh-CN', timeZone?: string): string {
  return d.toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    ...(timeZone && timeZone !== 'system' ? { timeZone } : {}),
  })
}

/** 年月日 + 星期（2026年9月3日星期四 / Thursday, September 3, 2026）。 */
export function formatClockDate(d: Date, locale = 'zh-CN', timeZone?: string): string {
  return d.toLocaleDateString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
    ...(timeZone && timeZone !== 'system' ? { timeZone } : {}),
  })
}
