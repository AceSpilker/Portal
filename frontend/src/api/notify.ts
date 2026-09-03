import request from './request'

/**
 * 通知中心 API（M09；dev-plan P9.1/P9.2/P9.3；api-spec §4.9）。
 */

export type NotifyLevel = 'info' | 'warn' | 'error'
export type ChannelType = 'bark' | 'telegram' | 'smtp' | 'webhook' | 'wecom' | 'dingtalk' | 'feishu' | 'ntfy'
export type NotifyEvent =
  | 'app_down'
  | 'app_up'
  | 'metric_alert'
  | 'port_down'
  | 'port_up'
  | 'flow_failed'
  | 'system'

export interface NotificationItem {
  id: number
  title: string
  body: string
  level: NotifyLevel
  source: string
  is_read: boolean
  created_at: string
}

export interface NotificationPage {
  items: NotificationItem[]
  total: number
  unread: number
}

export interface NotifyChannel {
  id: number
  type: ChannelType
  name: string
  enabled: boolean
  config: Record<string, unknown>
}

export interface NotifyRule {
  id: number
  event: NotifyEvent
  channel_ids: number[]
  enabled: boolean
  quiet_start: string | null
  quiet_end: string | null
}

export const notifyApi = {
  list: (params: { level?: string; unread?: number; limit?: number; offset?: number } = {}) =>
    request.get<never, NotificationPage>('/notifications', { params }),
  unreadCount: () => request.get<never, { unread: number }>('/notifications/unread-count'),
  markRead: (id: number) => request.put(`/notifications/${id}/read`),
  readAll: () => request.put('/notifications/read-all'),
  remove: (id: number) => request.delete(`/notifications/${id}`),

  channels: () => request.get<never, NotifyChannel[]>('/notify-channels'),
  createChannel: (body: Omit<NotifyChannel, 'id'>) => request.post<never, NotifyChannel>('/notify-channels', body),
  updateChannel: (id: number, body: Omit<NotifyChannel, 'id'>) =>
    request.put<never, NotifyChannel>(`/notify-channels/${id}`, body),
  deleteChannel: (id: number) => request.delete(`/notify-channels/${id}`),
  testChannel: (id: number) => request.post<never, { sent: boolean }>(`/notify-channels/${id}/test`),

  rules: () => request.get<never, NotifyRule[]>('/notify-rules'),
  replaceRules: (rules: Array<Omit<NotifyRule, 'id'>>) => request.put<never, NotifyRule[]>('/notify-rules', { rules }),
}
