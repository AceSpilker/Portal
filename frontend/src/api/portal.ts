import request from './request'

export type AccessType = 'domain' | 'lan' | 'ssh' | 'vpn' | 'custom'
export type IconType = 'url' | 'upload' | 'emoji'
export type OpenMode = 'newtab' | 'current' | 'iframe'
export type Visibility = 'all' | 'admin' | 'users'
export type HealthType = '' | 'http' | 'tcp' | 'keyword'

export interface Category {
  id: number
  name: string
  icon: string | null
  sort: number
  collapsed: boolean
  /** 列表接口聚合返回；其他接口为 0 */
  app_count: number
}

export interface AppUrl {
  id: number
  app_id: number
  access_type: AccessType
  url: string
  label: string
  sort: number
}

export interface PortalApp {
  id: number
  name: string
  description: string
  icon: string | null
  icon_type: IconType
  category_id: number | null
  sort: number
  enabled: boolean
  health_type: HealthType
  health_target: string | null
  health_interval: number
  open_mode: OpenMode
  visibility: Visibility
  favorite: boolean
  tags: string[]
  remark: string
  doc_url: string | null
  urls: AppUrl[]
}

export interface CategoryPayload {
  name: string
  icon?: string | null
  sort?: number
  collapsed?: boolean
}

export interface AppPayload {
  name: string
  description?: string
  icon?: string | null
  icon_type?: IconType
  category_id?: number | null
  sort?: number
  enabled?: boolean
  health_type?: HealthType
  health_target?: string | null
  health_interval?: number
  open_mode?: OpenMode
  visibility?: Visibility
  favorite?: boolean
  tags?: string[]
  remark?: string
  doc_url?: string | null
}

export interface AppUrlPayload {
  access_type: AccessType
  url: string
  label?: string
  sort?: number | null
}

export interface SortItem {
  id: number
  sort: number
  category_id?: number
}

export interface ImportResult {
  categories: number
  apps: number
  urls: number
}

export const portalApi = {
  // ---- 分组 ----
  listCategories: () => request.get<never, Category[]>('/categories'),
  createCategory: (payload: CategoryPayload) =>
    request.post<never, Category>('/categories', payload),
  updateCategory: (id: number, payload: Partial<CategoryPayload>) =>
    request.put<never, Category>(`/categories/${id}`, payload),
  deleteCategory: (id: number) => request.delete<never, null>(`/categories/${id}`),
  sortCategories: (items: SortItem[]) =>
    request.put<never, null>('/categories/sort', { items }),

  // ---- 应用 ----
  listApps: (params?: { keyword?: string; category?: number; tag?: string }) =>
    request.get<never, PortalApp[]>('/apps', { params }),
  getApp: (id: number) => request.get<never, PortalApp>(`/apps/${id}`),
  createApp: (payload: AppPayload) => request.post<never, PortalApp>('/apps', payload),
  updateApp: (id: number, payload: Partial<AppPayload>) =>
    request.put<never, PortalApp>(`/apps/${id}`, payload),
  deleteApp: (id: number) => request.delete<never, null>(`/apps/${id}`),
  sortApps: (items: SortItem[]) => request.put<never, null>('/apps/sort', { items }),

  // ---- 访问入口 ----
  listUrls: (appId: number) => request.get<never, AppUrl[]>(`/apps/${appId}/urls`),
  createUrl: (appId: number, payload: AppUrlPayload) =>
    request.post<never, AppUrl>(`/apps/${appId}/urls`, payload),
  updateUrl: (id: number, payload: Partial<AppUrlPayload>) =>
    request.put<never, AppUrl>(`/app-urls/${id}`, payload),
  deleteUrl: (id: number) => request.delete<never, null>(`/app-urls/${id}`),

  // ---- 图标 / 导入导出 ----
  uploadIcon: (filename: string, dataBase64: string) =>
    request.post<never, { url: string }>('/apps/upload-icon', {
      filename,
      data: dataBase64,
    }),
  fetchFavicon: (url: string) =>
    request.get<never, { url: string }>('/apps/favicon', { params: { url } }),
  exportApps: () =>
    request.get<never, { version: number; exported_at: string; categories: unknown[]; apps: unknown[] }>(
      '/apps/export',
    ),
  importApps: (payload: unknown) =>
    request.post<never, ImportResult>('/apps/import', payload),
}
