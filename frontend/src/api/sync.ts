import request from './request'

/** MySQL 镜像同步（P23；api-spec §4.12）。 */

export interface SyncConfig {
  host: string
  port: number
  user: string
  database: string
  interval_min: number
  enabled: boolean
  password: string
  password_set: boolean
}

export interface SyncTableState {
  table: string
  last_push_at: string | null
  rows_pushed: number
  status: string
  fail_count: number
  message: string
}

export const syncApi = {
  getConfig: () => request.get<never, SyncConfig>('/settings/sync'),
  saveConfig: (payload: Partial<SyncConfig> & { password?: string }) =>
    request.put<never, SyncConfig>('/settings/sync', payload),
  testConnection: (payload: Partial<SyncConfig> & { password?: string }) =>
    request.post<never, { ok: boolean; server_version?: string; error?: string }>('/mysql/test', payload),
  push: () => request.post<never, { enabled: boolean; pushed: number; tables: number; error?: string }>('/sync/push'),
  status: () =>
    request.get<never, { enabled: boolean; host: string; database: string; interval_min: number; tables: SyncTableState[] }>('/sync/status'),
  restore: () =>
    request.post<never, { ok: boolean; backup: string; error?: string }>('/sync/restore', { confirm: true }),
}
