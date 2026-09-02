/** SSH 本地转发命令构造测试（M04-15；dev-plan P3.7 单测关卡）。 */
import { describe, expect, it } from 'vitest'
import { buildSshCommand, parseInner, parseJump, suggestLocalPort } from '../utils/ssh'
import type { AppUrl } from '../api/portal'

const url = (id: number, access_type: AppUrl['access_type'], u: string): AppUrl => ({
  id,
  app_id: 1,
  access_type,
  url: u,
  label: '',
  sort: 0,
})

describe('parseJump', () => {
  it('解析 user@host:port / host / host:port', () => {
    expect(parseJump('root@192.168.1.5:2222')).toEqual({
      user: 'root',
      host: '192.168.1.5',
      port: 2222,
    })
    expect(parseJump('jump.example.com')).toEqual({ user: '', host: 'jump.example.com', port: 22 })
    expect(parseJump('host:22')).toEqual({ user: '', host: 'host', port: 22 })
  })

  it('非法输入返回 null', () => {
    expect(parseJump('')).toBeNull()
    expect(parseJump('ssh -L 18096:1.2.3.4:80 a@b')).toBeNull()
  })
})

describe('parseInner', () => {
  it('提取 host 与端口，https 兜底 443', () => {
    expect(parseInner('http://192.168.1.10:8096')).toEqual({ host: '192.168.1.10', port: 8096 })
    expect(parseInner('https://jf.example.com')).toEqual({ host: 'jf.example.com', port: 443 })
    expect(parseInner('192.168.1.10:8096')).toEqual({ host: '192.168.1.10', port: 8096 })
    expect(parseInner('')).toBeNull()
  })
})

describe('buildSshCommand', () => {
  const jump = url(1, 'ssh', 'root@jump.example.com:2222')
  const lan = url(2, 'lan', 'http://192.168.1.10:8096')

  it('生成带 -L 的完整命令（非 22 端口加 -p）', () => {
    expect(buildSshCommand(jump, lan, 18096)).toBe(
      'ssh -L 18096:192.168.1.10:8096 root@jump.example.com -p 2222',
    )
  })

  it('无内网目标时仅登录跳板机；22 端口省略 -p', () => {
    expect(buildSshCommand(jump, null, 18096)).toBe('ssh root@jump.example.com -p 2222')
    const stdJump = url(3, 'ssh', 'admin@10.0.0.2')
    expect(buildSshCommand(stdJump, null, 18000)).toBe('ssh admin@10.0.0.2')
  })

  it('跳板地址无法解析时返回 null', () => {
    expect(buildSshCommand(url(4, 'ssh', 'not a url'), lan, 18000)).toBeNull()
  })
})

describe('suggestLocalPort', () => {
  it('稳定且落在 18000~18999', () => {
    expect(suggestLocalPort(1)).toBe(18001)
    expect(suggestLocalPort(999)).toBe(18999)
    expect(suggestLocalPort(1000)).toBe(18000)
  })
})
