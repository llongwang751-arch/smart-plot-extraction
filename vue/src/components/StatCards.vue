<template>
  <div>
    <div class="metrics">
      <div v-for="m in metrics" :key="m.label" class="metric">
        <div class="label">{{ m.label }}</div>
        <div class="value">{{ m.value }}<small v-if="m.unit">{{ m.unit }}</small></div>
      </div>
    </div>

    <div v-if="byType.length" class="block">
      <div class="block-title">地类构成（按面积，无图表库，用进度条表达）</div>
      <div v-for="row in byType" :key="row.name" class="dist">
        <span class="dot" :style="{ background: colorOf(row.name) }" />
        <span class="name">{{ row.name }}</span>
        <el-progress :percentage="row.percent" :stroke-width="12" :color="colorOf(row.name)" :show-text="false" class="bar" />
        <span class="fig">{{ row.count }} 块 / {{ num(row.area_mu) }} 亩</span>
      </div>
    </div>

    <div v-if="byRegion.length" class="block">
      <div class="block-title">区域构成</div>
      <el-tag v-for="row in byRegion" :key="row.name" size="small" effect="plain" class="r-tag">
        {{ row.name }} · {{ row.count }} 块 · {{ num(row.area_mu) }} 亩
      </el-tag>
    </div>

    <div v-if="knowledge && knowledge.length" class="block">
      <div class="block-title">本次召回的知识片段（{{ knowledge.length }} 条）</div>
      <el-collapse>
        <el-collapse-item v-for="(hit, i) in knowledge" :key="i" :title="`${hit.doc_name || '知识片段'}（相似度 ${hit.score ?? '-'}）`">
          <div class="kn">{{ hit.content || hit.text || '' }}</div>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { colorOf, num } from '@/utils/geo'

const props = defineProps({
  statistics: { type: Object, default: () => ({}) },
  knowledge: { type: Array, default: () => [] }
})

const metrics = computed(() => {
  const s = props.statistics || {}
  return [
    { label: '命中地块', value: num(s.count || 0, 0), unit: ' 块' },
    { label: '合计面积', value: num(s.total_area_mu), unit: ' 亩' },
    { label: '平均面积', value: num(s.avg_area_mu), unit: ' 亩' },
    { label: '最大地块', value: num(s.max_area_mu), unit: ' 亩' },
    { label: 'AOI 面积', value: s.aoi_area_mu != null ? num(s.aoi_area_mu) : '—', unit: s.aoi_area_mu != null ? ' 亩' : '' },
    { label: '计算引擎', value: s.engine === 'postgis' ? 'PostGIS' : '本地引擎', unit: '' },
    { label: '数据来源', value: s.origin === 'candidate' ? '网格候选' : '矢量裁剪', unit: '' }
  ]
})

const share = (total) => (total > 0 ? 100 / total : 0)

const byType = computed(() => {
  const s = props.statistics || {}
  const total = Number(s.total_area_mu || 0)
  return (s.by_land_type || []).map((row) => ({ ...row, percent: Math.round(share(total) * Number(row.area_mu || 0) * 10) / 10 }))
})

const byRegion = computed(() => (props.statistics?.by_region || []).slice(0, 8))
</script>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
  gap: 8px;
}

.metric {
  background: #f7f9fc;
  border-radius: 6px;
  padding: 8px 10px;
}

.label {
  font-size: 12px;
  color: #8a919f;
}

.value {
  font-size: 17px;
  font-weight: 600;
  margin-top: 2px;
  word-break: break-all;
}

.value small {
  font-size: 11px;
  font-weight: 400;
  color: #8a919f;
  margin-left: 2px;
}

.block {
  margin-top: 12px;
}

.block-title {
  font-size: 12px;
  color: #8a919f;
  margin-bottom: 6px;
}

.dist {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 5px;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
}

.name {
  width: 62px;
  font-size: 12px;
  flex: none;
}

.bar {
  flex: 1;
}

.fig {
  width: 150px;
  text-align: right;
  font-size: 12px;
  color: #606266;
  flex: none;
}

.r-tag {
  margin: 0 6px 6px 0;
}

.kn {
  font-size: 12px;
  line-height: 1.8;
  color: #4b5563;
  max-height: 150px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
