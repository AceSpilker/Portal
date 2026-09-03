import request from './request'

/** 应用增强（M03；dev-plan P15.1）+ 小组件（M02-11/13~15）。 */

export interface RecycleItem {
  id: number
  name: string
  description: string
  deleted_at: string | null
}

export interface AppTemplate {
  key: string
  name: string
  description: string
  icon: string
  category: string
  health_type: string
  health_target: string
  tags: string[]
}

export interface WeatherInfo {
  city: string
  temp_c: number
  feels_c: number
  desc: string
  humidity: number
  days: Array<{ date: string; max: number; min: number; desc: string }>
}

export interface WidgetsSummary {
  notifications: Array<{ id: number; title: string; level: string; is_read: boolean }>
  flow_runs: Array<{ id: number; flow: string; status: string; finished_at: string | null }>
  docker: { running: number; stopped: number } | null
}

export const appsEnhApi = {
  recycleBin: () => request.get<never, RecycleItem[]>('/apps/recycle-bin'),
  restore: (id: number) => request.post<never, { id: number }>(`/apps/${id}/restore`),
  purge: (id: number) => request.delete(`/apps/${id}/purge`),
  templates: () => request.get<never, AppTemplate[]>('/apps/templates'),
  fromTemplate: (key: string, host: string, category_id: number | null = null) =>
    request.post<never, { id: number; name: string; entry: string }>('/apps/from-template', {
      key,
      host,
      category_id,
    }),
  batch: (ids: number[], op: 'enable' | 'disable' | 'recycle' | 'move', category_id: number | null = null) =>
    request.post<never, { count: number }>('/apps/batch', { ids, op, category_id }),
  precheck: (id: number) =>
    request.post<
      never,
      { app_id: number; ok: boolean; state: string; latency_ms: number | null; alternatives: Array<{ app_id: number; name: string; health_target: string }> }
    >(`/apps/${id}/precheck`),
  weather: () => request.get<never, WeatherInfo | null>('/widgets/weather'),
  summary: () => request.get<never, WidgetsSummary>('/widgets/summary'),
}
