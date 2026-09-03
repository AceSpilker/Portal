import request from './request'

/** 应用探活（M07；dev-plan P6；api-spec §4.2/§5）。 */

export type ProbeState = 'up' | 'down' | 'unknown'

export interface ProbeStatus {
  state: ProbeState
  latency_ms: number | null
  message: string
}

export interface ProbeStatusMap {
  [appId: string]: ProbeStatus
}

export const probeApi = {
  /** 全部应用当前状态（首页磁贴初始加载） */
  status: () => request.get<never, ProbeStatusMap>('/probe/status'),
  /** 立即探活一次 */
  check: (appId: number) =>
    request.get<never, { state: ProbeState; latency_ms: number | null }>(`/apps/${appId}/check`, {
      method: 'POST',
    }),
  /** 站内通知（P6.4 最小集） */
  notifications: () =>
    request.get<never, { id: number; title: string; level: string; is_read: boolean }[]>(
      '/notifications',
    ),
}
