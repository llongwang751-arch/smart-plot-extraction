<template>
  <div class="chat">
    <div class="sessions">
      <el-button size="small" type="primary" class="new" @click="newSession">+ 新会话</el-button>
      <div class="list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="item"
          :class="{ on: s.id === current }"
          @click="pick(s.id)"
        >
          <div class="t">{{ s.title }}</div>
          <div class="m">{{ s.messages }} 条 · {{ s.updated_at }}</div>
          <span class="ops">
            <el-button link size="small" @click.stop="rename(s)">✎</el-button>
            <el-button link size="small" type="danger" @click.stop="drop(s)">✕</el-button>
          </span>
        </div>
      </div>
    </div>

    <div class="main">
      <div ref="listEl" class="msgs" v-loading="loadingMsgs">
        <div v-if="!messages.length" class="welcome">
          <h3>智能问答（ReAct Agent）</h3>
          <p>助手会自主决定是否调用知识库检索、全库统计、区域查询、范围提取这 4 个工具；工具圈出的地块会直接画在右侧地图上。</p>
          <div class="chips">
            <el-tag v-for="q in suggests" :key="q" class="chip" @click="ask(q)">{{ q }}</el-tag>
          </div>
          <p class="muted small">约束：涉及面积、数量等数字必须来自工具返回结果，不允许模型编造；无可用模型时自动降级为 RAG 兜底问答。</p>
        </div>
        <div v-for="m in messages" :key="m.key" class="msg" :class="m.role">
          <div class="avatar">{{ m.role === 'user' ? '我' : 'AI' }}</div>
          <div class="body">
            <MdView v-if="m.role === 'assistant'" :content="m.content" />
            <div v-else class="text">{{ m.content }}</div>
            <div v-if="m.role === 'assistant'" class="meta">
              <el-tag size="small" effect="plain">{{ m.via || 'react-agent' }}</el-tag>
              <el-tag size="small" effect="plain" type="info">工具 {{ (m.calls || []).length }} 次</el-tag>
              <el-tag v-if="(m.sources || []).length" size="small" effect="plain" type="success">知识 {{ m.sources.length }} 条</el-tag>
              <el-tag v-if="m.geojson" size="small" effect="plain" type="warning">已上图 {{ m.geojson.features?.length || 0 }} 块</el-tag>
              <span class="muted">{{ m.elapsed_ms }} ms</span>
            </div>
          </div>
        </div>
        <div v-if="busy" class="msg assistant">
          <div class="avatar">AI</div>
          <div class="body"><span class="thinking">正在思考 / 调用工具…</span></div>
        </div>
      </div>

      <div class="input">
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          resize="none"
          placeholder="问点什么，例如：库里一共有多少地块？耕地占多少亩？（Enter 发送，Shift+Enter 换行）"
          @keydown="onKey"
        />
        <div class="row">
          <span class="muted small">最多 {{ maxSteps }} 步推理（可在系统配置调整）</span>
          <el-button type="primary" :loading="busy" @click="ask()">发送</el-button>
        </div>
      </div>
    </div>

    <div class="aside">
      <div class="card map-card">
        <div class="card-head">结果上图</div>
        <MapCanvas v-if="shown" :features="shown" mini :model-value="null" height="100%" />
        <el-empty v-else :image-size="60" description="Agent 圈出地块后自动显示" />
      </div>
      <div class="card">
        <div class="card-head">检索来源<small class="muted">（相似度可核查）</small></div>
        <div v-if="sources.length">
          <div v-for="(s, i) in sources" :key="i" class="src">
            <div class="sh">
              <b>{{ s.doc_name || '知识片段' }}</b>
              <span class="score">{{ s.score }}</span>
            </div>
            <el-progress :percentage="Math.min(100, Math.round((s.score || 0) * 100))" :stroke-width="4" :show-text="false" />
            <div class="sc">{{ (s.content || s.text || '').slice(0, 120) }}…</div>
          </div>
        </div>
        <span v-else class="muted small">本轮没有向量检索命中</span>
      </div>
      <div class="card">
        <div class="card-head">工具调用轨迹</div>
        <el-collapse v-if="calls.length">
          <el-collapse-item v-for="(c, i) in calls" :key="i" :title="`${i + 1}. ${c.name}（${c.elapsed_ms || 0} ms）`">
            <div class="lbl">入参</div>
            <pre class="mono">{{ pretty(c.args) }}</pre>
            <div class="lbl">返回</div>
            <pre class="mono">{{ pretty(c.result) }}</pre>
          </el-collapse-item>
        </el-collapse>
        <span v-else class="muted small">尚未调用工具</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api'
import MapCanvas from '@/components/MapCanvas.vue'
import MdView from '@/components/MdView.vue'

const sessions = ref([])
const messages = ref([])
const current = ref(0)
const draft = ref('')
const busy = ref(false)
const loadingMsgs = ref(false)
const maxSteps = ref(8)
const listEl = ref(null)
const lastPlots = ref(null)

const suggests = [
  '库里一共有多少个地块？总面积多少亩？',
  '耕地的认定标准是什么？面积口径怎么算？',
  '朝阳区有哪些园地？分别多少亩？',
  '海淀区建设用地有多少块？'
]

const tail = computed(() => [...messages.value].reverse().find((m) => m.role === 'assistant') || {})
const sources = computed(() => tail.value.sources || [])
const calls = computed(() => tail.value.calls || [])
const shown = computed(() => lastPlots.value || tail.value.geojson || null)

