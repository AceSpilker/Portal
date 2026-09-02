import { describe, expect, it, vi, afterEach } from 'vitest'
import { makeExportFilename } from '../utils/export'

describe('导出文件名规范（api-spec §1）', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('格式为 前缀_YYYYMMDDHHMMSS_RRR.后缀', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 2, 15, 30, 45)) // 2026-09-02 15:30:45 本地时间
    const name = makeExportFilename('portal-apps', 'json')
    expect(name).toMatch(/^portal-apps_20260902153045_\d{3}\.json$/)
  })

  it('随机数在 000–999 范围内且后缀可自动去点', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 0, 1, 0, 0, 0))
    const name = makeExportFilename('backup', '.csv')
    expect(name).toMatch(/^backup_20260101000000_\d{3}\.csv$/)
    const rand = Number(name.match(/_(\d{3})\.csv$/)![1])
    expect(rand).toBeGreaterThanOrEqual(0)
    expect(rand).toBeLessThanOrEqual(999)
  })

  it('月份/日期/时分秒补零到两位', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 0, 5, 3, 7, 9))
    const name = makeExportFilename('report', 'csv')
    expect(name).toMatch(/^report_20260105030709_\d{3}\.csv$/)
  })
})
