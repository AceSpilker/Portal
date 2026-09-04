import request from './request'

/** SSH 托管隧道（M04-16；dev-plan P20.1/P20.2）。 */

export interface SSHCredential {
  id: number
  name: string
  host: string
  port: number
  username: string
  has_secret: boolean
  note: string
}

export interface Tunnel {
  id: number
  name: string
  credential_id: number
  remote_host: string
  remote_port: number
  local_port: number
  auto_close_min: number
  status: 'stopped' | 'running' | 'error' | 'degraded'
  last_error: string
  last_active_at: string | null
}

export const tunnelsApi = {
  // 凭据
  listCredentials: () => request.get<never, SSHCredential[]>('/ssh-credentials'),
  createCredential: (payload: {
    name: string
    host: string
    port: number
    username: string
    password?: string
    private_key?: string
    note?: string
  }) => request.post<never, SSHCredential>('/ssh-credentials', payload),
  deleteCredential: (id: number) => request.delete<never, { id: number }>(`/ssh-credentials/${id}`),
  // 隧道
  list: () => request.get<never, Tunnel[]>('/tunnels'),
  create: (payload: {
    name: string
    credential_id: number
    remote_host: string
    remote_port: number
    local_port?: number
    auto_close_min?: number
  }) => request.post<never, Tunnel>('/tunnels', payload),
  start: (id: number) => request.post<never, Tunnel>(`/tunnels/${id}/start`),
  stop: (id: number) => request.post<never, Tunnel>(`/tunnels/${id}/stop`),
  remove: (id: number) => request.delete<never, { id: number }>(`/tunnels/${id}`),
  openUrl: (id: number) =>
    request.get<never, { url: string; expires_in: number }>(`/tunnels/${id}/open-url`),
}
