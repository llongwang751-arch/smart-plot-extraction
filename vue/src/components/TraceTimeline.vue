<template>
  <el-timeline v-if="items.length" class="tl">
    <el-timeline-item
      v-for="(row, index) in items"
      :key="index"
      :timestamp="`${row.elapsed_ms || 0} ms`"
      placement="top"
      :type="dotType(row)"
      :hollow="dotType(row) === 'info'"
      size="normal"
    >
      <div class="head">
        <b>{{ index + 1 }}. {{ row.label || row.node }}</b>
        <el-tag size="small" :type="tagType(row)" effect="plain">{{ row.via || '-' }}</el-tag>
      </div>
      <div class="detail">{{ row.detail || '已执行' }}</div>
    </el-timeline-item>
  </el-timeline>
  <el-empty v-else description="暂无执行轨迹" :image-size="60" />
</template>

<script setup>
defineProps({ items: { type: Array, default: () => [] } })

const dotType = (row) => {
  const via = String(row.via || '')
  if (String(row.detail || '').includes('失败') || via.includes('error')) return 'danger'
  if (via.includes('degrade') || via.includes('skip') || via.includes('template') || via.includes('rule')) return 'warning'
  return 'primary'
}

const tagType = (row) => (dotType(row) === 'danger' ? 'danger' : dotType(row) === 'warning' ? 'warning' : 'success')
</script>

<style scoped>
.tl {
  padding-left: 2px;
  margin-top: 6px;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.detail {
  margin-top: 4px;
  color: #606266;
  font-size: 12px;
  line-height: 1.7;
}
</style>
