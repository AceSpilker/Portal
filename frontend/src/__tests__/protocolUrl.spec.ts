/** ProtocolUrlInput 共享逻辑单测（066：协议前缀改下拉选择）。 */
import { describe, expect, it } from 'vitest'
import { joinProtocol, splitProtocol, stripProtocol } from '../utils/protocolUrl'

describe('splitProtocol', () => {
  it('http/https/ws/ftp 前缀均能拆出', () => {
    expect(splitProtocol('https://x.com/a')).toEqual({ proto: 'https://', rest: 'x.com/a' })
    expect(splitProtocol('http://192.168.1.1:8096')).toEqual({ proto: 'http://', rest: '192.168.1.1:8096' })
    expect(splitProtocol('wss://host/ws')).toEqual({ proto: 'wss://', rest: 'host/ws' })
    expect(splitProtocol('ftp://f/x')).toEqual({ proto: 'ftp://', rest: 'f/x' })
  })
  it('无前缀原样返回空协议', () => {
    expect(splitProtocol('nas.local:5000')).toEqual({ proto: '', rest: 'nas.local:5000' })
    expect(splitProtocol('')).toEqual({ proto: '', rest: '' })
  })
})

describe('stripProtocol', () => {
  it('剥离协议；无协议原样返回', () => {
    expect(stripProtocol('https://x.com')).toBe('x.com')
    expect(stripProtocol('x.com')).toBe('x.com')
  })
})

describe('joinProtocol', () => {
  it('正常拼接', () => {
    expect(joinProtocol('https://', 'x.com')).toBe('https://x.com')
    expect(joinProtocol('http://', 'a:8080/b')).toBe('http://a:8080/b')
  })
  it('地址为空返回空串，避免产出纯协议值；地址自带协议时被剥离', () => {
    expect(joinProtocol('https://', '')).toBe('')
    expect(joinProtocol('https://', 'http://x.com')).toBe('https://x.com')
  })
})
