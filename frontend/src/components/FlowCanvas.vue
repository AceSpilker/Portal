<script setup lang="ts">
/**
 * Flow 画布编辑器（M06-3；dev-plan P19.1/P19.2）。
 *
 * - Vue Flow 拖拽节点/连线；条件节点 true/false 双出口；fan-out 多出边即分支并行；
 * - 节点点击 → 侧栏编辑参数（实时写透到 working graph）；保存序列化 {nodes,edges}；
 * - 图校验（无环/类型/数量）由后端保存时兜底。
 */
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Delete as IconDelete } from '@element-plus/icons-vue'
import { VueFlow, useVueFlow, type Connection } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import { nodeColor, nodeLabel, nextNodeId, type FlowGraph } from '../utils/canvas'

const { t } = useI18n()

const props = defineProps<{ modelValue: FlowGraph | null }>()
const emit = defineEmits<{ save: [graph: FlowGraph] }>()

const visible = defineModel('visible', { type: Boolean, required: true })

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- vue-flow 泛型过深，内部节点直接用宽松结构
const vfNodes = ref<any[]>([])
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const vfEdges = ref<any[]>([])
const selectedId = ref<string | null>(null)
const { addNodes, addEdges, removeNodes, findNode, onConnect, onNodeClick, onPaneClick } = useVueFlow()

// 工作图副本：所有参数编辑实时写透；positions 在保存时从 VueFlow 节点回读
const working = ref<FlowGraph>({ nodes: [], edges: [] })

const form = reactive({
  id: '',
  type: 'http',
  name: '',
  expression: '',
  config: {} as Record<string, unknown>,
})

const NODE_TYPES = ['condition', 'http', 'notify', 'ssh', 'docker', 'ai', 'delay', 'variable']

const DEFAULT_CONFIG: Record<string, Record<string, unknown>> = {
  condition: {},
  http: { method: 'GET', url: '' },
  notify: { title: '', body: '', level: 'info' },
  ssh: { host: '', port: 22, username: 'root', password: '', command: '' },
  docker: { container: '', op: 'restart' },
  ai: { prompt: '', system: '你是 NAS 助手，简洁回答。' },
  delay: { seconds: 60 },
  variable: { name: '', value: '' },
  trigger: {},
}

function syncFromModel() {
  const g = props.modelValue ?? { nodes: [], edges: [] }
  working.value = JSON.parse(JSON.stringify(g))
  vfNodes.value = g.nodes.map((n, i) => ({
    id: n.id,
    type: 'fnode',
    position: n.position ?? { x: 40 + (i % 4) * 190, y: 40 + Math.floor(i / 4) * 110 },
    data: { ftype: n.type, label: n.name },
  }))
  vfEdges.value = g.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_handle ?? null,
    animated: e.source_handle === 'true',
    style: e.source_handle === 'false' ? { stroke: '#e0566a' } : undefined,
  }))
}

watch(
  visible,
  (v) => {
    if (v) syncFromModel()
  },
  { immediate: true },
)

// 参数编辑实时写透 working（按选中节点 id）
watch(
  () => `${form.name}\u0000${form.expression}\u0000${JSON.stringify(form.config)}`,
  () => {
    const n = working.value.nodes.find((x) => x.id === selectedId.value)
    if (!n) return
    n.name = form.name
    if (n.type === 'condition') n.expression = form.expression
    if (n.type !== 'trigger') n.config = { ...form.config }
    const vn = vfNodes.value.find((x) => x.id === selectedId.value)
    if (vn) vn.data = { ...vn.data, label: form.name }
  },
)

function loadFormOf(id: string) {
  const n = working.value.nodes.find((x) => x.id === id)
  if (!n) return
  selectedId.value = id
  form.id = id
  form.type = n.type
  form.name = n.name
  form.expression = n.expression ?? ''
  form.config = { ...(DEFAULT_CONFIG[n.type] ?? {}), ...(n.config ?? {}) }
}

function addNode(type: string) {
  const id = nextNodeId(type)
  working.value.nodes.push({
    id,
    type,
    name: nodeLabel(type),
    config: { ...(DEFAULT_CONFIG[type] ?? {}) },
    position: { x: 240 + Math.random() * 140, y: 50 + Math.random() * 170 },
  })
  addNodes([
    {
      id,
      type: 'fnode',
      position: { x: 240 + Math.random() * 140, y: 50 + Math.random() * 170 },
      data: { ftype: type, label: nodeLabel(type) },
    },
  ])
  loadFormOf(id)
}

