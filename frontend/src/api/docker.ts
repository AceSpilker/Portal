import request from './request'

/** Docker 容器管理（M08；dev-plan P12；api-spec §4.6，可选模块）。 */

export interface DockerContainer {
  id: string
  name: string
  image: string
  state: string
  status?: string
  cpu_percent?: number
  mem_used_mb?: number
  mem_percent?: number
}

export interface DockerDetail {
  id: string
  name: string
  image: string
  state: string
  ports: Array<{ container: string; host_ip: string; host_port: string }>
  mounts: Array<{ source: string; destination: string; mode: string }>
  env: string[]
}

export const dockerApi = {
  status: () => request.get<never, { enabled: boolean }>('/docker/status'),
  containers: () => request.get<never, DockerContainer[]>('/docker/containers'),
  op: (name: string, op: 'start' | 'stop' | 'restart') =>
    request.post<never, { ok: boolean }>(`/docker/containers/${name}/${op}`),
  logs: (name: string, tail = 200) =>
    request.get<never, { logs: string }>(`/docker/containers/${name}/logs`, { params: { tail } }),
  detail: (name: string) => request.get<never, DockerDetail>(`/docker/containers/${name}/detail`),
}

// ---- Docker 增强（P21.4）----

export interface DockerImage {
  id: string
  tags: string[]
  created: number
  size: number
}

export const dockerAdvancedApi = {
  batch: (names: string[], op: 'start' | 'stop' | 'restart') =>
    request.post<never, { results: Array<{ name: string; ok: boolean; error?: string }>; ok_count: number }>(
      '/docker/batch',
      { names, op },
    ),
  images: () => request.get<never, DockerImage[]>('/docker/images'),
  deleteImage: (id: string, force = false) =>
    request.delete<never, { id: string }>(`/docker/images/${encodeURIComponent(id)}`, { params: { force } }),
  updates: () =>
    request.get<never, Array<{ tag: string; created_days_old: number }>>('/docker/updates'),
}
