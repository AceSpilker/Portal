/** P5 单测关卡：监控工具函数（单位换算 / 时长格式化 / WS 地址构造）。 */
import { describe, expect, it } from 'vitest'
import { buildMonitorWsUrl, formatBytes, formatRate, formatUptime } from '../utils/monitor'

describe('formatBytes / formatRate', () => {
  it('1024 进制换算，B 不带小数', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1536 * 1024)).toBe('1.5 MB')
    expect(formatRate(2 * 1024 * 1024)).toBe('2.0 MB/s')
  })
  it('非法输入返回占位符', () => {
    expect(formatBytes(-1)).toBe('-')
    expect(formatBytes(Number.NaN)).toBe('-')
  })
})

describe('formatUptime', () => {
  it('中文：天/小时/分钟分层', () => {
    expect(formatUptime(90 * 86400 + 5 * 3600 + 720, 'zh-CN')).toBe('90天5小时12分')
    expect(formatUptime(3 * 3600 + 60, 'zh-CN')).toBe('3小时1分')
    expect(formatUptime(59, 'zh-CN')).toBe('0分钟')
  })
  it('英文：Xd Xh Xm', () => {
    expect(formatUptime(2 * 86400 + 3600, 'en')).toBe('2d 1h 0m')
  })
  it('非法输入返回占位符', () => {
    expect(formatUptime(-5, 'zh-CN')).toBe('-')
  })
})

describe('buildMonitorWsUrl', () => {
  it('跟随页面协议与 host，token 走 query 并转义', () => {
    Object.defineProperty(window, 'location', {
      value: { protocol: 'http:', host: 'localhost:5173' },
      writable: true,
    })
    expect(buildMonitorWsUrl('a b&c')).toBe('ws://localhost:5173/ws/monitor?token=a%20b%26c')
  })
})
