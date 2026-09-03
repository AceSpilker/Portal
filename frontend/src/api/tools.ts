import request from './request'

/** 工具箱后端接口（M10-1/3；dev-plan 7.3）。 */

export interface WolTarget {
  id: number
  name: string
  mac: string
  note: string
}

export const toolsApi = {
  /** 网络唤醒：广播魔术包 */
  wol: (mac: string, port = 9) =>
    request.post<never, { sent_bytes: number }>('/tools/wol', { mac, port }),
  /** TCP 端口连通测试（从服务端发起） */
  portCheck: (host: string, port: number) =>
    request.post<never, { ok: boolean; latency_ms: number | null }>('/tools/port-check', {
      host,
      port,
    }),
  wolTargets: {
    list: () => request.get<never, WolTarget[]>('/tools/wol-targets'),
    create: (body: { name: string; mac: string; note?: string }) =>
      request.post<never, WolTarget>('/tools/wol-targets', body),
    remove: (id: number) => request.delete<never, null>(`/tools/wol-targets/${id}`),
  },
}
