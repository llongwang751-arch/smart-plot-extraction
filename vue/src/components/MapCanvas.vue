<template>
  <div class="map-wrap" :style="{ height }">
    <div ref="el" class="map" />
    <div v-if="!mini" class="toolbar">
      <el-select v-model="baseKey" size="small" class="base-select" @change="applyBase">
        <el-option v-for="b in basemaps" :key="b.key" :label="b.name" :value="b.key">
          <span>{{ b.name }}</span>
          <span v-if="!b.configured" class="off">（未配置）</span>
        </el-option>
      </el-select>
      <el-tooltip content="框选矩形范围" placement="bottom">
        <el-button size="small" :type="mode === 'rect' ? 'warning' : 'default'" @click="toggle('rect')">▭ 矩形</el-button>
      </el-tooltip>
      <el-tooltip content="手绘多边形范围（双击或点“完成”闭合）" placement="bottom">
        <el-button size="small" :type="mode === 'poly' ? 'warning' : 'default'" @click="toggle('poly')">⬠ 多边形</el-button>
      </el-tooltip>
      <el-button v-if="mode === 'poly'" size="small" type="primary" @click="closePolygon">✓ 闭合</el-button>
      <el-button size="small" @click="clearAoi">✕ 清范围</el-button>
      <el-button size="small" @click="fitAll">⤢ 全览</el-button>
      <el-tooltip :content="tileHint" placement="bottom">
        <el-checkbox v-model="showPlots" size="small" label="库内地块" border />
      </el-tooltip>
    </div>
    <div v-if="drawingHint" class="draw-hint">{{ drawingHint }}</div>
    <div v-if="!basemaps.length" class="loading">底图加载中…</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import { ElMessage } from 'element-plus'
import { api, tileUrl } from '@/api'
import { boundsOf, colorOf, geomAreaMu, props as featureProps } from '@/utils/geo'

const props = defineProps({
  modelValue: { type: Object, default: null },
  features: { type: Object, default: null },
  drawMode: { type: String, default: 'none' },
  mini: { type: Boolean, default: false },
  fit: { type: Boolean, default: true },
  center: { type: Array, default: () => [39.908, 116.397] },
  zoom: { type: Number, default: 11 },
  height: { type: String, default: '100%' },
  showPlotsDefault: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'update:drawMode', 'tile-error', 'ready'])

const el = ref(null)
const basemaps = ref([])
const baseKey = ref('')
const mode = ref('none')
const showPlots = ref(props.showPlotsDefault)
const tileHint = ref('勾选后可把库内已有地块叠加显示，用于判断提取范围是否覆盖到位')
const drawingHint = ref('')

let map = null
let baseLayers = {}
let tileErrors = 0
let fellBack = false
let aoiLayer = null
let featLayer = null
let plotLayer = null
let drawLayer = null
let rectStart = null
let rectShape = null
let verts = []
let polyShape = null
let observer = null

const selfAoi = ref(false)

function toggle(next) {
  setMode(mode.value === next ? 'none' : next)
}

function setMode(next) {
  mode.value = next
  emit('update:drawMode', next)
  resetDrawing()
  if (next === 'rect') {
    drawingHint.value = '在地图上按下并拖动，松开即完成矩形框选'
    map.dragging.disable()
  } else if (next === 'poly') {
    drawingHint.value = '依次点击落点，双击或点“闭合”完成；至少 3 个顶点'
    map.doubleClickZoom.disable()
  } else {
    drawingHint.value = ''
    map.dragging.enable()
    map.doubleClickZoom.enable()
  }
}

function resetDrawing() {
  if (rectShape) drawLayer.removeLayer(rectShape)
  if (polyShape) drawLayer.removeLayer(polyShape)
  rectShape = null
  polyShape = null
  rectStart = null
  verts = []
}

function onDown(e) {
  if (mode.value !== 'rect') return
  rectStart = e.latlng
  rectShape = L.rectangle(L.latLngBounds(rectStart, rectStart), {
    color: '#f0a020', weight: 2, dashArray: '6,4', fillOpacity: 0.06
  }).addTo(drawLayer)
  map.on('mousemove', onMove)
  map.once('mouseup', onUp)
}

function onMove(e) {
  if (rectShape && rectStart) rectShape.setBounds(L.latLngBounds(rectStart, e.latlng))
}

