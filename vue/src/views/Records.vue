<template>
  <div class="page" v-loading="loading">
    <div class="page-title">
      <div>
        <h2>提取记录</h2>
        <div class="sub">每次提取（智能 / 纯计算）都会落库：需求原文、AOI、结果 GeoJSON、统计、执行轨迹、大模型结论</div>
      </div>
      <div class="filters">
        <el-radio-group v-model="query.mode" size="small" @change="load(1)">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="smart">智能</el-radio-button>
          <el-radio-button value="space">纯计算</el-radio-button>
        </el-radio-group>
        <el-button size="small" @click="load(query.page)">刷新</el-button>
      </div>
    </div>

    <div class="card">
      <el-table :data="items" size="small" empty-text="还没有提取记录">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="title" label="需求 / 标题" min-width="220" show-overflow-tooltip />
        <el-table-column label="模式" width="86">
          <template #default="{ row }">
            <el-tag size="small" :type="row.mode === 'smart' ? 'primary' : 'success'" effect="plain">
              {{ row.mode === 'smart' ? '智能' : '纯计算' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="引擎" width="86">
          <template #default="{ row }">{{ row.engine === 'postgis' ? 'PostGIS' : '本地' }}</template>
        </el-table-column>
        <el-table-column prop="count" label="地块数" width="80" />
        <el-table-column label="面积(亩)" width="106">
          <template #default="{ row }">{{ num(row.total_area_mu) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="86">
          <template #default="{ row }">{{ row.elapsed_ms }} ms</template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ok' ? 'success' : 'danger'">{{ row.status === 'ok' ? '成功' : '失败' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="open(row.id)">回看</el-button>
            <el-button link type="success" size="small" @click="savePlots(row)">存为地块</el-button>
            <el-button link size="small" @click="downloadJson(row)">下载</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pg"
        layout="total, sizes, prev, pager, next"
        :total="total"
        v-model:current-page="query.page"
        v-model:page-size="query.size"
        :page-sizes="[10, 20, 50]"
        @current-change="load()"
        @size-change="load(1)"
      />
    </div>

    <el-drawer v-model="detailVisible" size="62%" :title="detail ? `记录 #${detail.id} · ${detail.title}` : '记录详情'">
      <div v-if="detail" class="detail">
        <el-descriptions :column="3" size="small" border>
          <el-descriptions-item label="模式">{{ detail.mode === 'smart' ? '智能提取' : '纯计算' }}</el-descriptions-item>
          <el-descriptions-item label="引擎">{{ detail.engine }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="地类">{{ (detail.land_types || []).join('、') || '不限' }}</el-descriptions-item>
          <el-descriptions-item label="最小面积">{{ num(detail.min_area_mu) }} 亩</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detail.elapsed_ms }} ms</el-descriptions-item>
          <el-descriptions-item label="需求原文" :span="3">{{ detail.query || '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-alert v-if="detail.error" type="error" :closable="false" :title="detail.error" class="mt" />

        <div class="grid mt">
          <div class="card">
            <div class="card-head">结果地图（重载结果）</div>
            <MapCanvas mini :features="detail.geojson" :model-value="detail.aoi" height="330px" :show-plots-default="false" />
          </div>
          <div class="card">
            <div class="card-head">统计</div>
            <StatCards :statistics="detail.statistics" />
          </div>
        </div>

        <div class="card mt">
          <div class="card-head">分析结论</div>
          <MdView v-if="detail.analysis" :content="detail.analysis" />
          <span v-else class="muted">本次没有结论文本</span>
        </div>

        <div class="card mt">
          <div class="card-head">执行轨迹（{{ detail.trace?.length || 0 }} 个节点）</div>
          <TraceTimeline :items="detail.trace || []" />
        </div>

        <div class="card mt">
          <div class="card-head">地块明细（{{ rows.length }}）</div>
          <el-table :data="rows" size="small" max-height="300">
            <el-table-column prop="code" label="编号" width="96" />
            <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="land_type" label="地类" width="90" />
            <el-table-column prop="region" label="区域" width="100" />
            <el-table-column prop="area_mu" label="面积(亩)" width="110" sortable />
            <el-table-column prop="origin" label="来源" width="90" />
          </el-table>
        </div>
      </div>
    </el-drawer>
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

const items = ref([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ page: 1, size: 10, mode: '' })
const detailVisible = ref(false)
const detail = ref(null)

const rows = computed(() => featureRows(detail.value?.geojson))

async function load(page) {
  if (page) query.page = page
  loading.value = true
  try {
    const res = await api.records({ ...query })
    items.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function open(id) {
  detail.value = await api.record(id)
  detailVisible.value = true
}

async function savePlots(row) {
  const res = await api.saveRecordPlots(row.id)
  ElMessage.success(res.message)
}

async function remove(row) {
  const ok = await ElMessageBox.confirm(`确定删除记录 #${row.id}？该操作不可恢复。`, '提示', { type: 'warning' }).catch(() => false)
  if (!ok) return
  await api.deleteRecord(row.id)
  ElMessage.success('记录已删除')
  await load()
}

function downloadJson(row) {
  api.record(row.id).then((task) => download(`record-${row.id}.geojson`, task.geojson))
}

onMounted(() => load())
</script>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  align-items: center;
}

.pg {
  margin-top: 10px;
  justify-content: flex-end;
}

.mt {
  margin-top: 12px;
}

.grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 12px;
}

.grid .card + .card {
  margin-top: 0;
}

.detail {
  padding-bottom: 20px;
}
</style>
