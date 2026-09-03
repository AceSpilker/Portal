/** P4.7 时钟格式化单测：年月日+时分秒+星期，中英双语。 */
import { describe, expect, it } from 'vitest'
import { formatClockDate, formatClockTime } from '../utils/clock'

describe('formatClockTime', () => {
  it('输出时:分:秒且两位补零（24 小时制）', () => {
    expect(formatClockTime(new Date(2026, 8, 3, 9, 26, 45))).toBe('09:26:45')
    expect(formatClockTime(new Date(2026, 8, 3, 15, 5, 3))).toBe('15:05:03')
    expect(formatClockTime(new Date(2026, 8, 3, 0, 0, 0))).toBe('00:00:00')
  })
})

describe('formatClockDate', () => {
  it('中文：年月日 + 星期（2026-09-03 为星期四）', () => {
    expect(formatClockDate(new Date(2026, 8, 3), 'zh-CN')).toBe('2026年9月3日星期四')
  })
  it('英文：weekday, month day, year', () => {
    expect(formatClockDate(new Date(2026, 8, 3), 'en')).toBe('Thursday, September 3, 2026')
  })
})