onNodeClick(({ node }) => {
  loadFormOf(node.id)
})

onPaneClick(() => {
  selectedId.value = null
})

onConnect((conn: Connection) => {
  const src = working.value.nodes.find((n) => n.id === conn.source)
  working.value.edges.push({
    source: conn.source,
    target: conn.target,
    ...(conn.sourceHandle ? { source_handle: conn.sourceHandle } : {}),
  })
  addEdges([
    {
      ...conn,
      id: `e_${conn.source}_${conn.target}_${Date.now()}`,
      animated: conn.sourceHandle === 'true',
      style: conn.sourceHandle === 'false' ? { stroke: '#e0566a' } : undefined,
    },
  ])
  void src
})

function removeSelected() {
  if (!selectedId.value) return
  const vn = findNode(selectedId.value)
  if (vn?.data.ftype === 'trigger') {
    ElMessage.warning(t('canvas.triggerUndeletable'))
    return
  }
  removeNodes([selectedId.value])
  working.value.nodes = working.value.nodes.filter((x) => x.id !== selectedId.value)
  working.value.edges = working.value.edges.filter(
    (e) => e.source !== selectedId.value && e.target !== selectedId.value,
  )
  selectedId.value = null
}

function saveCanvas() {
  // 从 VueFlow 节点回读位置；配置取 working
  const pos = new Map(vfNodes.value.map((n) => [n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) }]))
  const nodes = working.value.nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position ?? { x: 0, y: 0 } }))
  if (nodes.length < 2) {
    ElMessage.warning(t('canvas.emptyWarn'))
    return
  }
  const graph: FlowGraph = { nodes, edges: working.value.edges }
  emit('save', graph)
}
</script>

