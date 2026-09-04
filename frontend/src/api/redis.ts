import request from './request'

/** Redis 缓存与会话（P25；api-spec §4.12）。 */

export interface RedisConfig {
  host: string
  port: number
  db: number
  key_prefix: string
  enabled: boolean
  password: string
  password_set: boolean
}

export interface RedisStatus {
  enabled: boolean
  mode: 'redis' | 'memory' | 'redis-degraded'
  connected: boolean
  degraded: boolean
  key_prefix: string
  last_error: string
}

export const redisApi = {
  getConfig: () => request.get<never, RedisConfig>('/settings/redis'),
  saveConfig: (payload: Partial<RedisConfig> & { password?: string }) =>
    request.put<never, RedisConfig>('/settings/redis', payload),
  test: (payload: Partial<RedisConfig> & { password?: string }) =>
    request.post<never, { ok: boolean; server_version?: string; error?: string }>('/redis/test', payload),
  status: () => request.get<never, RedisStatus>('/redis/status'),
}
