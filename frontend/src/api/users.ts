import request from './request'

/** 用户管理（M01-11；dev-plan 7.4；api-spec §4.2）。仅管理员。 */

export interface UserItem {
  id: number
  username: string
  role: 'admin' | 'user'
  is_active: boolean
  remark: string
  token_version: number
  created_at: string | null
}

export interface UserPage {
  items: UserItem[]
  total: number
  page: number
  page_size: number
}

export const usersApi = {
  list: (keyword = '', page = 1, pageSize = 50) =>
    request.get<never, UserPage>('/users', {
      params: { keyword, page, page_size: pageSize },
    }),
  create: (body: { username: string; password: string; role: string; remark?: string }) =>
    request.post<never, UserItem>('/users', body),
  update: (id: number, body: { role: string; remark?: string }) =>
    request.put<never, UserItem>(`/users/${id}`, body),
  setStatus: (id: number, enabled: boolean) =>
    request.put<never, UserItem>(`/users/${id}/status`, { enabled }),
  resetPassword: (id: number, password: string) =>
    request.put<never, null>(`/users/${id}/password`, { password }),
  kick: (id: number) => request.post<never, null>(`/users/${id}/kick`),
}
