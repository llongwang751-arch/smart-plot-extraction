<template>
  <div class="extract">
    <div class="topbar">
      <el-radio-group v-model="form.mode" size="small">
        <el-radio-button value="smart">智能提取（LangGraph）</el-radio-button>
        <el-radio-button value="space">纯计算（不经大模型）</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="form.query"
        class="query"
        size="small"
        clearable
        :disabled="form.mode === 'space'"
        placeholder="用自然语言描述需求，例如：提取这片区域里大于 5 亩的耕地和园地"
        @keyup.enter.ctrl="run"
      />
      <el-select v-model="form.land_types" multiple collapse-tags collapse-tags-tooltip size="small" class="types" placeholder="地类（可多选）">
        <el-option v-for="t in landTypes" :key="t" :label="t" :value="t" />
      </el-select>
      <el-input-number v-model="form.min_area_mu" size="small" :min="0" :step="1" controls-position="right" class="area" />
      <span class="unit">亩以上</span>
      <el-checkbox v-model="form.save" size="small">保存为记录</el-checkbox>
      <el-button type="primary" size="small" :loading="busy" @click="run">执行提取</el-button>
      <el-tag size="small" :type="engineTag" effect="dark">{{ engineText }}</el-tag>
    </div>

    <div class="examples">
      <span class="muted">示例需求：</span>
      <el-tag v-for="ex in examples" :key="ex" class="ex" size="small" effect="plain" @click="useExample(ex)">{{ ex }}</el-tag>
      <span v-if="ctx" class="muted right">
        库内 {{ num(ctx.plots?.count, 0) }} 块 / {{ num(ctx.plots?.total_area_mu) }} 亩 · 知识 {{ ctx.kb?.chunks || 0 }} 片（{{ ctx.kb?.backend || '-' }}）
        · 模型 {{ ctx.llm?.configured ? ctx.llm.model : '未配置（走规则降级）' }}
      </span>
    </div>

    <div class="body">
      <div class="map-col">
        <MapCanvas
          v-if="ctx"
          ref="mapRef"
          v-model="form.aoi"
          :features="result?.geojson || null"
          :center="center"
          :zoom="12"
          :show-plots-default="true"
          height="100%"
          @tile-error="onTileError"
        />
        <div v-else class="map-loading" v-loading="true" element-loading-text="加载提取上下文…" />
      </div>

      <div class="side">
        <el-tabs v-model="tab" class="tabs">
          <el-tab-pane label="结果统计" name="stat">
            <div v-if="result" class="pane">
              <StatCards :statistics="result.statistics" :knowledge="result.knowledge" />
              <el-alert v-for="(w, i) in result.warnings || []" :key="i" type="warning" :closable="false" class="mt8" :title="w" />
              <el-alert v-if="result.error" type="error" :closable="false" class="mt8" :title="`提取失败：${result.error}`" />
            </div>
            <el-empty v-else :image-size="70" description="尚未执行提取">
              <div class="hint">① 在左侧地图上「矩形」或「多边形」框选范围（不框选则由工作流自行定位）<br />② 输入需求或直接点示例<br />③ 执行提取</div>
            </el-empty>
          </el-tab-pane>

          <el-tab-pane :label="`分析结论${result?.analysis ? ' ●' : ''}`" name="analysis">
            <MdView v-if="result?.analysis" :content="result.analysis" />
            <el-empty v-else :image-size="70" :description="result ? '本次没有生成结论文本' : '执行提取后在这里查看大模型归纳的结论'" />
          </el-tab-pane>

          <el-tab-pane label="执行轨迹" name="trace">
            <TraceTimeline v-if="result?.trace?.length" :items="result.trace" />
            <el-empty v-else :image-size="70" description="暂无轨迹" />
          </el-tab-pane>

          <el-tab-pane :label="`地块明细${rows.length ? ` (${rows.length})` : ''}`" name="rows">
            <el-table :data="rows" size="small" height="calc(100% - 46px)" :empty-text="'暂无地块'">
              <el-table-column prop="code" label="编号" width="90" />
              <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
              <el-table-column prop="land_type" label="地类" width="80" />
              <el-table-column prop="region" label="区域" width="90" />
              <el-table-column prop="area_mu" label="面积(亩)" width="96" sortable :sort-method="(a, b) => a.area_mu - b.area_mu" />
              <el-table-column prop="origin" label="来源" width="80">
                <template #default="{ row }">{{ row.origin === 'candidate' ? '网格候选' : '矢量' }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>

        <div class="actions">
          <el-button size="small" :disabled="!rows.length" @click="exportGeojson">导出 GeoJSON</el-button>
          <el-button size="small" type="success" :disabled="!rows.length" :loading="saving" @click="saveAsPlots">结果存为地块</el-button>
          <el-button size="small" @click="sampleVisible = true">生成示例数据</el-button>
          <el-button size="small" :disabled="!result" @click="resetResult">清空</el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="sampleVisible" title="生成示例地块" width="420px">
      <el-form label-width="92px">
        <el-form-item label="数量"><el-input-number v-model="sample.count" :min="1" :max="500" /></el-form-item>
        <el-form-item label="覆盖重建"><el-switch v-model="sample.overwrite" /></el-form-item>
      </el-form>
      <div class="muted small">用于没有真实矢量数据时演示：在北京各区的范围内生成带抖动的规则/六边形地块，面积由空间计算得出。</div>
      <template #footer>
        <el-button @click="sampleVisible = false">取消</el-button>
        <el-button type="primary" :loading="sampling" @click="makeSample">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import MapCanvas from '@/components/MapCanvas.vue'
