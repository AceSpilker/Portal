import request from './request'

/** 知识库（091）：数据源（服务器映射目录 / git 仓库）与在线阅读编辑。 */

export interface KnowledgeSource {
  id: number
  name: string
  kind: 'local' | 'git'
  path: string
  url: string
  branch: string
  enabled: boolean
  last_sync_at: string | null
  last_commit: string
  last_status: string
  last_error: string
}

export interface KnowledgeSourceBody {
  name: string
  kind: 'local' | 'git'
  path: string
  branch?: string
  username?: string
  password?: string
  enabled?: boolean
}

export interface KnowledgeTreeNode {
  name: string
  type: 'dir' | 'file'
  size: number | null
  mtime: number
}

export interface KnowledgeReadResult {
  path: string
  kind:
    | 'markdown'
    | 'text'
    | 'code'
    | 'html'
    | 'image'
    | 'video'
    | 'audio'
    | 'pdf'
    | 'docx'
    | 'xlsx'
    | 'pptx'
    | 'binary'
  editable: boolean
  text?: string
  html?: string
}

export const knowledgeApi = {
  sources: () => request.get<never, KnowledgeSource[]>('/knowledge/sources'),
  createSource: (payload: KnowledgeSourceBody) =>
    request.post<never, KnowledgeSource>('/knowledge/sources', payload),
  updateSource: (id: number, payload: Partial<KnowledgeSourceBody>) =>
    request.put<never, KnowledgeSource>(`/knowledge/sources/${id}`, payload),
  removeSource: (id: number) => request.delete<never, null>(`/knowledge/sources/${id}`),
  syncSource: (id: number) =>
    request.post<never, { cloned: boolean; commit: string; duration_ms: number }>(
      `/knowledge/sources/${id}/sync`,
    ),
  tree: (id: number, path = '') =>
    request.get<never, KnowledgeTreeNode[]>(`/knowledge/${id}/tree`, { params: path ? { path } : {} }),
  read: (id: number, path: string) =>
    request.get<never, KnowledgeReadResult>(`/knowledge/${id}/read`, { params: { path } }),
  write: (id: number, path: string, content: string) =>
    request.put<never, null>(`/knowledge/${id}/file`, { content }, { params: { path } }),
  rawUrl: (id: number, path: string) => `/api/knowledge/${id}/raw?path=${encodeURIComponent(path)}`,
}
