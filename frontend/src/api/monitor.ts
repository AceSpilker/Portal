import request from './request'

/** 服务器监控（M17；api-spec §4.4/§5，dev-plan P5.3/P5.4）。 */

export interface MonitorSystemInfo {
  hostname: string
  os: string
  kernel: string
  arch: string
  uptime: number
}

export interface MonitorCpu {
  percent: number
  per_core: number[]
  load: (number | null)[]
  cores: number
}

export interface MonitorMem {
  total: number
  used: number
  available: number
  percent: number
  buffers: number
  cached: number
  swap_total: number
  swap_used: number
  swap_percent: number
}

export interface MonitorDisk {
  mount: string
  total: number
  used: number
  percent: number
  inode_p: number | null
}

export interface MonitorNet {
  iface: string
  rx_rate: number
  tx_rate: number
  rx_total: number
  tx_total: number
  rx_today: number
  tx_today: number
}

export interface MonitorIo {
  read_rate: number
  write_rate: number
  read_iops: number
  write_iops: number
  read_total: number
  write_total: number
}

export interface MonitorGpu {
  name: string
  util: number
  mem_used: number | null
  mem_total: number | null
}

export interface MonitorTemp {
  name: string
  current: number | null
  high: number | null
  critical: number | null
}

export interface MonitorOverview {
  ts: string
  system: MonitorSystemInfo
  cpu: MonitorCpu
  mem: MonitorMem
  disks: MonitorDisk[]
  nets: MonitorNet[]
  io: MonitorIo | null
  gpu: MonitorGpu[]
  temps: MonitorTemp[]
}

export interface MonitorHistoryPoint {
  ts: string
  cpu?: number
  /** 每核使用率（cpu 指标返回） */
  cores?: number[]
  used?: number
  percent?: number
  rx?: number
  tx?: number
  current?: number
  /** 磁盘读写速率 B/s（io 指标返回） */
  read?: number
  write?: number
}

export interface MonitorHistory {
  metric: string
  range: string
  points: MonitorHistoryPoint[]
  /** disk/temp/gpu 指标：多序列共享对齐时间轴（缺失补 null） */
  mounts?: { mount: string; points: { ts: string; percent: number | null }[] }[]
  sensors?: { name: string; points: { ts: string; current: number | null }[] }[]
  gpus?: { name: string; points: { ts: string; util: number | null }[] }[]
}

export const monitorApi = {
  /** 实时概览（管理员）。 */
  system: () => request.get<never, MonitorOverview>('/monitor/system'),
  /** 历史曲线（管理员）。 */
  history: (metric: HistoryMetricParam, range: string) =>
    request.get<never, MonitorHistory>('/monitor/history', {
      params: { metric, range },
    }),
  /** 进程 Top 榜（M17-12；P10.1，管理员）。 */
  processes: (sort: 'cpu' | 'mem' = 'cpu', q = '', limit = 20) =>
    request.get<never, ProcRow[]>('/monitor/processes', { params: { sort, q, limit } }),
  /** 按容器资源占用（M17-13；P10.2，无 docker.sock 返回空数组）。 */
  dockerStats: () => request.get<never, DockerStat[]>('/monitor/docker-stats'),
  /** 证书到期即时检查（P10.5）。 */
  certs: () => request.get<never, CertInfo[]>('/monitor/certs'),
  /** 证书监控域名保存（M）。 */
  saveCertHosts: (hosts: string[]) => request.put<never, string[]>('/monitor/certs/hosts', { hosts }),
  /** 阈值告警规则 CRUD（M17-14/15；P10.3，管理员）。 */
  alertRules: () => request.get<never, AlertRule[]>('/alerts/rules'),
  createAlertRule: (body: AlertRuleBody) => request.post<never, AlertRule>('/alerts/rules', body),
  updateAlertRule: (id: number, body: AlertRuleBody) => request.put<never, AlertRule>(`/alerts/rules/${id}`, body),
  deleteAlertRule: (id: number) => request.delete(`/alerts/rules/${id}`),
  testAlertRule: (id: number) =>
    request.post<never, { current: number | null; threshold: number; op: string; violated: boolean | null }>(
      `/alerts/rules/${id}/test`,
    ),
  /** 告警事件历史（与站内通知同源 source=metric）。 */
  alertEvents: (range = '7d', level = '') =>
    request.get<never, AlertEvent[]>('/alerts/events', { params: { range, level } }),
}

export interface ProcRow {
  pid: number
  name: string
  username: string
  cpu_percent: number
  mem_percent: number
  mem_mb: number
}

export interface DockerStat {
  id: string
  name: string
  image: string
  state: string
  cpu_percent: number
  mem_used_mb: number
  mem_limit_mb: number
  mem_percent: number
  net_rx_mb: number
  net_tx_mb: number
}

export interface CertInfo {
  host: string
  days_left?: number
  not_after?: string
  level?: 'ok' | 'info' | 'warn' | 'error'
  error?: string
}

export type AlertMetric = 'cpu' | 'mem' | 'disk' | 'disk_io' | 'temp'

export interface AlertRule {
  id: number
  name: string
  metric: AlertMetric
  target: string | null
  op: '>' | '<'
  threshold: number
  duration_min: number
  level: 'warn' | 'error'
  enabled: boolean
  last_fired_at: string | null
}

export type AlertRuleBody = Omit<AlertRule, 'id' | 'last_fired_at'>

export interface AlertEvent {
  id: number
  title: string
  body: string
  level: 'info' | 'warn' | 'error'
  is_read: boolean
  created_at: string
}

type HistoryMetricParam = 'cpu' | 'mem' | 'net' | 'disk' | 'temp' | 'io' | 'gpu'

// ---- 数据与报表/多机纳管/SNMP（P21）----

export interface AgentNodeItem {
  hostname: string
  cpu_pct: number
  mem_pct: number
  disk_pct: number
  uptime_s: number
  last_seen_at: string
  online: boolean
}

export interface DayReport {
  date: string
  cpu: { min: number | null; avg: number | null; max: number | null }
  mem: { min: number | null; avg: number | null; max: number | null }
}

export const monitorEnterpriseApi = {
  exportCsv: (metric: string, range: string) =>
    request.get<never, { filename: string; csv: string }>('/monitor/export', {
      params: { metric, range },
    }),
  report: (days = 7) =>
    request.get<never, { days: DayReport[] }>('/monitor/report', { params: { days } }),
  agents: () => request.get<never, AgentNodeItem[]>('/monitor/agents'),
  registerAgent: (hostname: string) =>
    request.post<never, { hostname: string; token: string }>('/monitor/agents', { hostname }),
  agentScript: () =>
    request.get<never, { hostname: string; token: string; script: string }>('/monitor/agents/script'),
  snmpTest: (payload: { host: string; community: string; oid: string }) =>
    request.post<never, { ok: boolean; oid?: string; value?: string; error?: string }>(
      '/monitor/snmp/test',
      payload,
    ),
}
