import request from './request'

/** 首页仪表盘布局（M02-2；api-spec §3.2 dashboard_layouts / §4.13）。 */
export interface LayoutItem {
  tab: string
  sort: number
  layout: Record<string, unknown>
}

export const layoutApi = {
  getMyLayouts: () => request.get<never, LayoutItem[]>('/me/layouts'),
  saveMyLayout: (tab: string, layout: Record<string, unknown>) =>
    request.put<never, { tab: string; layout: Record<string, unknown> }>('/me/layouts', {
      tab,
      layout,
    }),
}