const pretty = (v) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2))

async function loadSessions() {
  const res = await api.sessions()
  sessions.value = res.items || []
}

async function pick(id) {
  current.value = id
  loadingMsgs.value = true
  try {
    const res = await api.messages(id)
    messages.value = (res.items || []).map((m, i) => ({ ...m, key: `${id}-${m.id}-${i}`, via: m.role === 'assistant' ? 'react-agent' : '' }))
    lastPlots.value = [...messages.value].reverse().find((m) => m.geojson)?.geojson || null
    scroll()
  } finally {
    loadingMsgs.value = false
  }
}

async function newSession() {
  const res = await api.createSession()
  await loadSessions()
  await pick(res.id)
}

async function rename(s) {
  const input = await ElMessageBox.prompt('会话标题', '重命名', { inputValue: s.title }).catch(() => null)
  if (!input) return
  await api.renameSession(s.id, input.value)
  await loadSessions()
}

async function drop(s) {
  const ok = await ElMessageBox.confirm(`删除会话「${s.title}」及其消息？`, '提示', { type: 'warning' }).catch(() => false)
  if (!ok) return
  await api.deleteSession(s.id)
  if (current.value === s.id) {
    current.value = 0
    messages.value = []
  }
  await loadSessions()
}

function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    ask()
  }
}

async function ask(text) {
  const question = (typeof text === 'string' && text) || draft.value.trim()
  if (!question || busy.value) return
  draft.value = ''
  messages.value.push({ key: `u-${Date.now()}`, role: 'user', content: question })
  busy.value = true
  scroll()
  try {
    const res = await api.ask({ message: question, session_id: current.value || 0 })
    maxSteps.value = res.max_steps || maxSteps.value
    messages.value.push({
      key: `a-${res.message_id || Date.now()}`,
      role: 'assistant',
      content: res.answer,
      sources: res.sources,
      calls: res.calls,
      geojson: res.plots,
      via: res.via,
      elapsed_ms: res.elapsed_ms
    })
    if (res.plots) lastPlots.value = res.plots
    if (current.value !== res.session_id) {
      current.value = res.session_id
      await loadSessions()
    }
  } catch (e) {
    messages.value.push({ key: `e-${Date.now()}`, role: 'assistant', content: '请求失败，请查看后端日志或稍后重试。', calls: [], sources: [] })
  } finally {
    busy.value = false
    scroll()
  }
}

function scroll() {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight + 200
  })
}

onMounted(async () => {
  await loadSessions()
  if (sessions.value.length) await pick(sessions.value[0].id)
})
</script>

<style scoped>
.chat {
  height: 100%;
  display: flex;
  gap: 10px;
  padding: 10px 12px 12px;
}

.sessions {
  width: 200px;
  flex: none;
  background: #fff;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.new {
  margin: 8px;
  width: calc(100% - 16px);
}

.list {
  flex: 1;
  overflow: auto;
}

.item {
  padding: 8px 10px;
  border-top: 1px solid #f3f4f6;
  cursor: pointer;
  position: relative;
}

.item:hover {
  background: #f7f9fc;
}

.item.on {
  background: #eef4ff;
}

.item .t {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 34px;
}

.item .m {
  font-size: 11px;
  color: #a8abb2;
  margin-top: 2px;
}

.ops {
  position: absolute;
  right: 4px;
  top: 6px;
  display: none;
}

.item:hover .ops {
  display: block;
}

.main {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.msgs {
  flex: 1;
  overflow: auto;
  padding: 12px 16px;
}

.welcome h3 {
  margin: 24px 0 6px;
}

.welcome p {
  color: #6b7280;
  font-size: 13px;
  line-height: 1.9;
  max-width: 640px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px 0;
}

.chip {
  cursor: pointer;
}

.msg {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.msg.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: #2c5282;
  color: #fff;
}

.msg.user .avatar {
  background: #dfe6f5;
  color: #2c5282;
}

.body {
  max-width: calc(100% - 46px);
  background: #f7f9fc;
  padding: 8px 12px;
  border-radius: 8px;
}

.msg.user .body {
  background: #eef4ff;
}

.text {
  white-space: pre-wrap;
  line-height: 1.7;
}

.meta {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 8px;
  flex-wrap: wrap;
}

.meta .muted {
  font-size: 11px;
}

.thinking {
  color: #8a919f;
  font-size: 13px;
}

.input {
  flex: none;
  border-top: 1px solid #f0f0f0;
  padding: 8px 12px 10px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}

.aside {
  width: 322px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
}

.aside .card + .card {
  margin-top: 0;
}

.map-card {
  height: 236px;
  display: flex;
  flex-direction: column;
}

.map-card :deep(.map-wrap) {
  flex: 1;
  min-height: 170px;
}

.src {
  margin-bottom: 8px;
}

.sh {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}

.score {
  color: #2c5282;
}

.sc {
  font-size: 11px;
  color: #8a919f;
  line-height: 1.6;
  margin-top: 2px;
}

.lbl {
  font-size: 11px;
  color: #8a919f;
  margin: 4px 0;
}

pre.mono {
  background: #f7f9fc;
  padding: 6px;
  border-radius: 4px;
  font-size: 11px;
  max-height: 150px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.card-head small {
  font-weight: 400;
  font-size: 11px;
}
</style>
