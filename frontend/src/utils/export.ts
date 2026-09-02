/**
 * 导出文件名统一规范（api-spec §1 通用约定）：
 * `前缀_YYYYMMDDHHMMSS_RRR.后缀`
 * - 时间部分为本地时间年月日时分秒；
 * - RRR 为 000–999 三位随机数，避免同一秒内多次导出同名覆盖；
 * - 所有导出场景（应用/备份/报表等）一律经由本函数生成文件名。
 */
export function makeExportFilename(prefix: string, ext: string): string {
  const d = new Date()
  const p2 = (n: number) => String(n).padStart(2, '0')
  const ts =
    `${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}` +
    `${p2(d.getHours())}${p2(d.getMinutes())}${p2(d.getSeconds())}`
  const rand = String(Math.floor(Math.random() * 1000)).padStart(3, '0')
  return `${prefix}_${ts}_${rand}.${ext.replace(/^\./, '')}`
}
