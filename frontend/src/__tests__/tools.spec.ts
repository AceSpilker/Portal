import { describe, expect, it } from 'vitest'
import {
  base64Decode,
  base64Encode,
  dateToUnix,
  generatePassword,
  unixToDate,
  urlDecode,
  urlEncode,
} from '../utils/tools'

describe('编解码工具', () => {
  it('Base64 编解码往返（含中文与表情）', () => {
    for (const text of ['hello world', '中文内容', '带表情 🎬 的文本']) {
      expect(base64Decode(base64Encode(text))).toBe(text)
    }
  })

  it('URL 编解码往返', () => {
    const text = 'a=1&b=中文'
    expect(urlDecode(urlEncode(text))).toBe(text)
    expect(urlEncode('a b')).toBe('a%20b')
  })
})

describe('时间戳转换', () => {
  it('秒级时间戳 → 本地时间字符串', () => {
    // UTC 2026-09-02T00:00:00Z → 180000 秒；本地时区相关，仅断言格式与非空
    const out = unixToDate('1800000000')
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
  })

  it('毫秒级时间戳自动识别', () => {
    expect(unixToDate('1800000000000')).toBe(unixToDate('1800000000'))
  })

  it('非法输入返回空串', () => {
    expect(unixToDate('abc')).toBe('')
    expect(unixToDate('')).toBe('')
  })

  it('datetime-local → 秒级时间戳往返', () => {
    const ts = dateToUnix('2026-09-02T12:00:00')
    expect(ts).toMatch(/^\d{10}$/)
    // 转回本地时间字符串，日期部分一致（同一天）
    expect(unixToDate(ts).slice(0, 10)).toBe('2026-09-02')
  })
})

describe('密码生成器', () => {
  const SETS = {
    upper: 'ABCDEFGHJKLMNPQRSTUVWXYZ',
    lower: 'abcdefghijkmnpqrstuvwxyz',
    digits: '23456789',
    symbols: '!@#$%^&*()-_=+[]{};:,.?',
  }
  const has = (pwd: string, set: string) => [...pwd].some((ch) => set.includes(ch))

  it('按指定长度生成', () => {
    expect(generatePassword({ length: 16, upper: true, lower: true, digits: true, symbols: true })).toHaveLength(16)
    expect(generatePassword({ length: 8, upper: false, lower: true, digits: true, symbols: false })).toHaveLength(8)
  })

  it('只含勾选的字符集', () => {
    const pwd = generatePassword({ length: 32, upper: false, lower: false, digits: true, symbols: false })
    expect(pwd).toMatch(/^[23456789]+$/)
  })

  it('每种勾选字符集至少出现一次', () => {
    for (let i = 0; i < 20; i++) {
      const pwd = generatePassword({ length: 12, upper: true, lower: true, digits: true, symbols: true })
      expect(has(pwd, SETS.upper)).toBe(true)
      expect(has(pwd, SETS.lower)).toBe(true)
      expect(has(pwd, SETS.digits)).toBe(true)
      expect(has(pwd, SETS.symbols)).toBe(true)
    }
  })

  it('未勾选任何字符集返回空串', () => {
    expect(generatePassword({ length: 12, upper: false, lower: false, digits: false, symbols: false })).toBe('')
  })
})
