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
}

type HistoryMetricParam = 'cpu' | 'mem' | 'net' | 'disk' | 'temp' | 'io' | 'gpu'