function onUp(e) {
  map.off('mousemove', onMove)
  if (!rectStart) return
  const bounds = L.latLngBounds(rectStart, e.latlng)
  const sw = bounds.getSouthWest()
  const ne = bounds.getNorthEast()
  setMode('none')
  if (Math.abs(ne.lng - sw.lng) < 1e-6 || Math.abs(ne.lat - sw.lat) < 1e-6) {
    ElMessage.info('框选范围过小，已忽略')
    return
  }
  const ring = [
    [sw.lng, sw.lat], [ne.lng, sw.lat], [ne.lng, ne.lat], [sw.lng, ne.lat], [sw.lng, sw.lat]
  ]
  commitAoi({ type: 'Polygon', coordinates: [ring] })
}

function onClick(e) {
  if (mode.value !== 'poly') return
  verts.push([e.latlng.lng, e.latlng.lat])
  drawPolygon(false)
}

function drawPolygon(finished) {
  if (polyShape) drawLayer.removeLayer(polyShape)
  if (!verts.length) return
  const latlngs = verts.map(([lng, lat]) => [lat, lng])
  polyShape = L[filled(finished) ? 'polygon' : 'polyline'](latlngs, {
    color: '#f0a020', weight: 2, dashArray: finished ? '' : '6,4', fillOpacity: finished ? 0.08 : 0
  }).addTo(drawLayer)
}

const filled = (finished) => finished && verts.length >= 3

function closePolygon() {
  if (mode.value !== 'poly') return
  if (verts.length < 3) {
    ElMessage.warning('至少需要 3 个顶点')
    return
  }
  const ring = [...verts, verts[0]]
  setMode('none')
  commitAoi({ type: 'Polygon', coordinates: [ring] })
}

function commitAoi(geojson) {
  selfAoi.value = true
  emit('update:modelValue', geojson)
  renderAoi(geojson)
}

function clearAoi() {
  resetDrawing()
  if (aoiLayer) {
    map.removeLayer(aoiLayer)
    aoiLayer = null
  }
  commitAoi(null)
}

function renderAoi(geojson) {
  if (aoiLayer) {
    map.removeLayer(aoiLayer)
    aoiLayer = null
  }
  if (!geojson) return
  aoiLayer = L.geoJSON(geojson, {
    style: { color: '#f0a020', weight: 2, dashArray: '6,4', fillColor: '#f0a020', fillOpacity: 0.07 }
  }).addTo(map)
}

function renderFeatures(geojson) {
  if (featLayer) {
    map.removeLayer(featLayer)
    featLayer = null
  }
  if (!geojson || !(geojson.features || []).length) return
  featLayer = L.geoJSON(geojson, {
    style: (f) => {
      const c = colorOf(featureProps(f).land_type)
      return { color: c, weight: 1.6, fillColor: c, fillOpacity: 0.28 }
    },
    onEachFeature: (f, layer) => {
      const p = featureProps(f)
      const mu = p.area_mu != null ? Number(p.area_mu).toFixed(2) : geomAreaMu(f.geometry).toFixed(2)
      layer.bindTooltip(`${p.name || '地块'}｜${p.land_type || '未标注'}｜${mu} 亩`, {
        sticky: true, className: 'plot-tip'
      })
      const rows = Object.entries(p)
        .filter(([k]) => ['code', 'name', 'land_type', 'region', 'owner', 'area_mu', 'origin'].includes(k))
        .map(([k, v]) => `<tr><td>${k}</td><td>${v ?? ''}</td></tr>`)
        .join('')
      layer.bindPopup(`<table class="pk">${rows}</table>`)
    }
  }).addTo(map)
  if (props.fit) fitAll()
}

async function loadPlots() {
  if (!showPlots.value) {
    if (plotLayer) {
      map.removeLayer(plotLayer)
      plotLayer = null
    }
    return
  }
  const fc = await api.plotGeojson({ limit: 1000 })
  if (plotLayer) map.removeLayer(plotLayer)
  plotLayer = L.geoJSON(fc, {
    style: (f) => {
      const c = colorOf(featureProps(f).land_type)
      return { color: c, weight: 1, fillColor: c, fillOpacity: 0.14 }
    }
  }).addTo(map)
  plotLayer.bringToBack()
}

function fitAll() {
  const bounds = L.latLngBounds([])
  ;[props.features, props.modelValue].forEach((g) => {
    const b = boundsOf(g)
    if (b) bounds.extend(b[0]).extend(b[1])
  })
  if (bounds.isValid()) {
    map.fitBounds(bounds.pad(0.15))
    return
  }
  const pb = plotLayer && plotLayer.getBounds ? plotLayer.getBounds() : null
  if (pb && pb.isValid()) map.fitBounds(pb.pad(0.15))
  else map.setView(props.center, props.zoom)
}