import StatCards from '@/components/StatCards.vue'
import TraceTimeline from '@/components/TraceTimeline.vue'
import MdView from '@/components/MdView.vue'
import { download, featureRows, num } from '@/utils/geo'

const ctx = ref(null)
const result = ref(null)
const busy = ref(false)
const saving = ref(false)
const tab = ref('stat')
const mapRef = ref(null)
const sampleVisible = ref(false)
const sampling = ref(false)
const sample = reactive({ count: 80, overwrite: false })

const form = reactive({
  mode: 'smart',
  query: '',
  aoi: null,
  land_types: [],
  min_area_mu: 0,
  save: true
})

const examples = [
  '提取这片区域里大于 5 亩的耕地和园地',
  '统计朝阳区建设用地，面积不限',
  '海淀区 20 亩以上的林地和水域有多少',
  '把范围内的草地和未利用地都挑出来'
]

const landTypes = computed(() => ctx.value?.land_types || ['耕地', '园地', '林地', '草地', '建设用地', '水域', '未利用地'])
const rows = computed(() => featureRows(result.value?.geojson))
const engineTag = computed(() => (ctx.value?.engine === 'postgis' ? 'success' : 'warning'))
const engineText = computed(() => (ctx.value?.engine === 'postgis' ? 'PostGIS 引擎' : '本地降级引擎'))
const center = computed(() => {
  const b = ctx.value?.extent
  if (!b || b.length < 4) return [39.908, 116.397]
  return [(b[1] + b[3]) / 2, (b[0] + b[2]) / 2]
})

function useExample(text) {
  form.mode = 'smart'
  form.query = text
}

async function loadContext() {
  ctx.value = await api.extractContext()
  if (!form.min_area_mu && ctx.value.min_area_mu) form.min_area_mu = ctx.value.min_area_mu
}

onMounted(() => {
  loadContext().catch(() => {
    ctx.value = { land_types: landTypes.value, plots: {}, kb: {}, llm: {} }
  })
})

async function run() {
  if (form.mode === 'space' && !form.aoi) return ElMessage.warning('纯计算模式必须先框选范围（AOI）')
  if (form.mode === 'smart' && !form.query.trim() && !form.aoi) return ElMessage.warning('请描述需求或框选范围')
  busy.value = true
  const tip = setTimeout(() => ElMessage.info('正在执行提取，长任务可能需要十几秒…'), 6000)
  try {
    const payload = {
      query: form.query,
      mode: form.mode,
      aoi: form.aoi,
      land_types: form.land_types,
      min_area_mu: form.min_area_mu,
      save: form.save
    }
    result.value = await api.runExtract(payload)
    if (result.value.error) ElMessage.error(`提取失败：${result.value.error}`)
    else ElMessage.success(`完成：命中 ${result.value.statistics?.count ?? 0} 个地块，合计 ${num(result.value.statistics?.total_area_mu)} 亩`)
    tab.value = result.value.analysis ? 'analysis' : 'stat'
    await loadContext()
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    clearTimeout(tip)
    busy.value = false
  }
}

function resetResult() {
  result.value = null
  tab.value = 'stat'
}

function exportGeojson() {
  download(`plots-${Date.now()}.geojson`, result.value.geojson)
  ElMessage.success('已导出 GeoJSON 文件')
}

async function saveAsPlots() {
  saving.value = true
  try {
    const res = await api.savePlots({ task_id: result.value?.task_id || 0, features: result.value.geojson.features })
    ElMessage.success(res.message)
    mapRef.value?.reloadPlots?.()
    await loadContext()
  } finally {
    saving.value = false
  }
}

async function makeSample() {
  sampling.value = true
  try {
    const res = await api.samplePlots({ ...sample })
    ElMessage.success(res.message)
    sampleVisible.value = false
    if (sample.overwrite) result.value = null
    mapRef.value?.reloadPlots?.()
    await loadContext()
  } finally {
    sampling.value = false
  }
}

function onTileError(item) {
  ElMessageBox.alert(
    `底图「${item.name}」的瓦片连续 3 次加载失败，已自动切换到 OpenStreetMap 备用底图。\n常见原因：Token 未配置或过期、域名未加入白名单、开启了安全密钥但未填 sk。可到「系统配置」的对应分组做一键连通性测试。`,
    '底图降级提示',
    { type: 'warning' }
  ).catch(() => {})
}
</script>

<style scoped>
.extract {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 12px;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  background: #fff;
  padding: 8px 10px;
  border-radius: 8px;
}

.query {
  flex: 1;
  min-width: 240px;
}

.types {
  width: 190px;
}

.area {
  width: 110px;
}

.unit {
  font-size: 12px;
  color: #8a919f;
  margin-left: -4px;
}

.examples {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  padding: 6px 2px;
}

.ex {
  cursor: pointer;
}

.right {
  margin-left: auto;
}

.body {
  flex: 1;
  display: flex;
  gap: 10px;
  min-height: 0;
}

.map-col {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}

.map-loading {
  height: 100%;
}

.side {
  width: 428px;
  flex: none;
  background: #fff;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.tabs {
  flex: 1;
  min-height: 0;
  padding: 0 12px;
}

:deep(.el-tabs__content),
:deep(.el-tab-pane) {
  height: 100%;
}

:deep(.el-tabs__content) {
  overflow: auto;
}

.pane {
  padding-bottom: 10px;
}

.mt8 {
  margin-top: 8px;
}

.hint {
  font-size: 12px;
  color: #8a919f;
  line-height: 2;
}

.actions {
  flex: none;
  padding: 8px 12px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.small {
  font-size: 12px;
  line-height: 1.8;
}
</style>
