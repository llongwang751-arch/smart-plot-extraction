/** 前端几何与格式化工具：面积口径与后端 PostGIS 的 ::geography 保持一致（同一球面公式）。 */

export const EARTH_RADIUS = 6378137
export const M2_PER_MU = 666.6666666667
export const MU_PER_M2 = 1 / M2_PER_MU

const rad = (deg) => (deg * Math.PI) / 180

function ringAreaM2(ring) {
  const coords = ring && ring.length > 3 ? ring.slice() : []
  if (coords.length < 4) return 0
  if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
    coords.push(coords[0])
  }
  let total = 0
  for (let i = 0; i < coords.length - 1; i += 1) {
    const [lon1, lat1] = coords[i]
    const [lon2, lat2] = coords[i + 1]
    total += rad(lon2 - lon1) * (2 + Math.sin(rad(lat1)) + Math.sin(rad(lat2)))
  }
  return Math.abs((total * EARTH_RADIUS * EARTH_RADIUS) / 2)
}

/** 接受 Polygon / MultiPolygon / Feature / FeatureCollection，返回平方米。 */
export function geomAreaM2(geom) {
  if (!geom || !geom.type) return 0
  if (geom.type === 'Feature') return geomAreaM2(geom.geometry)
  if (geom.type === 'FeatureCollection') return (geom.features || []).reduce((s, f) => s + geomAreaM2(f), 0)
  if (geom.type === 'MultiPolygon') return (geom.coordinates || []).reduce((s, p) => s + geomAreaM2({ type: 'Polygon', coordinates: p }), 0)
  if (geom.type !== 'Polygon') return 0
  const rings = geom.coordinates || []
  let area = ringAreaM2(rings[0])
  for (let i = 1; i < rings.length; i += 1) area -= ringAreaM2(rings[i])
  return Math.max(area, 0)
}

export const geomAreaMu = (geom) => geomAreaM2(geom) * MU_PER_M2

/** 每经/纬度约 111.319 km，经度方向按 cos(纬度) 修正。 */
export function metersPerDeg(lat) {
  const base = 111319.49079327358
  return { dLat: base, dLon: base * Math.max(Math.abs(Math.cos(rad(lat))), 0.05) }
}

/** 包围盒：[[south, west], [north, east]]，可直接喂给 Leaflet 的 fitBounds。 */
export function boundsOf(geom) {
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
  const walk = (node) => {
    if (typeof node === 'number') return
    if (Array.isArray(node)) {
      if (node.length >= 2 && typeof node[0] === 'number') {
        minx = Math.min(minx, node[0]); maxx = Math.max(maxx, node[0])
        miny = Math.min(miny, node[1]); maxy = Math.max(maxy, node[1])
      } else node.forEach(walk)
    } else if (node && node.coordinates) walk(node.coordinates)
    else if (node && node.geometry) walk(node.geometry)
    else if (node && node.features) node.features.forEach(walk)
  }
  if (geom) walk(geom)
  if (!isFinite(minx)) return null
  return [[miny, minx], [maxy, maxx]]
}

export function rectToPolygon(sw, ne) {
  const ring = [
    [sw[1], sw[0]],
    [ne[1], sw[0]],
    [ne[1], ne[0]],
    [sw[1], ne[0]],
    [sw[1], sw[0]]
  ]
  return { type: 'Polygon', coordinates: [ring] }
}

export const LAND_COLORS = {
  耕地: '#f5a623',
  园地: '#8fd14f',
  林地: '#2f9e44',
  草地: '#a0d468',
  建设用地: '#e05252',
  水域: '#3b82f6',
  未利用地: '#9ca3af',
  待认定: '#a855f7'
}

export const colorOf = (landType) => LAND_COLORS[landType] || '#4b7bec'

export const num = (value, digits = 2) => {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '0'
}

export function download(filename, content, mime = 'application/geo+json;charset=utf-8') {
  const blob = new Blob([typeof content === 'string' ? content : JSON.stringify(content, null, 2)], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export const props = (feature) => feature?.properties || feature || {}

export const featureRows = (geojson) =>
  (geojson?.features || []).map((f) => {
    const p = props(f)
    return {
      id: p.id,
      code: p.code || '—',
      name: p.name || '未命名地块',
      land_type: p.land_type || '未标注',
      region: p.region || '未标注',
      owner: p.owner || '',
      area_mu: Number(p.area_mu || 0),
      area_m2: Number(p.area_m2 || 0),
      origin: p.origin || ''
    }
  })