function makeTile(item) {
  const layers = [L.tileLayer(tileUrl(item.url), { maxZoom: 18, attribution: item.attribution })]
  if (item.anno) {
    const anno = basemaps.value.find((b) => b.layer === item.anno)
    if (anno) layers.unshift(L.tileLayer(tileUrl(anno.url), { maxZoom: 18 }))
  }
  layers.forEach((layer) => {
    layer.on('tileload', () => {
      tileErrors = 0
    })
    layer.on('tileerror', () => {
      tileErrors += 1
      if (tileErrors >= 3 && !fellBack) fallBack(item)
    })
  })
  return layers
}

function fallBack(item) {
  fellBack = true
  tileErrors = 0
  const osm = baseLayers.osm
  if (osm) {
    baseKey.value = 'osm'
    applyBase('osm')
  }
  ElMessage.warning(`底图「${item.name}」连续 3 次加载失败，已自动切换到备用底图（OpenStreetMap）。请检查「系统配置」里的 Token / 安全密钥。`)
  emit('tile-error', item)
}

function applyBase(key) {
  Object.values(baseLayers).forEach((group) => group.forEach((l) => map.removeLayer(l)))
  const item = basemaps.value.find((b) => b.key === key)
  if (!item) return
  const layers = makeTile(item)
  baseLayers[key] = layers
  layers.forEach((l) => l.addTo(map))
}

onMounted(async () => {
  map = L.map(el.value, { center: props.center, zoom: props.zoom, zoomControl: true, attributionControl: false, preferCanvas: true })
  drawLayer = L.layerGroup().addTo(map)
  aoiLayer = null
  renderAoi(props.modelValue)
  renderFeatures(props.features)
  try {
    const res = await api.basemaps()
    basemaps.value = res.items || []
    const first = basemaps.value.find((b) => b.key === 'tianditu_img') || basemaps.value.find((b) => b.configured) || basemaps.value[0]
    if (first) {
      baseKey.value = first.key
      applyBase(first.key)
    }
  } catch (e) {
    baseKey.value = 'osm'
    basemaps.value = [{ key: 'osm', name: 'OpenStreetMap（备用）', provider: 'osm', layer: 'default', url: '/api/maps/tile?provider=osm&layer=default&z={z}&x={x}&y={y}' }]
    applyBase('osm')
  }
  map.on('mousedown', onDown)
  map.on('click', onClick)
  map.on('dblclick', () => mode.value === 'poly' && closePolygon())
  observer = new ResizeObserver(() => map.invalidateSize())
  observer.observe(el.value)
  setTimeout(() => map.invalidateSize(), 60)
  if (showPlots.value) loadPlots()
  emit('ready', map)
})

onBeforeUnmount(() => {
  observer && observer.disconnect()
  map && map.remove()
  map = null
})

watch(() => props.drawMode, (v) => {
  if (map && v !== mode.value) setMode(v)
})

watch(
  () => props.modelValue,
  (v) => {
    if (selfAoi.value) {
      selfAoi.value = false
      return
    }
    renderAoi(v || null)
    if (v && props.fit) {
      const b = boundsOf(v)
      if (b) map && map.fitBounds(L.latLngBounds(b[0], b[1]).pad(0.2))
    }
  }
)

watch(() => props.features, (v) => renderFeatures(v || null))
watch(showPlots, () => map && loadPlots())

defineExpose({ fitAll, clearAoi, startDraw: toggle, reloadPlots: loadPlots, getMap: () => map })
</script>

<style scoped>
.map-wrap {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 8px;
}

.map {
  position: absolute;
  inset: 0;
}

.toolbar {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 1000;
  display: flex;
  gap: 6px;
  align-items: center;
  background: rgba(255, 255, 255, 0.94);
  padding: 6px;
  border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.16);
  flex-wrap: wrap;
  max-width: calc(100% - 60px);
}

.base-select {
  width: 148px;
}

.off {
  color: #c0c4cc;
  font-size: 12px;
  margin-left: 6px;
}

.draw-hint {
  position: absolute;
  left: 50%;
  top: 12px;
  transform: translateX(-50%);
  z-index: 1000;
  background: rgba(31, 41, 55, 0.86);
  color: #fff;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 14px;
}

.loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8a919f;
  background: #eef1f5;
  z-index: 900;
}
</style>

<style>
.pk td {
  font-size: 12px;
  padding: 2px 6px;
  border-bottom: 1px dashed #eee;
}

.pk td:first-child {
  color: #8a919f;
}
</style>
