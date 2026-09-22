<template>
  <div class="wrap">
    <div class="hero">
      <h1>智能地块提取平台</h1>
      <p>用自然语言描述需求，在地图上框个范围，系统自动完成地块提取、统计与结论生成。</p>
      <ul>
        <li>LangGraph 五节点工作流：需求理解 → 范围定位 → 知识召回 → 空间提取 → 结论归纳</li>
        <li>语义归大模型，几何与数字归 PostGIS，结果可复现、可追溯</li>
        <li>RAG 知识库 + ReAct 智能问答，检索来源与工具轨迹全可视</li>
      </ul>
    </div>

    <div class="panel">
      <el-tabs v-model="tab" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form :model="form" label-position="top" @submit.prevent>
            <el-form-item label="用户名">
              <el-input v-model="form.username" placeholder="请输入用户名" @keyup.enter="submit" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" @keyup.enter="submit" />
            </el-form-item>
            <el-button type="primary" class="go" :loading="busy" @click="submit">登 录</el-button>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form :model="form" label-position="top" @submit.prevent>
            <el-form-item label="用户名">
              <el-input v-model="form.username" placeholder="3-32 位，登录后不可修改" />
            </el-form-item>
            <el-form-item label="昵称">
              <el-input v-model="form.nickname" placeholder="选填" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="form.email" placeholder="选填" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
            <el-button type="primary" class="go" :loading="busy" @click="submit">注册并登录</el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <div class="tip">
        登录不区分角色，由后端按账号判定；自助注册的一律是普通用户，管理员由「用户管理」指定。<br />
        内置管理员：<span class="mono">admin / admin123</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import { setAuth } from '@/store'

const route = useRoute()
const router = useRouter()
const tab = ref('login')
const busy = ref(false)
const form = reactive({ username: '', password: '', nickname: '', email: '' })

async function submit() {
  if (!form.username.trim() || !form.password) return ElMessage.warning('请填写用户名与密码')
  if (tab.value === 'register' && form.password.length < 6) return ElMessage.warning('密码至少 6 位')
  busy.value = true
  try {
    const res = tab.value === 'login'
      ? await api.login({ username: form.username, password: form.password })
      : await api.register({ username: form.username, password: form.password, nickname: form.nickname, email: form.email })
    setAuth(res.token, res.user)
    ElMessage.success(`欢迎，${res.user.nickname || res.user.username}`)
    router.replace(route.query.next || '/home')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 60px;
  background: linear-gradient(135deg, #16283f, #24507f 60%, #2c6fa8);
  flex-wrap: wrap;
  padding: 24px;
}

.hero {
  color: #eaf1fb;
  max-width: 520px;
}

.hero h1 {
  font-size: 32px;
  margin: 0 0 12px;
  letter-spacing: 1px;
}

.hero p {
  font-size: 15px;
  opacity: 0.9;
  line-height: 1.8;
}

.hero ul {
  padding-left: 18px;
  font-size: 13px;
  opacity: 0.8;
  line-height: 2;
}

.panel {
  width: 360px;
  background: #fff;
  border-radius: 10px;
  padding: 22px 26px 18px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.24);
}

.go {
  width: 100%;
  margin-top: 6px;
}

.tip {
  margin-top: 16px;
  font-size: 12px;
  color: #8a919f;
  line-height: 1.8;
}

.mono {
  font-family: Consolas, monospace;
  color: #4b6cb7;
}
</style>
