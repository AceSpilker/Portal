import request from './request'

/** 端口监控（M18；dev-plan P11；api-spec §4.5）。 */

export interface ListenRow {
  proto: string
  addr: string
  port: number
  pid: number | null
  proc: string
  cmdline: string
}

export interface LookupRow {
  proto: string
  addr: string
  port: number
  status: string
  pid: number | null
  proc: string
  cmdline: string
  username: string
}

export interface PortMonitorItem {
  id: number
  name: string
  host: string
  port: number
  app_id: number | null
  app_name: string | null
  interval: number
  enabled: boolean
  state: 'up' | 'down' | 'unknown'
  last_latency_ms: number | null
  last_checked_at: string | null
}

export interface PortEventItem {
  id: number
  monitor_id: number
  monitor_name: string
  app_id: number | null
  app_name: string | null
  event: 'up' | 'down'
  latency_ms: number | null
  created_at: string
}

export interface PortMonitorBody {
  name: string
  host: string
  port: number
  app_id: number | null
  interval: number
  enabled: boolean
}

export const portsApi = {
  listen: () => request.get<never, ListenRow[]>('/ports/listen'),
  lookup: (port: number) => request.get<never, LookupRow[]>('/ports/lookup', { params: { port } }),
  monitors: () => request.get<never, PortMonitorItem[]>('/ports/monitors'),
  create: (body: PortMonitorBody) => request.post<never, PortMonitorItem>('/ports/monitors', body),
  update: (id: number, body: PortMonitorBody) => request.put<never, PortMonitorItem>(`/ports/monitors/${id}`, body),
  remove: (id: number) => request.delete(`/ports/monitors/${id}`),
  import: (items: string[]) =>
    request.post<never, { created: number; skipped: number }>('/ports/monitors/import', { items }),
  events: (limit = 50) => request.get<never, PortEventItem[]>('/ports/events', { params: { limit } }),
  monitorEvents: (id: number) => request.get<never, PortEventItem[]>(`/ports/monitors/${id}/events`),
}
