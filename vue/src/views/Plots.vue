<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>地块管理</h2>
        <div class="sub">
          引擎：{{ engine === 'postgis' ? 'PostGIS（面积由 ST_Area(::geography) 计算）' : '本地引擎（Shapely + 球面面积，口径一致）' }} ·
          共 {{ num(total, 0) }} 块 / {{ num(options.total_area_mu) }} 亩
        </div>
      </div>
      <div class="head-actions">
        <el-button size="small" @click="exportAll">导出全部 GeoJSON</el-button>
        <el-button size="small" @click="sampleVisible = true">生成示例数据</el-button>
        <el-button size="small" type="primary" @click="openCreate">+ 新增地块</el-button>
      </div>
    </div>

    <div class="card">
      <div class="filters">
        <el-input v-model="query.name" size="small" placeholder="名称 / 编号关键字" clearable class="w180" @keyup.enter="load(1)" />
        <el-select v-model="query.land_type" size="small" placeholder="地类" clearable class="w120">
          <el-option v-for="t in options.land_types || []" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="query.region" size="small" placeholder="区域" clearable filterable class="w140">
          <el-option v-for="r in options.regions || []" :key="r" :label="r" :value="r" />
        </el-select>
        <el-button size="small" type="primary" @click="load(1)">查询</el-button>
        <el-button size="small" @click="reset">重置</el-button>
        <span class="muted right-tip">面积由空间引擎在入库时自动计算，不用手填</span>
      </div>

      <el-table :data="items" size="small" v-loading="loading" empty-text="暂无地块，点右上角「生成示例数据」先造一批">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="code" label="编号" width="100" />
        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="地类" width="100">
          <template #default="{ row }">
            <span class="dot" :style="{ background: colorOf(row.land_type) }" />{{ row.land_type }}
          </template>
        </el-table-column>
        <el-table-column prop="region" label="区域" width="100" />
        <el-table-column prop="owner" label="权属" width="100" show-overflow-tooltip />
        <el-table-column label="面积(亩)" width="110" prop="area_mu" sortable />
        <el-table-column label="面积(㎡)" width="120">
          <template #default="{ row }">{{ num(row.area_m2) }}</template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }">{{ row.origin === 'candidate' ? '网格候选' : '矢量' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="info" size="small" @click="preview(row)">查看</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pg"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        v-model:current-page="query.page"
        v-model:page-size="query.size"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="load()"
        @size-change="load(1)"
      />
    </div>

    <el-dialog v-model="dialogVisible" :title="editing.id ? `编辑地块 #${editing.id}` : '新增地块'" width="860px" top="6vh">
      <div class="dlg">
        <el-form :model="editing" label-width="72px" class="form">
          <el-form-item label="编号"><el-input v-model="editing.code" placeholder="留空则自动生成" /></el-form-item>
          <el-form-item label="名称"><el-input v-model="editing.name" placeholder="如 朝阳区王四营耕地 01" /></el-form-item>
          <el-form-item label="地类">
            <el-select v-model="editing.land_type" class="full">
              <el-option v-for="t in options.land_types || []" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="区域"><el-input v-model="editing.region" placeholder="如 朝阳区" /></el-form-item>
          <el-form-item label="权属"><el-input v-model="editing.owner" placeholder="选填" /></el-form-item>
          <el-form-item label="面积">
            <div class="area-box">
              <b>{{ num(areaMu) }}</b> 亩 / {{ num(areaM2) }} ㎡
              <div class="muted small">在右侧地图上画边界后自动计算；保存时由空间引擎按椭球面口径重算</div>
            </div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" :disabled="!editing.geometry" @click="submit">保存地块</el-button>
            <el-button @click="clearGeometry">清除边界</el-button>
          </el-form-item>
        </el-form>
        <div class="map-box">
          <MapCanvas
            v-if="dialogVisible"
            ref="dlgMap"
            v-model="editing.geometry"
            :features="previewLayer"
            height="100%"
            :center="mapCenter"
            :show-plots-default="false"
          />
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="sampleVisible" title="生成示例地块" width="400px">
      <el-form label-width="90px">
        <el-form-item label="数量"><el-input-number v-model="sample.count" :min="1" :max="500" /></el-form-item>
        <el-form-item label="覆盖重建"><el-switch v-model="sample.overwrite" /></el-form-item>
      </el-form>
      <div class="muted small">覆盖重建会清空现有地块后重新生成。</div>
      <template #footer>
        <el-button @click="sampleVisible = false">取消</el-button>
        <el-button type="primary" :loading="sampling" @click="makeSample">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import MapCanvas from '@/components/MapCanvas.vue'
