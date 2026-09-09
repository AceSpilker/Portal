import request from './request'

/** 系统设置（api-spec §4.12：GET/PUT /api/settings，A 读 M 写）。 */

export interface TokenRow {
  id: number
  name: string
  prefix: string
  scope: string
  revoked: boolean
  expires_at: string | null
  last_used_at: string | null
  created_at: string | null
  note: string
}

export interface AuditQuery {
  range: string
  action?: string
  method?: string
  user_id?: number
  page: number
}

/** 审计条目（087 起含请求执行详情；旧记录 method/path 等为空串/0） */
export interface AuditItem {
  id: number
  user_id: number | null
  username: string
  action: string
  method: string
  path: string
  query: string
  status: number
  duration_ms: number
  user_agent: string
  error_msg: string
  detail: string
  ip: string
  created_at: string
}

export interface UpdateInfo {
  current: string
  latest: string | null
  changelog: string
  has_update: boolean
  error?: string
}

export const settingsApi = {
  /** 全量读取（key → 解析后的值） */
  getSettings: () => request.get<never, Record<string, unknown>>('/settings'),
  /** 批量写入（仅白名单键） */
  updateSettings: (values: Record<string, unknown>) =>
    request.put<never, null>('/settings', { values }),

  // ---- P17.2 开放能力：API Token ----
  getTokens: () => request.get<never, TokenRow[]>('/tokens'),
  createToken: (payload: { name: string; scope: string; expires_at: string | null; note?: string }) =>
    request.post<never, TokenRow & { token: string }>('/tokens', payload),
  revokeToken: (id: number) => request.delete<never, { id: number }>(`/tokens/${id}`),

  // ---- P17.1 审计日志 ----
  auditLogs: (q: AuditQuery) =>
    request.get<never, { total: number; page: number; page_size: number; items: AuditItem[] }>('/audit-logs', {
      params: {
        range: q.range,
        action: q.action || undefined,
        method: q.method || undefined,
        user_id: q.user_id,
        page: q.page,
        page_size: 50,
      },
    }),
  auditExport: (range: string) =>
    request.get<never, { filename: string; csv: string }>('/audit-logs/export', {
      params: { range },
    }),

  // ---- P17.3 备份与恢复出厂 ----
  backupExport: () => request.get<never, Record<string, unknown>>('/backup/export'),
  factoryReset: (password: string) =>
    request.post<never, { apps: number; flows: number }>('/backup/factory-reset', { password }),

  // ---- P17.3/P17.5 健康自检完整版与在线更新 ----
  healthFull: () =>
    request.get<never, { data_dir_writable: boolean; scheduler_running: boolean; internet_ok: boolean | null; last_backup_at: string | null; mysql: unknown; redis: unknown; ai: unknown; checked_at: number }>('/system/health-report/full'),
  updateCheck: () =>
    request.get<never, UpdateInfo>('/system/update/check'),
  updateApply: (payload: { version: string; mode?: string }) =>
    request.post<never, { steps: string[]; note: string }>('/system/update/apply', payload),
  updateStatus: () =>
    request.get<never, { stage: string; last_result: string; checked_at: number | null }>('/system/update/status'),
}