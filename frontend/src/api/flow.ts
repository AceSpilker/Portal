import request from './request'
import type { FlowGraph } from '../utils/canvas'

/** Flow 自动化·表单版 + 画布（M06；dev-plan P14/P19；api-spec §4.7）。 */

export type FlowTrigger = 'cron' | 'webhook' | 'manual' | 'event'
export type FlowActionType = 'http' | 'notify' | 'condition' | 'ssh' | 'docker' | 'ai' | 'delay' | 'variable'

export interface FlowAction {
  type: FlowActionType
  name?: string
  expression?: string
  config?: Record<string, unknown>
}

export interface FlowItem {
  id: number
  name: string
  description: string
  trigger_type: FlowTrigger
  trigger_config: Record<string, unknown>
  actions: FlowAction[]
  graph: FlowGraph | null
  enabled: boolean
  webhook_token: string | null
  retry: number
  retry_interval: number
  last_run_at: string | null
}

export interface FlowRunItem {
  id: number
  flow_id: number
  trigger: string
  status: 'running' | 'success' | 'failed'
  steps: Array<Record<string, unknown>>
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
}

export interface FlowBody {
  name: string
  description: string
  trigger_type: FlowTrigger
  trigger_config: Record<string, unknown>
  actions: FlowAction[]
  graph?: FlowGraph | null
  enabled: boolean
  retry: number
  retry_interval: number
}

export interface FlowTemplate {
  key: string
  name: string
  description: string
  trigger_type: FlowTrigger
  trigger_config: Record<string, unknown>
  has_canvas: boolean
}

export const flowApi = {
  list: () => request.get<never, FlowItem[]>('/flows'),
  get: (id: number) => request.get<never, FlowItem>(`/flows/${id}`),
  create: (body: FlowBody) => request.post<never, FlowItem>('/flows', body),
  update: (id: number, body: FlowBody) => request.put<never, FlowItem>(`/flows/${id}`, body),
  remove: (id: number) => request.delete(`/flows/${id}`),
  run: (id: number) => request.post<never, { run_id: number; status: string }>(`/flows/${id}/run`),
  dryRun: (id: number) =>
    request.post<never, { run_id: number; status: string; steps: Array<Record<string, unknown>> }>(
      `/flows/${id}/dry-run`,
    ),
  runs: (id: number, limit = 20) => request.get<never, FlowRunItem[]>(`/flows/${id}/runs`, { params: { limit } }),
  runDetail: (runId: number) => request.get<never, FlowRunItem>(`/flow-runs/${runId}`),
  templates: () => request.get<never, FlowTemplate[]>('/flows/templates'),
  fromTemplate: (key: string, name?: string) =>
    request.post<never, FlowItem>('/flows/from-template', { key, name }),
  exportFlow: (id: number) =>
    request.get<never, Record<string, unknown>>(`/flows/${id}/export`),
  importFlow: (payload: Record<string, unknown>) =>
    request.post<never, FlowItem>('/flows/import', payload),
  resetToken: (id: number) => request.post<never, { webhook_token: string }>(`/flows/${id}/reset-token`),
}
