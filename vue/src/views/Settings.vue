<template>
  <div class="page" v-loading="loading">
    <div class="page-title">
      <div>
        <h2>系统配置</h2>
        <div class="sub">
          全部参数存在数据库里，页面由 <span class="mono">/api/config/schema</span> 自动渲染：新增配置项只需在后端 schema 加一行，前后端都不用改代码。保存后下一次调用即热生效。
        </div>
      </div>
      <div class="head-actions">
        <el-button size="small" @click="loadStatus">刷新运行态</el-button>
        <el-button size="small" @click="previewVisible = true">预览底图</el-button>
        <el-button size="small" type="primary" :disabled="!dirtyKeys.length" :loading="saving" @click="save">
          保存变更{{ dirtyKeys.length ? ` (${dirtyKeys.length})` : '' }}
        </el-button>
      </div>
    </div>

    <el-row :gutter="10" class="mb">
      <el-col :span="6"><div class="mini"><span>空间引擎</span><b :class="st?.gis?.mode === 'postgis' ? 'ok' : 'warn'">{{ st?.gis?.mode === 'postgis' ? 'PostGIS' : '本地降级' }}</b></div></el-col>
      <el-col :span="6"><div class="mini"><span>向量后端</span><b>{{ st?.vector?.backend || '-' }}</b><i>{{ num(st?.vector?.chunks, 0) }} 片</i></div></el-col>
      <el-col :span="6"><div class="mini"><span>大模型</span><b :class="st?.llm?.configured ? 'ok' : 'warn'">{{ st?.llm?.configured ? st.llm.model : '未配置' }}</b></div></el-col>
      <el-col :span="6"><div class="mini"><span>业务库 / 底图</span><b>{{ st?.sys_db || '-' }}</b><i>天地图 {{ st?.maps?.tianditu ? '✓' : '✗' }} · 星图 {{ st?.maps?.geovis ? '✓' : '✗' }}</i></div></el-col>
    </el-row>

    <el-alert
      v-if="st && st.gis?.mode !== 'postgis'"
      type="warning"
      :closable="false"
      class="mb"
      :title="`PostGIS 未启用：${st.gis?.error || st.postgres_configured ? '连接失败' : '未配置 DSN'}，当前走本地降级引擎`"
      description="在「空间数据库」分组填好 PostGIS DSN 后保存，系统会自动重建连接池并建表（CREATE EXTENSION postgis / vector），无需重启。"
    />

    <div class="card">
      <el-tabs v-model="tab">
        <el-tab-pane v-for="g in groups" :key="g.code" :label="g.name" :name="g.code">
          <div class="gdesc">{{ g.desc }}</div>
          <el-form label-width="184px" label-position="left" size="small">
            <el-form-item v-for="item in g.items" :key="item.key" :label="item.label">
              <el-switch v-if="item.type === 'boolean'" v-model="values[item.key]" />
              <el-input-number
                v-else-if="item.type === 'number'"
                :model-value="toNum(values[item.key])"
                :step="stepOf(item)"
                :precision="precisionOf(item)"
                controls-position="right"
                @update:model-value="(v) => (values[item.key] = v)"
              />
              <el-input
                v-else
                v-model="values[item.key]"
                :type="item.type === 'password' ? 'password' : 'text'"
                :show-password="item.type === 'password'"
                :placeholder="item.placeholder || (item.secret && item.has_value ? '已设置，保持 ****** 表示不修改' : '')"
                class="fin"
              />
              <div class="tip">
                <span class="mono">{{ item.key }}</span>
                <span v-if="item.tip"> · {{ item.tip }}</span>
                <span v-if="item.secret && item.has_value" class="masked"> · 已脱敏</span>
              </div>
            </el-form-item>
          </el-form>
          <div class="gtest">
            <el-button
              v-for="t in testsOf(g.code)"
              :key="t.target"
              size="small"
              :loading="testing === t.target"
              @click="test(t.target)"
            >
              {{ t.label }}
            </el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div v-if="lastTest" class="card mt">
      <div class="card-head">
        测试结果：{{ lastTest.target }}
        <el-button link size="small" @click="lastTest = null">关闭</el-button>
      </div>
      <div v-if="lastTest.target === 'tiles'" class="tiles">
        <div class="sum">
          <el-tag :type="lastTest.result?.ok ? 'success' : 'danger'" size="small">{{ lastTest.result?.summary }}</el-tag>
          <span class="muted">{{ lastTest.result?.degrade_hint }}</span>
        </div>
        <div v-for="(row, i) in lastTest.result?.items || []" :key="i" class="trow">
          <el-tag size="small" :type="row.ok ? 'success' : row.configured ? 'danger' : 'info'">{{ row.ok ? '可访问' : row.configured ? '失败' : '未配置' }}</el-tag>
          <span class="tn">{{ row.name }}</span>
          <span class="muted mono">HTTP {{ row.status }} · {{ row.elapsed_ms }}ms</span>
          <span v-if="row.error?.advice || row.error?.message" class="advice">{{ row.error.advice || row.error.message }}</span>
          <span v-else-if="row.message" class="advice">{{ row.message }}</span>
        </div>
      </div>
      <pre v-else class="mono box">{{ pretty(lastTest.result) }}</pre>
    </div>

    <el-dialog v-model="previewVisible" title="底图预览（瓦片走后端代理，凭据不下发浏览器）" width="900px" top="6vh">
      <div class="preview">
        <MapCanvas v-if="previewVisible" :mini="false" :model-value="null" height="100%" :show-plots-default="false" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import MapCanvas from '@/components/MapCanvas.vue'
