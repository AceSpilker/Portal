<script setup lang="ts">
/**
 * 用户管理面板（M01-11；dev-plan 7.4）。仅管理员可见（设置页 requiresAdmin）。
 * 列表/新增/编辑（角色/备注）/禁用启用/重置密码/强制下线；全部操作写审计。
 */
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usersApi, type UserItem } from '../api/users'

const { t } = useI18n()
const loading = ref(false)
const keyword = ref('')
const items = ref<UserItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50

// 新增/编辑对话框
const dialog = ref(false)
const editing = ref<UserItem | null>(null) // null = 新增
const form = reactive({ username: '', password: '', role: 'user', remark: '' })

async function load() {
  loading.value = true
  try {
    const data = await usersApi.list(keyword.value, page.value, pageSize)
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.username = ''
  form.password = ''
  form.role = 'user'
  form.remark = ''
  dialog.value = true
}

function openEdit(u: UserItem) {
  editing.value = u
  form.username = u.username
  form.password = ''
  form.role = u.role
  form.remark = u.remark
  dialog.value = true
}

async function save() {
  try {
    if (editing.value) {
      await usersApi.update(editing.value.id, { role: form.role, remark: form.remark })
      ElMessage.success(t('users.saved'))
    } else {
      await usersApi.create({
        username: form.username,
        password: form.password,
        role: form.role,
        remark: form.remark,
      })
      ElMessage.success(t('users.created'))
    }
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function promptError(e: unknown) {
  // 后端拒绝（self-guard / 最后管理员 / 重名等）时给出可见反馈，不再静默
  ElMessage.error((e as Error).message || String(e))
}

async function toggleStatus(u: UserItem) {
  const confirmed = await ElMessageBox.confirm(
    u.is_active ? t('users.confirmDisable', { name: u.username }) : t('users.confirmEnable', { name: u.username }),
    t('common.confirm'),
    { type: 'warning' },
  ).then(() => true, () => false)
  if (!confirmed) return
  try {
    await usersApi.setStatus(u.id, !u.is_active)
    ElMessage.success(t(u.is_active ? 'users.disabled' : 'users.enabled'))
    await load()
  } catch (e) {
    promptError(e)
  }
}

async function resetPassword(u: UserItem) {
  let value: string
  try {
    ;({ value } = await ElMessageBox.prompt(
      t('users.resetPrompt', { name: u.username }),
      t('users.resetTitle'),
      { inputPlaceholder: t('users.resetPh'), inputPattern: /^.{8,}$/, inputErrorMessage: t('users.resetErr') },
    ))
  } catch {
    return
  }
  try {
    await usersApi.resetPassword(u.id, value)
    ElMessage.success(t('users.resetOk'))
  } catch (e) {
    promptError(e)
  }
}

async function kick(u: UserItem) {
  const confirmed = await ElMessageBox.confirm(
    t('users.confirmKick', { name: u.username }),
    t('users.kickTitle'),
    { type: 'warning' },
  ).then(() => true, () => false)
  if (!confirmed) return
  try {
    await usersApi.kick(u.id)
    ElMessage.success(t('users.kicked'))
    await load()
  } catch (e) {
    promptError(e)
  }
}

onMounted(load)
</script>

<template>
  <div class="users-panel">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        :placeholder="t('users.searchPh')"
        clearable
        style="width: 220px"
        @change="load"
        @clear="load"
      />
      <el-button type="primary" class="btn-gradient" @click="openCreate">
        {{ t('users.add') }}
      </el-button>
    </div>

    <el-table :data="items" v-loading="loading">
      <el-table-column prop="username" :label="t('users.username')" min-width="140" />
      <el-table-column :label="t('users.role')" width="110">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
            {{ row.role === 'admin' ? t('users.roleAdmin') : t('users.roleUser') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('users.status')" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? t('users.active') : t('users.inactive') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" :label="t('users.remark')" min-width="160" show-overflow-tooltip />
      <el-table-column :label="t('users.operations')" width="220">
        <template #default="{ row }">
          <el-button link size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
          <el-button link size="small" :type="row.is_active ? 'danger' : 'success'" @click="toggleStatus(row)">
            {{ row.is_active ? t('users.disable') : t('users.enable') }}
          </el-button>
          <el-button link size="small" @click="resetPassword(row)">{{ t('users.resetPwd') }}</el-button>
          <el-button link size="small" type="warning" @click="kick(row)">{{ t('users.kick') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body
      v-model="dialog"
      :title="editing ? t('users.editTitle', { name: editing.username }) : t('users.addTitle')"
      width="420px"
      
    >
      <el-form label-width="90px">
        <el-form-item :label="t('users.username')">
          <el-input v-model="form.username" :disabled="!!editing" />
        </el-form-item>
        <el-form-item v-if="!editing" :label="t('users.password')">
          <el-input v-model="form.password" type="password" show-password :placeholder="t('users.passwordPh')" />
        </el-form-item>
        <el-form-item :label="t('users.role')">
          <el-select v-model="form.role" :disabled="!!editing" style="width: 100%">
            <el-option :label="t('users.roleAdmin')" value="admin" :disabled="!!editing" />
            <el-option :label="t('users.roleUser')" value="user" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('users.remark')">
          <el-input v-model="form.remark" maxlength="256" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.users-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.toolbar {
  display: flex;
  gap: 10px;
  justify-content: space-between;
}
</style>
