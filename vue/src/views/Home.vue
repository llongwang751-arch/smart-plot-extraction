<template>
  <div class="page" v-loading="loading">
    <div class="page-title">
      <div>
        <h2>系统首页</h2>
        <div class="sub">你好，{{ displayName() }}（{{ isAdmin() ? '管理员' : '普通用户' }}）· 当前时间 {{ now }}</div>
      </div>
      <el-button type="primary" @click="$router.push('/extract')">开始一次地块提取 →</el-button>
    </div>

    <el-alert v-if="data?.engine?.degraded" type="warning" :closable="false" class="mb">
      空间引擎未连接到 PostgreSQL/PostGIS（{{ data.engine.error || '未配置' }}），已自动降级到本地引擎：
      空间计算与向量检索改由 Shapely + 本地向量库完成，功能与接口完全一致；在「系统配置 → 空间数据库」填好 DSN 并保存即可热切回 PostGIS。
    </el-alert>
    <el-alert v-else-if="data && !data.llm?.configured" type="info" :closable="false" class="mb">
      尚未配置大模型：需求理解与结论归纳会走规则降级，地块数量、面积等数字始终由空间计算得出，不受影响。
    </el-alert>

    <el-row :gutter="12">
      <el-col :span="6"><div class="kpi"><div class="k">地块总数</div><div class="v">{{ num(data?.plots?.count, 0) }}<small> 块</small></div></div></el-col>
      <el-col :span="6"><div class="kpi"><div class="k">地块总面积</div><div class="v">{{ num(data?.plots?.total_area_mu) }}<small> 亩</small></div></div></el-col>
      <el-col :span="6"><div class="kpi"><div class="k">提取记录</div><div class="v">{{ num(data?.records?.total, 0) }}<small> 条</small></div></div></el-col>
      <el-col :span="6"><div class="kpi"><div class="k">知识切片</div><div class="v">{{ num(data?.knowledge?.chunks, 0) }}<small> 片 / {{ num(data?.knowledge?.docs, 0) }} 文档</small></div></div></el-col>
    </el-row>

    <el-row :gutter="12" class="mt">
      <el-col :span="14">
        <div class="card">
          <div class="card-head">
            地类构成
            <span class="muted">引擎：{{ data?.engine?.mode === 'postgis' ? 'PostGIS + pgvector' : '本地降级引擎' }}</span>
          </div>
          <StatCards :statistics="overview" />
        </div>
      </el-col>
      <el-col :span="10">
        <div class="card">
          <div class="card-head">运行态</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="大模型">
              <el-tag size="small" :type="data?.llm?.configured ? 'success' : 'warning'">
                {{ data?.llm?.configured ? data.llm.model : '未配置' }}
              </el-tag>
              <span class="muted"> · Agent 最多 {{ data?.llm?.max_steps || '-' }} 步推理</span>
            </el-descriptions-item>
            <el-descriptions-item label="向量检索">
              {{ data?.knowledge?.backend || '-' }}（{{ data?.knowledge?.ok ? '正常' : data?.knowledge?.message || '不可用' }}）
            </el-descriptions-item>
            <el-descriptions-item label="天地图 / 星图">
              {{ data?.maps?.tianditu ? '已配置' : '未配置' }} / {{ data?.maps?.geovis ? '已配置' : '未配置' }}
            </el-descriptions-item>
            <el-descriptions-item label="业务库">MySQL 或 SQLite（Tortoise ORM）</el-descriptions-item>
            <el-descriptions-item label="空间库">PostgreSQL + PostGIS + pgvector（连不上自动降级）</el-descriptions-item>
          </el-descriptions>
          <div class="steps">
            <div class="st"><b>①</b> 系统配置：填大模型 / 数据库 / 底图并做连通性测试</div>
            <div class="st"><b>②</b> 知识库：上传地类认定标准、面积口径等文档</div>
            <div class="st"><b>③</b> 地图提取：框范围 + 自然语言需求 → 看结论</div>
            <div class="st"><b>④</b> 智能问答：让 Agent 查库、检索知识，结果直接上图</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="card mt">
      <div class="card-head">
        最近的提取记录
        <el-button link type="primary" @click="$router.push('/records')">查看全部</el-button>
      </div>
      <el-table :data="data?.records?.recent || []" size="small" empty-text="还没有提取记录，去「地图提取」跑一次">
        <el-table-column prop="title" label="需求 / 标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="mode" label="模式" width="90">
          <template #default="{ row }">{{ row.mode === 'smart' ? '智能' : '纯计算' }}</template>
        </el-table-column>
        <el-table-column prop="count" label="地块数" width="90" />
        <el-table-column label="面积(亩)" width="120">
          <template #default="{ row }">{{ num(row.total_area_mu) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column prop="created_at" label="时间" width="170" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import StatCards from '@/components/StatCards.vue'
import { displayName, isAdmin } from '@/store'
import { num } from '@/utils/geo'

const data = ref(null)
const loading = ref(false)
const now = new Date().toLocaleString('zh-CN', { hour12: false })

const overview = computed(() => ({
  count: 0,
  engine: data.value?.engine?.mode,
  origin: 'vector',
  ...(data.value?.plots || {})
}))

onMounted(async () => {
  loading.value = true
  try {
    data.value = await api.dashboard()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.mb {
  margin-bottom: 12px;
}

.mt {
  margin-top: 12px;
}

.kpi {
  background: #fff;
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.kpi .k {
  font-size: 12px;
  color: #8a919f;
}

.kpi .v {
  font-size: 24px;
  font-weight: 600;
  margin-top: 4px;
}

.kpi .v small {
  font-size: 12px;
  font-weight: 400;
  color: #8a919f;
}

.steps {
  margin-top: 12px;
  font-size: 12px;
  color: #6b7280;
  line-height: 2;
}

.steps b {
  color: #2c5282;
}
</style>
