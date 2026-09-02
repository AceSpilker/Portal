/** P4 单测关卡：命令面板搜索过滤与排序（M02-6/9）。 */
import { describe, expect, it } from 'vitest'
import { matchScore, searchApps } from '../utils/search'
import type { PortalApp } from '../api/portal'

const app = (over: Partial<PortalApp> & { id: number; name: string }): PortalApp => ({
  description: '',
  icon: null,
  icon_type: 'element',
  category_id: null,
  sort: 0,
  enabled: true,
  health_type: '',
  health_target: null,
  health_interval: 60,
  open_mode: 'newtab',
  visibility: 'all',
  favorite: false,
  tags: [],
  remark: '',
  doc_url: null,
  urls: [],
  ...over,
})

const jellyfin = app({ id: 1, name: 'Jellyfin', description: '媒体服务器', tags: ['媒体'] })
const github = app({ id: 2, name: 'GitHub', description: '代码托管', tags: ['开发'] })
const favorited = app({ id: 3, name: 'Home Assistant', description: '智能家居', favorite: true })

describe('matchScore', () => {
  it('名称前缀 > 名称包含 > 子序列 > 描述包含', () => {
    expect(matchScore(app({ id: 9, name: 'GitLab' }), 'git')).toBeGreaterThan(
      matchScore(app({ id: 8, name: 'MyGitHub' }), 'git'),
    )
    expect(matchScore(github, 'git')).toBeGreaterThan(matchScore(github, 'ithub'))
    expect(matchScore(jellyfin, 'jl')).toBeGreaterThan(0) // 子序列 jl → Jellyfin
    expect(matchScore(jellyfin, '媒体')).toBeGreaterThan(0) // 描述命中
  })

  it('不相关查询不命中', () => {
    expect(matchScore(jellyfin, 'qqq')).toBe(-1)
    expect(matchScore(jellyfin, '')).toBe(-1)
  })
})

describe('searchApps', () => {
  const all = [jellyfin, github, favorited]

  it('收藏在分数接近时优先（M02-9）', () => {
    const hit = searchApps(all, 'home')
    expect(hit[0]?.id).toBe(favorited.id)
  })

  it('空查询返回空数组；结果按得分降序', () => {
    expect(searchApps(all, '')).toEqual([])
    const hits = searchApps(all, 'a')
    for (let i = 1; i < hits.length; i++) {
      expect(matchScore(hits[i - 1], 'a')).toBeGreaterThanOrEqual(matchScore(hits[i], 'a'))
    }
  })
})
