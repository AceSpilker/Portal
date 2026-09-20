import request from './request'

/** 局域网设备与路由器 + 数据库服务（M19/M20；dev-plan P26/P27；api-spec §4.14/§4.15）。 */

// ---- 设备与路由器（M19）----

export interface LanSegment {
  iface: string
  address: string
  cidr: string
  is_gateway_iface: boolean
  gateway: string | null
  /** portal=由 Portal 访问地址派生（容器部署时的宿主网段来源）；nic=本机网卡 */
  source?: 'portal' | 'nic'
}

export interface LanSettings {
  scan_cidrs: string[]
  auto_scan: boolean
  scan_interval_min: number
  probe_ports: number[]
  dns_lookup: boolean
  concurrency: number
  extra_cidrs: string[]
  snmp: { enabled: boolean; community: string; timeout_s: number }
  snmp_community_set: boolean
}

export interface ScanRun {
  id: number
  kind: string
  cidrs: string[]
  status: 'running' | 'done' | 'failed'
  progress: number
  total: number
  found: number
  new_count: number
  gone_count: number
  message: string
  started_at: string
  finished_at: string | null
}

export interface LanDeviceItem {
  id: number
  ip: string
  mac: string | null
  hostname: string | null
  vendor: string | null
  device_type: 'router' | 'nas' | 'printer' | 'iot' | 'host' | 'db' | 'unknown'
  is_gateway: boolean
  open_ports: number[]
  source: string[]
  extra: Record<string, unknown>
  online: boolean
  first_seen_at: string
  last_seen_at: string
  events?: Array<{ event: string; created_at: string }>
}

export interface RouterInfo {
  gateway_ip: string | null
  device: LanDeviceItem | null
  upnp: {
    friendly_name?: string
    manufacturer?: string
    model_name?: string
    model_number?: string
    external_ip?: string | null
    connection_status?: string | null
    uptime_seconds?: number | null
  } | null
  admin_candidates: string[]
  snmp_enabled: boolean
}

export interface RouterClient {
  ip: string
  mac: string
  source: string
  vendor: string | null
}

export interface RouterInterface {
  index: string
  name: string
  speed_mbps: number
  in_octets: number
  out_octets: number
  in_bps: number
  out_bps: number
}

export interface DeviceEventRow {
  id: number
  device_id: number | null
  ip: string
  mac: string | null
  event: 'online' | 'offline'
  created_at: string
}

export const lanApi = {
  segments: () => request.get<never, LanSegment[]>('/lan/segments'),
  getSettings: () => request.get<never, LanSettings>('/lan/settings'),
  saveSettings: (body: Partial<LanSettings> & { snmp?: { enabled: boolean; community?: string; timeout_s?: number } }) =>
    request.put<never, LanSettings>('/lan/settings', body),
  startScan: (cidrs?: string[]) =>
    request.post<never, { run_id: number; cidrs: string[]; total: number }>('/lan/scan', cidrs?.length ? { cidrs } : {}),
  scanStatus: () =>
    request.get<never, { current: ScanRun | null; recent: ScanRun[] }>('/lan/scan/status'),
  devices: (params?: { type?: string; online?: string }) =>
    request.get<never, { items: LanDeviceItem[]; total: number }>('/lan/devices', { params }),
  device: (id: number) => request.get<never, LanDeviceItem>(`/lan/devices/${id}`),
  scans: (limit = 50) =>
    request.get<never, { runs: ScanRun[]; events: DeviceEventRow[] }>('/lan/scans', { params: { limit } }),
  createMonitor: (id: number, port?: number) =>
    request.post<never, { id: number; host: string; port: number }>(`/lan/devices/${id}/monitor`, port ? { port } : {}),
  addWolTarget: (id: number) =>
    request.post<never, { id: number; mac: string }>(`/lan/devices/${id}/wol-target`),
  router: () => request.get<never, RouterInfo>('/lan/router'),
  routerClients: () =>
    request.get<never, { items: RouterClient[]; total: number; sources: string[] }>('/lan/router/clients'),
  routerInterfaces: () =>
    request.get<never, { items: RouterInterface[]; reason: string | null }>('/lan/router/interfaces'),
  snmpTest: (body: { community?: string; host?: string }) =>
    request.post<never, { ok: boolean; detail: string }>('/lan/router/snmp/test', body),
}

// ---- 数据库服务（M20）----

export interface DbServiceItem {
  id: number
  host: string
  port: number
  service_type: string
  version: string | null
  state: 'up' | 'down' | 'unknown'
  latency_ms: number | null
  credential_id: number | null
  online: boolean
  first_seen_at: string
  last_seen_at: string
  device: { id: number; hostname: string | null; device_type: string } | null
}

export interface DbCredentialItem {
  id: number
  name: string
  service_type: 'mysql' | 'redis' | 'minio'
  host: string
  port: number
  username: string
  password_set: boolean
  extra: Record<string, unknown>
  enabled: boolean
  last_test_at: string | null
  last_test_ok: boolean | null
}

