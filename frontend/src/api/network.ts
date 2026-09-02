import request from './request'
import type { AccessType, AppUrl } from './portal'

/** 网络环境档案（M04-7；api-spec §3.3/§4.3）。 */
export interface NetworkProfile {
  id: number
  name: string
  match_type: 'cidr' | 'default'
  cidrs: string[]
  prefer_types: AccessType[]
  is_default: boolean
  sort: number
  enabled: boolean
}

export interface NetworkProfilePayload {
  name: string
  match_type: 'cidr' | 'default'
  cidrs?: string[]
  prefer_types?: AccessType[]
  sort?: number
  enabled?: boolean
}

export interface DetectResult {
  client_ip: string
  matched_profile: NetworkProfile | null
  candidates: NetworkProfile[]
}

export interface MyEnvResult {
  auto_profile: NetworkProfile | null
  manual_profile: NetworkProfile | null
  effective_profile: NetworkProfile | null
}

/** 智能解析结果（M04-10；api-spec §4.2）。 */
export interface ResolveResult {
  recommended: AppUrl | null
  alternatives: AppUrl[]
}

export interface MatrixUrl {
  id: number
  access_type: AccessType
  url: string
  label: string
  state: 'up' | 'down' | 'unknown'
  latency_ms: number | null
}

export interface MatrixApp {
  id: number
  name: string
  urls: MatrixUrl[]
}

export interface MatrixResult {
  probed_at: string
  apps: MatrixApp[]
}

export const networkApi = {
  // ---- 环境档案（M04-7）----
  listProfiles: () => request.get<never, NetworkProfile[]>('/network-profiles'),
  createProfile: (payload: NetworkProfilePayload) =>
    request.post<never, NetworkProfile>('/network-profiles', payload),
  updateProfile: (id: number, payload: Partial<NetworkProfilePayload>) =>
    request.put<never, NetworkProfile>(`/network-profiles/${id}`, payload),
  deleteProfile: (id: number) => request.delete<never, null>(`/network-profiles/${id}`),
  sortProfiles: (items: { id: number; sort: number }[]) =>
    request.put<never, null>('/network-profiles/sort', { items }),

  // ---- 环境探测 / 手动偏好（M04-8/9）----
  detect: () => request.post<never, DetectResult>('/network-profiles/detect'),
  getMyEnv: () => request.get<never, MyEnvResult>('/me/env'),
  setMyEnv: (profileId: number | null) =>
    request.put<never, MyEnvResult>('/me/env', { profile_id: profileId }),

  // ---- 智能解析 / 连通性矩阵（M04-10/13）----
  resolveApp: (appId: number, env: 'auto' | number = 'auto') =>
    request.get<never, ResolveResult>(`/apps/${appId}/resolve`, {
      params: { env },
    }),
  matrix: () =>
    request.get<never, MatrixResult>('/connectivity/matrix', { timeout: 60000 }),
}