import { colorOf, download, geomAreaM2, num } from '@/utils/geo'

const items = ref([])
const total = ref(0)
const options = ref({})
const engine = ref('local')
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const sampleVisible = ref(false)
const sampling = ref(false)
const previewLayer = ref(null)
const dlgMap = ref(null)
const query = reactive({ name: '', land_type: '', region: '', page: 1, size: 20 })
const editing = reactive({ id: 0, code: '', name: '', land_type: '耕地', region: '', owner: '', geometry: null })
const sample = reactive({ count: 80, overwrite: false })
const mapCenter = ref([39.908, 116.397])

const areaM2 = computed(() => geomAreaM2(editing.geometry))
const areaMu = computed(() => areaM2.value / 666.6666666667)

async function load(page) {
  if (page) query.page = page
  loading.value = true
  try {
    const res = await api.plots({ ...query })
    items.value = res.items || []
    total.value = res.total || 0
    engine.value = res.engine
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  options.value = await api.plotOptions()
}

function reset() {
  Object.assign(query, { name: '', land_type: '', region: '', page: 1 })
  load(1)
}

function openCreate() {
  Object.assign(editing, { id: 0, code: '', name: '', land_type: (options.value.land_types || ['耕地'])[0], region: '', owner: '', geometry: null })
  previewLayer.value = null
  dialogVisible.value = true
}

async function openEdit(row) {
  const detail = await api.plot(row.id)
  Object.assign(editing, {
    id: detail.id, code: detail.code, name: detail.name, land_type: detail.land_type,
    region: detail.region, owner: detail.owner || '', geometry: detail.geometry || null
  })
  previewLayer.value = null
  dialogVisible.value = true
}

function preview(row) {
  Object.assign(editing, {
    id: row.id, code: row.code, name: row.name, land_type: row.land_type,
    region: row.region, owner: row.owner || '', geometry: row.geometry || null
  })
  previewLayer.value = row.geometry ? { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: row.geometry }] } : null
  dialogVisible.value = true
}

function clearGeometry() {
  editing.geometry = null
}

async function submit() {
  if (!editing.geometry) return ElMessage.warning('请先在右侧地图上绘制地块边界')
  saving.value = true
  try {
    const payload = {
      code: editing.code, name: editing.name, land_type: editing.land_type,
      region: editing.region, owner: editing.owner, geometry: editing.geometry
    }
    if (editing.id) await api.updatePlot(editing.id, payload)
    else await api.createPlot(payload)
    ElMessage.success(editing.id ? '地块已更新' : '地块已入库，面积由空间引擎计算')
    dialogVisible.value = false
    await Promise.all([load(), loadOptions()])
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  const ok = await ElMessageBox.confirm(`确定删除地块「${row.name || row.code}」？`, '提示', { type: 'warning' }).catch(() => false)
  if (!ok) return
  await api.deletePlot(row.id)
  ElMessage.success('地块已删除')
  await Promise.all([load(), loadOptions()])
}

async function exportAll() {
  const fc = await api.plotGeojson({ land_type: query.land_type, region: query.region, limit: 5000 })
  download(`plots-${Date.now()}.geojson`, fc)
  ElMessage.success(`已导出 ${fc.returned} 个地块`)
}

async function makeSample() {
  sampling.value = true
  try {
    const res = await api.samplePlots({ ...sample })
    ElMessage.success(res.message)
    sampleVisible.value = false
    await Promise.all([load(1), loadOptions()])
  } finally {
    sampling.value = false
  }
}

watch(dialogVisible, async (v) => {
  if (!v) return
  setTimeout(() => dlgMap.value?.fitAll(), 80)
})

onMounted(async () => {
  await Promise.all([load(1), loadOptions()])
  const ctx = await api.extractContext().catch(() => null)
  const b = ctx?.extent
  if (b && b.length === 4) mapCenter.value = [(b[1] + b[3]) / 2, (b[0] + b[2]) / 2]
})
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 6px;
}

.filters {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.w180 { width: 180px; }
.w120 { width: 120px; }
.w140 { width: 140px; }

.right-tip {
  margin-left: auto;
  font-size: 12px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: middle;
}

.pg {
  margin-top: 10px;
  justify-content: flex-end;
}

.dlg {
  display: flex;
  gap: 14px;
  height: 460px;
}

.form {
  width: 330px;
  flex: none;
}

.map-box {
  flex: 1;
  min-width: 0;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.full {
  width: 100%;
}

.area-box b {
  font-size: 18px;
}

.small {
  font-size: 12px;
  line-height: 1.6;
}
</style>
