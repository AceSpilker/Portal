<script setup lang="ts">
import { ref, watch } from 'vue'
import { joinProtocol, splitProtocol } from '../utils/protocolUrl'

// 协议下拉 + 地址输入的组合控件（066 用户反馈：协议前缀手打易错，改为直接选择）
defineOptions({ name: 'ProtocolUrlInput', inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    /** 完整地址（含协议前缀），与表单字段直接双向绑定；接受 unknown 以兼容弱类型字段 */
    modelValue?: unknown
    /** 可选协议列表（含 // 的完整前缀） */
    protocols?: string[]
    placeholder?: string
  }>(),
  {
    protocols: () => ['https://', 'http://'],
    placeholder: '',
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const proto = ref(props.protocols[0])
const rest = ref('')

// 外部值（回显已有数据 / 粘贴完整地址）→ 拆分回填
watch(
  () => props.modelValue,
  (v) => {
    const { proto: p, rest: r } = splitProtocol(v)
    if (p) proto.value = p
    if (r !== rest.value) rest.value = r
  },
  { immediate: true },
)

function onRestInput(v: string) {
  // 输入过程中手动带了协议前缀（如粘贴完整地址）：吞掉前缀并切换协议
  const { proto: p, rest: r } = splitProtocol(v)
  if (p) {
    proto.value = p
    rest.value = r
  } else {
    rest.value = v
  }
  emit('update:modelValue', joinProtocol(proto.value, rest.value))
}

function onProtoChange() {
  emit('update:modelValue', joinProtocol(proto.value, rest.value))
}
</script>

<template>
  <el-input
    :model-value="rest"
    :placeholder="placeholder"
    v-bind="$attrs"
    @update:model-value="onRestInput"
  >
    <template #prepend>
      <el-select v-model="proto" class="proto-select" aria-label="Protocol" @change="onProtoChange">
        <el-option v-for="p in protocols" :key="p" :label="p" :value="p" />
      </el-select>
    </template>
  </el-input>
</template>

<style scoped>
.proto-select {
  width: 112px;
}
</style>
