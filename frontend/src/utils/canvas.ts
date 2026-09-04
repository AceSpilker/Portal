/**
 * Flow 画布（M06-3；dev-plan P19.1）：图/表单互转与节点元数据。
 *
 * 与后端 flow_svc.linear_to_graph / graph_to_linear 同构：
 * - 线性 → 图：trigger 起头串连，条件节点出边标 true；
 * - 图 → 线性：主路径投影（条件取 true 分支，fan-out 取首边）。
 */

export interface CanvasNode {
  id: string
  type: string
  name: string
  config?: Record<string, unknown>
  expression?: string
  position?: { x: number; y: number }
}

export interface CanvasEdge {
  source: string
  target: string
  source_handle?: string
}

export interface FlowGraph {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
}

export interface FlowActionLite {
  type: string
  name?: string
  expression?: string
  config?: Record<string, unknown>
}

export const NODE_META: Record<string, { label: string; color: string }> = {
  trigger: { label: '开始', color: '#64748b' },
  condition: { label: '条件', color: '#d97706' },
  http: { label: 'HTTP', color: '#4f6ef7' },
  notify: { label: '通知', color: '#059669' },
  ssh: { label: 'SSH', color: '#7c3aed' },
  docker: { label: 'Docker', color: '#0891b2' },
  ai: { label: 'AI', color: '#db2777' },
  delay: { label: '延时', color: '#ca8a04' },
  variable: { label: '变量', color: '#2563eb' },
}

export function nodeLabel(type: string): string {
  return NODE_META[type]?.label ?? type
}

export function nodeColor(type: string): string {
  return NODE_META[type]?.color ?? '#64748b'
}

/** 表单线性动作 → 画布图（与后端同构） */
export function linearToGraph(actions: FlowActionLite[]): FlowGraph {
  const nodes: CanvasNode[] = [{ id: 'start', type: 'trigger', name: '开始', config: {}, position: { x: 0, y: 0 } }]
  const edges: CanvasEdge[] = []
  let prev = 'start'
  let prevIsCondition = false
  actions.forEach((step, i) => {
    const id = `n${i + 1}`
    const node: CanvasNode = {
      id,
      type: step.type,
      name: step.name ?? nodeLabel(step.type),
      position: { x: 40 + (i % 4) * 190, y: 40 + Math.floor(i / 4) * 110 },
    }
    if (step.type === 'condition' && step.expression) node.expression = step.expression
    if (step.config) node.config = { ...step.config }
    nodes.push(node)
    const edge: CanvasEdge = { source: prev, target: id }
    if (prevIsCondition) edge.source_handle = 'true'
    edges.push(edge)
    prev = id
    prevIsCondition = step.type === 'condition'
  })
  return { nodes, edges }
}

/** 画布图 → 表单线性投影（主路径，条件取 true 分支，fan-out 取首边） */
export function graphToLinear(graph: FlowGraph): FlowActionLite[] {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const out: FlowActionLite[] = []
  let cur: string | undefined = graph.nodes.find((n) => n.type === 'trigger')?.id
  if (!cur) {
    const targets = new Set(graph.edges.map((e) => e.target))
    cur = graph.nodes.find((n) => !targets.has(n.id))?.id
  }
  const seen = new Set<string>()
  while (cur && !seen.has(cur)) {
    seen.add(cur)
    const node = byId.get(cur)
    if (!node) break
    if (node.type !== 'trigger') {
      const step: FlowActionLite = { type: node.type, name: node.name }
      if (node.expression) step.expression = node.expression
      if (node.config) step.config = { ...node.config }
      out.push(step)
    }
    const outs = graph.edges.filter((e) => e.source === cur)
    if (!outs.length) break
    if (node.type === 'condition') {
      const next = outs.find((e) => e.source_handle === 'true') ?? outs[0]
      cur = next.target
    } else {
      cur = outs[0].target
    }
  }
  return out
}

let seq = Date.now() % 100000
export function nextNodeId(type: string): string {
  seq += 1
  return `n_${type}_${seq}`
}
