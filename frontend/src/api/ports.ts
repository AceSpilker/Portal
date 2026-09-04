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

// ---- 端口进阶（M18-8~12；P20.3）----

export interface PortLatencyPoint {
  checked_at: string
  state: string
  latency_ms: number | null
}

export interface PortLatencyHistory {
  monitor_id: number
  range: string
  points: PortLatencyPoint[]
  avg_ms: number | null
  max_ms: number | null
  up_pct: number | null
}

export interface ListenChange {
  id: number
  added: Array<{ host: string; port: number | string; process: string }>
  removed: Array<{ host: string; port: number | string; process: string }>
  created_at: string
}

export interface ExposedPort {
  port: number
  process: string
  host: string
}

export interface PublicReach {
  public_ip: string | null
  items: Array<{ monitor_id: number; name: string; port: number; local_state: string; public_reachable: boolean | null }>
}

export const portsAdvancedApi = {
  latency: (monitorId: number, range = '24h') =>
    request.get<never, PortLatencyHistory>(`/ports/monitors/${monitorId}/latency`, { params: { range } }),
  checkNow: (monitorId: number) =>
    request.post<never, { state: string; latency_ms: number | null }>(`/ports/monitors/${monitorId}/check`),
  listenHistory: (limit = 20) =>
    request.get<never, ListenChange[]>('/ports/listen-history', { params: { limit } }),
  exposed: () => request.get<never, ExposedPort[]>('/ports/exposed'),
  publicReach: () => request.get<never, PublicReach>('/ports/public-reach'),
}
