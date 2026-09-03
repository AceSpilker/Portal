import request from './request'

/** AI 助手（M05；dev-plan P13；api-spec §4.8）。流式对话走 WS /ws/ai-chat。 */

export interface AiProvider {
  id: number
  name: string
  base_url: string
  api_key: string
  model: string
  enabled: boolean
}

export interface AiConversationItem {
  id: number
  title: string
  provider: string
  created_at: string
}

export interface AiMessageItem {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export const aiApi = {
  providers: () => request.get<never, AiProvider[]>('/ai/providers'),
  createProvider: (body: Omit<AiProvider, 'id'>) => request.post<never, AiProvider>('/ai/providers', body),
  updateProvider: (id: number, body: Omit<AiProvider, 'id'>) =>
    request.put<never, AiProvider>(`/ai/providers/${id}`, body),
  deleteProvider: (id: number) => request.delete(`/ai/providers/${id}`),
  testProvider: (base_url: string, api_key: string) =>
    request.post<never, { ok: boolean; error?: string; models?: string[] }>('/ai/providers/test', {
      base_url,
      api_key,
    }),
  providerModels: (base_url: string, api_key: string) =>
    request.post<never, { ok: boolean; models: string[] }>('/ai/providers/models', { base_url, api_key }),

  conversations: () => request.get<never, AiConversationItem[]>('/ai/conversations'),
  createConversation: (title: string, provider = '') =>
    request.post<never, AiConversationItem>('/ai/conversations', { title, provider }),
  renameConversation: (id: number, title: string) => request.put(`/ai/conversations/${id}`, { title }),
  deleteConversation: (id: number) => request.delete(`/ai/conversations/${id}`),
  messages: (id: number) => request.get<never, AiMessageItem[]>(`/ai/conversations/${id}/messages`),

  generateAppDraft: (description: string) =>
    request.post<
      never,
      { name: string; description: string; health_type: string; health_target: string; tags: string[] }
    >('/ai/generate/app-draft', { description }),
}
