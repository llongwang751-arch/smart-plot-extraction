<template>
  <el-container class="shell">
    <el-header class="shell-head">
      <div class="brand">
        <span class="logo">◈</span>
        <div>
          <div class="name">智能地块提取平台</div>
          <div class="slogan">自然语言描述需求 · 框选范围 · 自动提取统计</div>
        </div>
      </div>
      <div class="head-right">
        <el-tag v-if="health" size="small" :type="engineType" effect="dark">
          空间引擎：{{ health.gis?.mode === 'postgis' ? 'PostGIS' : '本地降级' }}
        </el-tag>
        <el-tag v-if="health" size="small" :type="health.llm?.configured ? 'success' : 'warning'" effect="plain">
          模型：{{ health.llm?.configured ? health.llm.model : '未配置' }}
        </el-tag>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-avatar :size="26">{{ avatar }}</el-avatar>
            <span class="uname">{{ displayName() }}</span>
            <el-tag size="small" :type="isAdmin() ? 'danger' : 'info'" effect="plain">
              {{ isAdmin() ? '管理员' : '普通用户' }}
            </el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人资料</el-dropdown-item>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-container class="shell-body">
      <el-aside width="186px" class="shell-aside">
        <el-menu :default-active="route.path" router :collapse="false" class="menu">
          <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
            <span class="mi">{{ item.icon }}</span>
            <span>{{ item.name }}</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-main class="shell-main">
        <router-view v-slot="{ Component }">
          <component :is="Component" :key="route.path" />
        </router-view>
      </el-main>
    </el-container>

    <el-dialog v-model="profileVisible" title="个人资料" width="420px">
      <el-form :model="profile" label-width="70px">
        <el-form-item label="账号"><el-input :model-value="state.user?.username" disabled /></el-form-item>
        <el-form-item label="昵称"><el-input v-model="profile.nickname" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="profile.email" /></el-form-item>
        <el-form-item label="手机"><el-input v-model="profile.phone" /></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" @click="saveProfile">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="pwdVisible" title="修改密码" width="400px">
      <el-form :model="pwd" label-width="80px">
        <el-form-item label="原密码"><el-input v-model="pwd.old_password" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="pwd.new_password" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" @click="savePassword">确认修改</el-button></template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MENU } from '@/router'
import { api } from '@/api'
import { clearAuth, displayName, isAdmin, setUser, state } from '@/store'

const route = useRoute()
const router = useRouter()
const health = ref(null)
const profileVisible = ref(false)
const pwdVisible = ref(false)
const profile = reactive({ nickname: '', email: '', phone: '' })
const pwd = reactive({ old_password: '', new_password: '' })

const menus = computed(() => MENU.filter((m) => !m.admin || isAdmin()))
const avatar = computed(() => (displayName() || '?').slice(0, 1).toUpperCase())
const engineType = computed(() => (health.value?.gis?.mode === 'postgis' ? 'success' : 'warning'))

onMounted(async () => {
  api.me().then(setUser).catch(() => {})
  try {
    health.value = await api.health()
  } catch (e) {
    health.value = null
  }
  if (state.user) Object.assign(profile, { nickname: state.user.nickname, email: state.user.email, phone: state.user.phone })
})

function onCommand(command) {
  if (command === 'profile') {
    Object.assign(profile, { nickname: state.user?.nickname, email: state.user?.email, phone: state.user?.phone })
    profileVisible.value = true
  } else if (command === 'password') {
    Object.assign(pwd, { old_password: '', new_password: '' })
    pwdVisible.value = true
  } else {
    ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
      .then(() => {
        clearAuth()
        router.replace('/login')
      })
      .catch(() => {})
  }
}

async function saveProfile() {
  const user = await api.profile({ ...profile })
  setUser(user)
  profileVisible.value = false
  ElMessage.success('资料已更新')
}

async function savePassword() {
  if (pwd.new_password.length < 6) return ElMessage.warning('新密码至少 6 位')
  await api.password({ ...pwd })
  pwdVisible.value = false
  ElMessage.success('密码已更新，请重新登录')
  clearAuth()
  router.replace('/login')
}
</script>

<style scoped>
.shell {
  height: 100%;
}

.shell-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(90deg, #1f3a63, #2c5282);
  color: #fff;
  height: 56px;
  padding: 0 18px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo {
  font-size: 24px;
  line-height: 1;
}

.name {
  font-size: 17px;
  font-weight: 600;
}

.slogan {
  font-size: 11px;
  opacity: 0.7;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  color: #fff;
}

.uname {
  font-size: 13px;
}

.shell-body {
  height: calc(100% - 56px);
}

.shell-aside {
  background: #fff;
  border-right: 1px solid #e6e8eb;
}

.menu {
  border-right: none;
}

.mi {
  margin-right: 8px;
}

.shell-main {
  padding: 0;
  overflow: auto;
  background: #f2f4f7;
}
</style>