import { num } from '@/utils/geo'

const groups = ref([])
const values = reactive({})
const original = reactive({})
const st = ref(null)
const tab = ref('')
const loading = ref(false)
const saving = ref(false)
const testing = ref('')
const lastTest = ref(null)
const previewVisible = ref(false)
const masked = ref('******')

const dirtyKeys = computed(() => Object.keys(values).filter((k) => String(values[k] ?? '') !== String(original[k] ?? '')))

const toNum = (v) => (v === '' || v === null || v === undefined ? 0 : Number(v))
const stepOf = (item) => (item.key === 'llm.temperature' ? 0.1 : 1)
const precisionOf = (item) => (item.key === 'llm.temperature' || item.key === 'extract.simplify' ? 4 : 0)
const pretty = (v) => JSON.stringify(v, null, 2)

const GROUP_TESTS = {
  llm: [{ target: 'llm', label: '测试大模型' }, { target: 'embed', label: '测试嵌入模型' }],
  rag: [{ target: 'embed', label: '测试嵌入模型' }, { target: 'sys_db', label: '测试业务库' }],
  geovis: [{ target: 'tiles', label: '测试瓦片可达性' }],
  tianditu: [{ target: 'tiles', label: '测试瓦片可达性' }],
  gis: [{ target: 'gis', label: '测试 PostGIS' }, { target: 'sys_db', label: '测试业务库' }],
  extract: []
}

const testsOf = (code) => GROUP_TESTS[code] || []

async function loadSchema() {
  loading.value = true
  try {
    const res = await api.configSchema()
    groups.value = res.groups || []
    masked.value = res.masked || '******'
    if (!tab.value && groups.value.length) tab.value = groups.value[0].code
    for (const g of groups.value) {
      for (const item of g.items) {
        const v = item.type === 'boolean' ? Boolean(item.value) : item.value
        values[item.key] = v
        original[item.key] = v
      }
    }
  } finally {
    loading.value = false
  }
}

async function loadStatus() {
  st.value = await api.configStatus()
}

async function save() {
  const payload = {}
  for (const key of dirtyKeys.value) {
    if (values[key] === masked.value) continue
    payload[key] = values[key]
  }
  if (!Object.keys(payload).length) return ElMessage.info('没有需要保存的变更')
  saving.value = true
  try {
    const res = await api.saveConfig(payload)
    ElMessage.success(res.message)
    await loadSchema()
    await loadStatus()
  } finally {
    saving.value = false
  }
}

async function test(target) {
  testing.value = target
  try {
    const res = await api.testConfig(target)
    lastTest.value = { target, result: res.result }
    if (res.result?.ok) ElMessage.success('测试通过')
    else ElMessage.warning(res.result?.message || '测试未通过，详情见下方结果')
  } finally {
    testing.value = ''
  }
}

onMounted(async () => {
  await loadSchema()
  await loadStatus()
})
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
}

.mb {
  margin-bottom: 12px;
}

.mt {
  margin-top: 12px;
}

.mini {
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.mini span {
  font-size: 12px;
  color: #8a919f;
}

.mini b {
  font-size: 15px;
}

.mini b.ok {
  color: #2f9e44;
}

.mini b.warn {
  color: #e0862a;
}

.mini i {
  font-style: normal;
  font-size: 12px;
  color: #8a919f;
}

.gdesc {
  font-size: 12px;
  color: #8a919f;
  margin-bottom: 12px;
}

.fin {
  width: 420px;
}

.tip {
  width: 100%;
  font-size: 11px;
  color: #a8abb2;
  line-height: 1.6;
}

.tip .mono {
  color: #6b7280;
}

.masked {
  color: #e0862a;
}

.gtest {
  display: flex;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px dashed #ebeef5;
}

.tiles .sum {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.trow {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 12px;
  padding: 5px 0;
  border-bottom: 1px dashed #f0f0f0;
  flex-wrap: wrap;
}

.tn {
  width: 168px;
  flex: none;
}

.advice {
  color: #b45309;
}

.box {
  background: #f7f9fc;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.preview {
  height: 460px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
