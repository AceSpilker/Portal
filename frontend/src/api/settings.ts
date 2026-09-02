import request from './request'

/** 系统设置（api-spec §4.12：GET/PUT /api/settings，A 读 M 写）。 */
export const settingsApi = {
  /** 全量读取（key → 解析后的值） */
  getSettings: () => request.get<never, Record<string, unknown>>('/settings'),
  /** 批量写入（仅白名单键） */
  updateSettings: (values: Record<string, unknown>) =>
    request.put<never, null>('/settings', { values }),
}
