/**
 * 命令面板搜索（M02-6；dev-plan P4.4）。
 *
 * 模糊匹配：查询串按字符顺序做子序列匹配（如 "jl" 命中 Jellyfin），
 * 得分 = 命中字段权重（名称 3 / 标签 2 / 描述 1）+ 连续命中加成 - 分散惩罚，
 * 收藏应用固定优先（M02-9 搜索优先）。
 */
import type { PortalApp } from '../api/portal'

/** query 的字符是否按顺序出现在 text 中；返回命中的末位下标（-1 为不命中）。 */
export function isSubsequence(query: string, text: string): number {
  let i = 0
  for (let j = 0; j < text.length && i < query.length; j++) {
    if (text[j] === query[i]) i++
  }
  return i === query.length ? 1 : -1
}

/** 单应用匹配得分；不匹配返回 -1。 */
export function matchScore(app: PortalApp, rawQuery: string): number {
  const query = rawQuery.trim().toLowerCase()
  if (!query) return -1
  const name = app.name.toLowerCase()
  const desc = (app.description || '').toLowerCase()
  const tags = (app.tags || []).map((t) => t.toLowerCase())

  let score = -1
  const nameIdx = name.indexOf(query)
  if (nameIdx === 0) score = 100
  else if (nameIdx > 0) score = 80
  else if (tags.some((t) => t === query)) score = 70
  else if (tags.some((t) => t.includes(query))) score = 60
  else if (isSubsequence(query, name) > 0) score = 50
  else if (desc.includes(query)) score = 30
  else if (tags.some((t) => isSubsequence(query, t) > 0)) score = 20
  else if (isSubsequence(query, desc) > 0) score = 10

  if (score < 0) return -1
  // 收藏加成（M02-9：搜索优先）；名称短者优先（更精确的命中）
  if (app.favorite) score += 5
  return score - name.length * 0.01
}

/** 过滤并排序：得分降序；分数相同收藏在前、名称次之。 */
export function searchApps(apps: PortalApp[], query: string): PortalApp[] {
  if (!query.trim()) return []
  return apps
    .map((app) => ({ app, score: matchScore(app, query) }))
    .filter((x) => x.score >= 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        Number(b.app.favorite) - Number(a.app.favorite) ||
        a.app.name.localeCompare(b.app.name, 'zh-CN'),
    )
    .map((x) => x.app)
}