// ---- 查看器数据形状 ----

export interface MysqlOverview {
  version: string
  uptime_seconds: number
  threads_connected: number
  threads_running: number
  connections_total: number
  max_used_connections: number
  slow_queries: number
  bytes_received: number
  bytes_sent: number
  qps_avg: number
  hostname: string
  datadir: string
}

export interface MysqlSchemaRow {
  table_schema: string
  table_name: string
  engine: string | null
  table_rows: number | null
  size_mb: number | null
}

export interface RedisInfoSections {
  sections: Record<string, Record<string, unknown>>
  dbsize: number
}

export interface RedisKeyRow {
  key: string
  type: string
  ttl: number
}

export interface RedisKeyDetail {
  key: string
  type: string
  ttl: number
  db: number
  memory_bytes: number | null
  size_bytes: number | null
  binary?: boolean
  preview?: string
  truncated?: boolean
  items?: Array<{ field?: string; member?: string; score?: number; binary?: boolean; preview?: string }>
}

export interface MinioBucket {
  name: string
  created_at: string
  object_count: number
  size_bytes: number
  truncated: boolean
}

export interface MinioObject {
  key: string
  size: number
  etag: string
  last_modified: string
}

export const lanDbApi = {
  startScan: (cidrs?: string[]) =>
    request.post<never, { run_id: number; cidrs: string[] }>('/lan/db/scan', cidrs?.length ? { cidrs } : {}),
  services: (type?: string) =>
    request.get<never, { items: DbServiceItem[]; total: number }>('/lan/db/services', { params: type ? { type } : {} }),
  createMonitor: (sid: number) => request.post<never, { id: number }>(`/lan/db/services/${sid}/monitor`),
  credentials: () =>
    request.get<never, { items: DbCredentialItem[]; total: number }>('/lan/db/credentials'),
  createCredential: (body: Record<string, unknown>) =>
    request.post<never, DbCredentialItem>('/lan/db/credentials', body),
  updateCredential: (id: number, body: Record<string, unknown>) =>
    request.put<never, DbCredentialItem>(`/lan/db/credentials/${id}`, body),
  deleteCredential: (id: number) => request.delete(`/lan/db/credentials/${id}`),
  testCredential: (id: number) =>
    request.post<never, { ok: boolean; detail: string }>(`/lan/db/credentials/${id}/test`),
  // 查看器（只读）
  mysqlOverview: (sid: number) => request.get<never, MysqlOverview>(`/lan/db/mysql/${sid}/overview`),
  mysqlVariables: (sid: number, q = '') =>
    request.get<never, { total: number; items: Array<{ Variable_name: string; Value: string }> }>(
      `/lan/db/mysql/${sid}/variables`, { params: q ? { q } : {} },
    ),
  mysqlSchemas: (sid: number, params: { schema?: string; page?: number; page_size?: number }) =>
    request.get<never, { total: number; page: number; page_size: number; items: MysqlSchemaRow[] }>(
      `/lan/db/mysql/${sid}/schemas`, { params },
    ),
  mysqlProcesslist: (sid: number) =>
    request.get<never, { items: Array<Record<string, unknown>> }>(`/lan/db/mysql/${sid}/processlist`),
  redisInfo: (sid: number) => request.get<never, RedisInfoSections>(`/lan/db/redis/${sid}/info`),
  redisKeys: (sid: number, params: { db?: number; cursor?: number; match?: string }) =>
    request.get<never, { cursor: number; items: RedisKeyRow[] }>(`/lan/db/redis/${sid}/keys`, { params }),
  redisKey: (sid: number, params: { key: string; db?: number }) =>
    request.get<never, RedisKeyDetail>(`/lan/db/redis/${sid}/key`, { params }),
  redisSlowlog: (sid: number) =>
    request.get<never, { items: Array<{ id: number; started_at: number; duration_us: number; command: string }> }>(
      `/lan/db/redis/${sid}/slowlog`,
    ),
  redisClients: (sid: number) =>
    request.get<never, { items: Array<Record<string, unknown>> }>(`/lan/db/redis/${sid}/clients`),
  minioOverview: (sid: number) =>
    request.get<never, { healthy: boolean; server: string; bucket_count: number; object_count: number; total_size_bytes: number }>(
      `/lan/db/minio/${sid}/overview`,
    ),
  minioBuckets: (sid: number) =>
    request.get<never, { items: MinioBucket[] }>(`/lan/db/minio/${sid}/buckets`),
  minioObjects: (sid: number, params: { bucket: string; prefix?: string; token?: string }) =>
    request.get<never, { bucket: string; prefix: string; objects: MinioObject[]; truncated: boolean; next_token: string }>(
      `/lan/db/minio/${sid}/objects`, { params },
    ),
  minioObjectUrl: (sid: number, params: { bucket: string; key: string }) =>
    request.get<never, { url: string; expires_in: number }>(`/lan/db/minio/${sid}/object-url`, { params }),
}
