<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>用户管理</h2>
        <div class="sub">管理员 / 普通用户双角色：管理员独享「系统配置」「用户管理」，后端接口强制校验身份，不只藏菜单</div>
      </div>
      <div class="head-actions">
        <el-input v-model="keyword" size="small" placeholder="按用户名搜索" clearable class="kw" @keyup.enter="load" @clear="load" />
        <el-button size="small" @click="load">刷新</el-button>
        <el-button size="small" type="primary" @click="openCreate">+ 新增用户</el-button>
      </div>
    </div>

    <div class="card">
      <el-table :data="items" size="small" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" width="150" />
        <el-table-column prop="nickname" label="昵称" width="150" />
        <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column label="角色" width="150">
          <template #default="{ row }">
            <el-switch
              :model-value="row.role === 'admin'"
              active-text="管理员"
              inactive-text="普通用户"
              inline-prompt
              :disabled="row.id === myId"
              @change="(v) => patch(row, { role: v ? 'admin' : 'user' })"
            />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-switch
              :model-value="!!row.enabled"
              active-text="启用"
              inactive-text="停用"
              inline-prompt
              :disabled="row.id === myId"
              @change="(v) => patch(row, { enabled: v })"
            />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" width="160" />
        <el-table-column prop="last_login_at" label="最近登录" width="160" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" :disabled="row.id === myId" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="pg" layout="total, prev, pager, next" :total="total" v-model:current-page="page" :page-size="20" @current-change="load" />
    </div>

    <el-dialog v-model="dialogVisible" :title="form.id ? `编辑用户 #${form.id}` : '新增用户'" width="460px">
      <el-form :model="form" label-width="82px" size="small">
        <el-form-item label="用户名"><el-input v-model="form.username" :disabled="!!form.id" /></el-form-item>
        <el-form-item label="昵称"><el-input v-model="form.nickname" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item :label="form.id ? '重置密码' : '初始密码'">
          <el-input v-model="form.password" type="password" show-password :placeholder="form.id ? '留空表示不修改' : '至少 6 位'" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role"><el-option label="普通用户" value="user" /><el-option label="管理员" value="admin" /></el-select>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { state } from '@/store'

const items = ref([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const form = reactive({ id: 0, username: '', nickname: '', email: '', password: '', role: 'user', enabled: true })
const myId = state.user?.id

async function load() {
  loading.value = true
  try {
    const res = await api.users({ keyword: keyword.value, page: page.value, size: 20 })
    items.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { id: 0, username: '', nickname: '', email: '', password: '', role: 'user', enabled: true })
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, { id: row.id, username: row.username, nickname: row.nickname, email: row.email, password: '', role: row.role, enabled: !!row.enabled })
  dialogVisible.value = true
}

async function submit() {
  saving.value = true
  try {
    if (form.id) await api.updateUser(form.id, { ...form, password: form.password || undefined })
    else await api.createUser({ ...form })
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function patch(row, payload) {
  await api.updateUser(row.id, payload)
  ElMessage.success('已更新')
  await load()
}

async function remove(row) {
  const ok = await ElMessageBox.confirm(`删除用户「${row.username}」会一并清理其会话记录，确定？`, '提示', { type: 'warning' }).catch(() => false)
  if (!ok) return
  await api.deleteUser(row.id)
  ElMessage.success('用户已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.kw {
  width: 180px;
}

.pg {
  margin-top: 10px;
  justify-content: flex-end;
}
</style>
