<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>知识库（RAG）</h2>
        <div class="sub">
          向量后端：{{ status.backend || '-' }} · 切片 {{ num(status.chunks, 0) }} 片 · 嵌入模型 {{ status.embed_model || '-' }} ·
          切块 {{ status.chunk_size }} 字 / 重叠 {{ status.chunk_overlap }} 字 · 检索 Top-K {{ status.top_k }}
        </div>
      </div>
      <div class="head-actions">
        <el-button size="small" @click="textVisible = true">录入文本</el-button>
        <el-upload :show-file-list="false" :http-request="doUpload" :accept="accepts">
          <el-button size="small" type="primary">上传文档</el-button>
        </el-upload>
      </div>
    </div>

    <el-alert v-if="status.message" type="warning" :closable="false" class="mb" :title="`向量后端提示：${status.message}`" />
    <el-alert
      v-else
      type="info"
      :closable="false"
      class="mb"
      title="入库链路：解析（多编码兜底 utf-8 → utf-8-sig → gbk → gb18030，pdf 走 pypdf，json 自动展平）→ 中文标点优先的分块 → 嵌入向量化 → 检索时取 Top-K 注入上下文。删除文档会同步清理向量，不留脏数据。"
    />

    <el-row :gutter="12">
      <el-col :span="14">
        <div class="card">
          <div class="card-head">
            文档台账
            <el-input v-model="keyword" size="small" placeholder="按名称搜索" clearable class="kw" @keyup.enter="load(1)" @clear="load(1)" />
          </div>
          <el-table :data="items" size="small" v-loading="loading" empty-text="还没有文档">
            <el-table-column prop="id" label="ID" width="52" />
            <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
            <el-table-column label="来源" width="80">
              <template #default="{ row }">{{ row.source === 'text' ? '录入' : '上传' }}</template>
            </el-table-column>
            <el-table-column prop="file_ext" label="类型" width="70" />
            <el-table-column label="字数" width="90">
              <template #default="{ row }">{{ num(row.char_count, 0) }}</template>
            </el-table-column>
            <el-table-column prop="chunk_count" label="切片" width="70" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tooltip :content="row.error || '入库正常'" placement="top">
                  <el-tag size="small" :type="row.status === 'ready' ? 'success' : row.status === 'failed' ? 'danger' : 'info'">
                    {{ { ready: '就绪', failed: '失败', pending: '处理中' }[row.status] || row.status }}
                  </el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="158" />
            <el-table-column label="操作" width="70" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            class="pg"
            layout="total, prev, pager, next"
            :total="total"
            v-model:current-page="page"
            :page-size="20"
            @current-change="load()"
          />
        </div>
      </el-col>

      <el-col :span="10">
        <div class="card">
          <div class="card-head">检索测试<small class="muted">看命中了哪些片段、相似度多少</small></div>
          <div class="search">
            <el-input v-model="q" size="small" placeholder="例如：耕地怎么认定？面积按什么口径？" @keyup.enter="search" />
            <el-input-number v-model="k" size="small" :min="1" :max="10" controls-position="right" class="kk" />
            <el-button size="small" type="primary" :loading="searching" @click="search">检索</el-button>
          </div>
          <div v-if="hits.length" class="hits">
            <div v-for="(h, i) in hits" :key="i" class="hit">
              <div class="hh">
                <b>#{{ i + 1 }} {{ h.doc_name }}</b>
                <span class="sc mono">chunk {{ h.chunk_index }} · 相似度 {{ h.score }}</span>
              </div>
              <el-progress :percentage="Math.min(100, Math.round((h.score || 0) * 100))" :stroke-width="6" :show-text="false" />
              <div class="ht">{{ h.text }}</div>
            </div>
          </div>
          <el-empty v-else-if="searched" :image-size="60" description="没有命中，试试换个说法或先上传文档" />
          <div v-else class="muted small">支持 {{ accepts }} 格式；检索结果会随每次提取/问答注入大模型上下文。</div>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="textVisible" title="录入文本知识" width="620px">
      <el-form label-width="62px">
        <el-form-item label="名称"><el-input v-model="textForm.name" placeholder="如 耕作层认定补充说明" /></el-form-item>
        <el-form-item label="内容">
          <el-input v-model="textForm.text" type="textarea" :rows="10" placeholder="支持 Markdown；按中文标点分块，约 500 字一片、重叠 80 字" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="textVisible = false">取消</el-button>
        <el-button type="primary" :loading="ingesting" @click="submitText">入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { num } from '@/utils/geo'

const items = ref([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const status = ref({})
const loading = ref(false)
const textVisible = ref(false)
const ingesting = ref(false)
const textForm = reactive({ name: '', text: '' })
const q = ref('耕地与园地的认定标准是什么？面积按什么口径计算？')
const k = ref(4)
const hits = ref([])
const searching = ref(false)
const searched = ref(false)
const accepts = '.txt,.md,.csv,.json,.pdf'

async function load(toPage) {
  if (toPage) page.value = toPage
  loading.value = true
  try {
    const res = await api.kbDocs({ page: page.value, size: 20, keyword: keyword.value })
    items.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function refreshStatus() {
  status.value = await api.kbStatus()
  if (status.value.top_k) k.value = status.value.top_k
}

async function submitText() {
  if (!textForm.name.trim() || !textForm.text.trim()) return ElMessage.warning('名称与内容都不能为空')
  ingesting.value = true
  try {
    const res = await api.kbText({ ...textForm })
    ElMessage.success(res.message)
    textVisible.value = false
    Object.assign(textForm, { name: '', text: '' })
    await Promise.all([load(1), refreshStatus()])
  } finally {
    ingesting.value = false
  }
}

async function doUpload({ file }) {
  const form = new FormData()
  form.append('file', file)
  form.append('name', file.name)
  const res = await api.kbUpload(form)
  ElMessage.success(res.message)
  await Promise.all([load(1), refreshStatus()])
}

async function remove(row) {
  const ok = await ElMessageBox.confirm(`删除「${row.name}」会同时清理它的 ${row.chunk_count} 条向量，确定？`, '提示', { type: 'warning' }).catch(() => false)
  if (!ok) return
  await api.kbDelete(row.id)
  ElMessage.success('文档与向量已一并删除')
  await Promise.all([load(), refreshStatus()])
}

async function search() {
  if (!q.value.trim()) return
  searching.value = true
  try {
    const res = await api.kbSearch({ query: q.value, k: k.value })
    hits.value = res.items || []
    searched.value = true
  } finally {
    searching.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(1), refreshStatus()])
  search()
})
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mb {
  margin-bottom: 12px;
  line-height: 1.8;
}

.kw {
  width: 170px;
}

.pg {
  margin-top: 10px;
  justify-content: flex-end;
}

.card-head small {
  font-weight: 400;
  font-size: 11px;
  margin-left: 6px;
}

.search {
  display: flex;
  gap: 6px;
}

.kk {
  width: 90px;
  flex: none;
}

.hits {
  margin-top: 10px;
  max-height: 460px;
  overflow: auto;
}

.hit {
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
}

.hh {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 4px;
}

.sc {
  color: #2c5282;
}

.ht {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.8;
  margin-top: 4px;
  white-space: pre-wrap;
}

.small {
  font-size: 12px;
  line-height: 1.8;
  margin-top: 10px;
}
</style>