<template>
  <div class="canvas-wrap">
    <div class="palette">
      <el-tooltip v-for="nt in NODE_TYPES" :key="nt" :content="t(`canvas.add.${nt}`)" placement="top">
        <button
          type="button"
          class="pal-btn"
          :style="{ borderColor: nodeColor(nt) }"
          @click="addNode(nt)"
        >
          <span class="pal-dot" :style="{ background: nodeColor(nt) }" />
          {{ nodeLabel(nt) }}
        </button>
      </el-tooltip>
      <span class="spacer" />
      <el-button size="small" type="primary" class="btn-gradient" data-test="canvas-save" @click="saveCanvas">
        {{ t('canvas.save') }}
      </el-button>
    </div>

    <div class="flow-host">
      <VueFlow v-model:nodes="vfNodes" v-model:edges="vfEdges" :default-edge-options="{ type: 'smoothstep' }" fit-view-on-init>
        <Background />
        <Controls />
        <MiniMap pannable zoomable />

        <template #node-fnode="{ data }">
          <div class="fnode" :style="{ borderColor: nodeColor(data.ftype) }">
            <span class="fnode-dot" :style="{ background: nodeColor(data.ftype) }" />
            <span class="fnode-label">{{ data.label }}</span>
            <template v-if="data.ftype === 'condition'">
              <span class="handle-line">
                <span class="tag-true">T</span>
                <span class="tag-false">F</span>
              </span>
            </template>
          </div>
        </template>
      </VueFlow>

      <!-- 节点参数侧栏 -->
      <aside v-if="selectedId" class="cfg-panel">
        <header class="cfg-head">
          <b>{{ nodeLabel(form.type) }}</b>
          <el-button link type="danger" size="small" :icon="IconDelete" @click="removeSelected" />
        </header>
        <el-form label-position="top" size="small">
          <el-form-item :label="t('canvas.nodeName')">
            <el-input v-model="form.name" maxlength="40" />
          </el-form-item>

          <template v-if="form.type === 'condition'">
            <el-form-item :label="t('flow.exprPh')">
              <el-input v-model="form.expression" placeholder="prev.status_code == 200" />
            </el-form-item>
          </template>
          <template v-else-if="form.type === 'http'">
            <el-form-item :label="'HTTP'">
              <div class="row">
                <el-select v-model="form.config.method" style="width: 92px">
                  <el-option v-for="m in ['GET', 'POST', 'PUT', 'DELETE']" :key="m" :label="m" :value="m" />
                </el-select>
                <el-input v-model="form.config.url" :placeholder="t('flow.urlPh')" />
              </div>
            </el-form-item>
          </template>
          <template v-else-if="form.type === 'notify'">
            <el-form-item :label="t('flow.notifyTitlePh')">
              <el-input v-model="form.config.title" />
            </el-form-item>
            <el-form-item :label="t('flow.notifyBodyPh')">
              <el-input v-model="form.config.body" />
            </el-form-item>
          </template>
          <template v-else-if="form.type === 'ssh'">
            <el-form-item :label="t('canvas.sshHost')"><el-input v-model="form.config.host" /></el-form-item>
            <div class="row">
              <el-form-item :label="t('redis.port')"><el-input-number v-model="form.config.port" :min="1" :max="65535" /></el-form-item>
              <el-form-item :label="t('settings.effUser')"><el-input v-model="form.config.username" /></el-form-item>
            </div>
            <el-form-item :label="t('settings.effPass')">
              <el-input v-model="form.config.password" type="password" show-password />
            </el-form-item>
            <el-form-item :label="t('canvas.sshCmd')"><el-input v-model="form.config.command" placeholder="systemctl restart xxx" /></el-form-item>
          </template>
          <template v-else-if="form.type === 'docker'">
            <el-form-item :label="t('canvas.dockerContainer')"><el-input v-model="form.config.container" /></el-form-item>
            <el-form-item :label="t('flow.op')">
              <el-radio-group v-model="form.config.op" size="small">
                <el-radio-button value="start">start</el-radio-button>
                <el-radio-button value="stop">stop</el-radio-button>
                <el-radio-button value="restart">restart</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </template>
          <template v-else-if="form.type === 'ai'">
            <el-form-item :label="t('canvas.aiPrompt')">
              <el-input v-model="form.config.prompt" type="textarea" :rows="3" />
            </el-form-item>
          </template>
          <template v-else-if="form.type === 'delay'">
            <el-form-item :label="t('canvas.delaySeconds')">
              <el-input-number v-model="form.config.seconds" :min="1" :max="300" />
            </el-form-item>
          </template>
          <template v-else-if="form.type === 'variable'">
            <el-form-item :label="t('canvas.varName')"><el-input v-model="form.config.name" /></el-form-item>
            <el-form-item :label="t('canvas.varValue')"><el-input v-model="form.config.value" /></el-form-item>
          </template>
        </el-form>
        <p class="cfg-tip">{{ t('canvas.connectTip') }}</p>
      </aside>

      <div v-else class="canvas-hint">{{ t('canvas.hint') }}</div>
    </div>
  </div>
</template>

<style scoped>
.canvas-wrap {
  display: flex;
  flex-direction: column;
  height: 62vh;
  gap: 8px;
}
.palette {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.pal-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border: 1px solid var(--p-card-border);
  border-radius: 999px;
  background: var(--p-card);
  cursor: pointer;
  font-size: 12.5px;
}
.pal-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.spacer {
  flex: 1;
}
.flow-host {
  position: relative;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  overflow: hidden;
}
.fnode {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 110px;
  padding: 8px 12px;
  background: var(--p-card);
  border: 1.5px solid var(--p-card-border);
  border-radius: 10px;
  font-size: 12.5px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.12);
}
.fnode-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.fnode-label {
  font-weight: 600;
}
.handle-line {
  display: flex;
  gap: 2px;
  margin-left: 6px;
}
.tag-true,
.tag-false {
  font-size: 9px;
  padding: 0 3px;
  border-radius: 4px;
  color: #fff;
}
.tag-true {
  background: #059669;
}
.tag-false {
  background: #e0566a;
}
.cfg-panel {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 260px;
  max-height: calc(100% - 20px);
  overflow-y: auto;
  background: var(--p-card);
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  padding: 10px 12px;
  z-index: 5;
}
.cfg-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.cfg-tip,
.canvas-hint {
  font-size: 12px;
  color: var(--p-muted);
}
.canvas-hint {
  position: absolute;
  bottom: 12px;
  left: 12px;
  background: var(--p-card);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--p-card-border);
}
.row {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
