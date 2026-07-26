<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, defineExpose } from 'vue'
import { save } from '@tauri-apps/plugin-dialog'
import { writeFile } from '@tauri-apps/plugin-fs'
import { open as shellOpen } from '@tauri-apps/plugin-shell'
import { api, IN_TAURI } from '../api'

// 平台中文映射（对应后端枚举）
const SOURCE_LABELS = { damai: '大麦网', maoyan: '猫眼' }

// 状态筛选 = 演出状态（与表格「状态」列同口径，按演出时间与今天比较），
// 固定四态，后端 /shows 以 perf_state 参数过滤。
const PERF_STATE_OPTIONS = [
  { value: 'upcoming', label: '未演出' },
  { value: 'ongoing', label: '演出中' },
  { value: 'done', label: '已演出' },
  { value: 'cancelled', label: '取消' },
]

// 1. 筛选条件（仅保留后端真实支持的维度）
const filters = reactive({
  keyword: '',
  source: 'all',
  city: 'all',
  category: 'all',
  status: 'all'
})

const showColumnModal = ref(false)

// 图片预览灯箱状态
const previewImage = ref('')
const previewTitle = ref('')

function openPreview(url, title) {
  const clean = cleanPosterUrl(url)
  if (!clean) return
  previewImage.value = clean
  previewTitle.value = title || ''
}
function closePreview() {
  previewImage.value = ''
  previewTitle.value = ''
}

// 海报 URL 清洗：大麦 verticalPic 常是「双拼」脏数据，形如
// https://img.alicdn.com/bao/uploaded/https://img.alicdn.com/imgextra/...jpg
// 前缀又接了一个完整 URL，取最后一个 http(s) 段即真实地址。
function cleanPosterUrl(url) {
  if (!url) return ''
  let s = String(url).trim()
  if (!s) return ''
  const idx = Math.max(s.lastIndexOf('http://'), s.lastIndexOf('https://'))
  if (idx > 0) s = s.slice(idx)
  if (s.startsWith('//')) s = 'https:' + s
  return s
}

// Toast 提示状态（success / error 两种样式）
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref('success')
let toastTimer = null

function triggerToast(msg, type = 'success') {
  toastMessage.value = msg
  toastType.value = type
  showToast.value = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    showToast.value = false
  }, type === 'error' ? 5000 : 3000)
}

// 2. 字段定义 —— 严格对齐《北京市演出信息》模板 36 列表头。
//    能从后端 Show 推导的列自动填充；剧场主数据 / 主办方 / 演艺之都分类等
//    人工富化列（enrich:true）后端不产出，表格留空待下游补齐。
const columns = ref([
  { key: 'id', title: 'id', width: '150px', visible: true },
  { key: 'seq', title: '序号', width: '70px', visible: true },
  { key: 'poster', title: '海报', width: '72px', visible: true },
  { key: 'city', title: '城市', width: '70px', visible: true },
  { key: 'venue_name', title: '原始剧场', width: '160px', visible: true },
  { key: 'norm_venue', title: '规范剧场', width: '140px', visible: true },
  { key: '', title: '场馆综合体', width: '140px', visible: true, enrich: true },
  { key: '', title: '场馆座位数', width: '100px', visible: true, enrich: true },
  { key: 'district', title: '所在区', width: '90px', visible: true },
  { key: '', title: '场馆类型（新标准）', width: '130px', visible: true, enrich: true },
  { key: '', title: '区号', width: '70px', visible: true, enrich: true },
  { key: '', title: '演艺集聚区', width: '110px', visible: true, enrich: true },
  { key: 'title', title: '原名称', width: '260px', visible: true },
  { key: 'norm_title', title: '规范剧目名称', width: '180px', visible: true },
  { key: 'start_time', title: '演出时间', width: '150px', visible: true },
  { key: 'year', title: '年份', width: '70px', visible: true },
  { key: 'month', title: '月份', width: '60px', visible: true },
  { key: 'quarter', title: '季度', width: '60px', visible: true },
  { key: 'day', title: '日', width: '55px', visible: true },
  { key: 'weekday', title: '星期', width: '80px', visible: true },
  { key: 'holiday', title: '节假日', width: '90px', visible: true },
  { key: 'troupe', title: '演出团体', width: '150px', visible: true },
  { key: 'group_city', title: '团体城市', width: '90px', visible: true },
  { key: 'hk_mo_tw', title: '港澳台', width: '80px', visible: true },
  { key: 'organizer', title: '主办方名称', width: '140px', visible: true },
  { key: 'organizer_city', title: '主办方城市', width: '90px', visible: true },
  { key: 'category', title: '演出大类', width: '110px', visible: true },
  { key: 'subcategory', title: '演出二级分类', width: '120px', visible: true },
  { key: '', title: '演出三级分类', width: '120px', visible: true, enrich: true },
  { key: '', title: '演艺之都分类', width: '120px', visible: true, enrich: true },
  { key: '', title: '类型顺序', width: '90px', visible: true, enrich: true },
  { key: 'session_count', title: '场次', width: '70px', visible: true },
  { key: 'status', title: '状态', width: '90px', visible: true },
  { key: 'troupe_attr', title: '院团属性', width: '100px', visible: true },
  { key: 'performers', title: '演员', width: '150px', visible: true },
  { key: 'price', title: '票价档', width: '180px', visible: true },
  { key: 'url', title: 'url', width: '220px', visible: true }
])

const visibleColumns = computed(() => columns.value.filter(c => c.visible))
const totalColumns = computed(() => columns.value.length)

function selectAllColumns() {
  columns.value.forEach(c => c.visible = true)
}
function invertColumns() {
  columns.value.forEach(c => c.visible = !c.visible)
}
function resetDefaultColumns() {
  columns.value.forEach(c => c.visible = true)
}

// 3. 真实数据 & 分页状态
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')
const page = ref(1)
const pageSize = ref(50)
const selectedRowIds = ref([])

// facets 下拉选项（包含从后端 SQLite 数据库 cities 主表及 shows 表提取的全量城市数据）
const facetOptions = ref({ source: [], city: [], category: [], status: [] })

const isCityExpanded = ref(false)
const citySearchQuery = ref('')

// 从后端数据库加载的全量城市数据（动态保证第一项为“全部”）
const allCityOptions = computed(() => {
  const dbCities = facetOptions.value.city || []
  const set = new Set()
  set.add('全部')
  for (const c of dbCities) {
    if (c && c !== '全部') set.add(c)
  }
  return Array.from(set)
})

// 下拉框城市列表（排除“全部”）
const dropdownCityOptions = computed(() => {
  return allCityOptions.value.filter(c => c !== '全部')
})

// 展现给用户的城市 Chip 列表（搜索时过滤；展开状态下通过 css scroll-area 滚动展现）
const visibleCityOptions = computed(() => {
  let list = allCityOptions.value
  if (citySearchQuery.value.trim()) {
    const q = citySearchQuery.value.trim().toLowerCase()
    return list.filter(c => c.toLowerCase().includes(q))
  }
  return list
})

function handleCitySelect(cityName) {
  filters.city = cityName === '全部' ? 'all' : cityName
  doSearch()
}

const totalPages = computed(() => Math.ceil(total.value / pageSize.value) || 1)

function buildQueryParams() {
  const p = {
    limit: pageSize.value,
    offset: (page.value - 1) * pageSize.value,
    sort_by: 'start_time',
    descending: true
  }
  if (filters.keyword.trim()) p.keyword = filters.keyword.trim()
  if (filters.source !== 'all') p.source = filters.source
  if (filters.city !== 'all') p.city = filters.city
  if (filters.category !== 'all') p.category = filters.category
  if (filters.status !== 'all') p.perf_state = filters.status
  return p
}

async function fetchShows() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await api.listShows(buildQueryParams())
    rows.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    errorMsg.value = e.message || '查询失败，请确认后端已启动'
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function loadFacets() {
  try {
    facetOptions.value = await api.facets()
  } catch (e) {
    console.error('加载筛选项失败:', e)
  }
}

function doSearch() {
  page.value = 1
  fetchShows()
}

function resetFilters() {
  filters.keyword = ''
  filters.source = 'all'
  filters.city = 'all'
  filters.category = 'all'
  filters.status = 'all'
  page.value = 1
  fetchShows()
}

function goPage(n) {
  if (n < 1 || n > totalPages.value) return
  page.value = n
  fetchShows()
}

function changePageSize() {
  page.value = 1
  fetchShows()
}

// 打开外部链接：Tauri 内 WebView 无法跳转，须经 shell 插件唤起系统浏览器
async function openExternalUrl(url) {
  if (!url) return

  if (IN_TAURI) {
    try {
      await shellOpen(url)
    } catch (e) {
      triggerToast(`打开链接失败：${e?.message || e}`, 'error')
    }
  } else {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

const WEEKDAYS = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']

// 剧目名称规范化：抽取标题中《》内的正式剧名，抽不到则返回原标题
function normalizeTitle(title) {
  if (!title) return ''
  const m = String(title).match(/《[^》]+》/)
  return m ? m[0] : title
}

// 演出团体 / 演员：取 artists，去掉「艺人：」前缀
function formatArtists(artists) {
  if (!Array.isArray(artists) || artists.length === 0) return ''
  return artists
    .map(a => String(a).replace(/^艺人[：:]\s*/, '').trim())
    .filter(Boolean)
    .join('、')
}

// 单元格取值。key 为空串的列（剧场主数据 / 主办方 / 演艺之都分类等人工富化列）
// 后端不产出，一律返回空串，供下游台账补齐。
// row 与其在当前页的序号 idx（1 起）共同决定取值。
function cellValue(row, key, idx) {
  const dt = parseRowTime(row.start_time)
  switch (key) {
    case 'id': return row.id || ''
    case 'seq': return (page.value - 1) * pageSize.value + idx
    case 'city': return row.venue?.city || ''
    case 'venue_name': return row.venue?.name || ''
    case 'norm_venue': return row.extras?.norm_venue || row.venue?.name || ''
    case 'district': return row.extras?.district || ''
    case 'title': return row.title || ''
    case 'norm_title': return normalizeTitle(row.title)
    case 'start_time': return formatTime(row.start_time)
    case 'year': return dt ? dt.getFullYear() : ''
    case 'month': return dt ? dt.getMonth() + 1 : ''
    case 'quarter': return dt ? `Q${Math.floor(dt.getMonth() / 3) + 1}` : ''
    case 'day': return dt ? dt.getDate() : ''
    case 'weekday': return dt ? WEEKDAYS[(dt.getDay() + 6) % 7] : ''
    case 'holiday': return row.holiday || ''
    case 'troupe': return row.extras?.troupe || (row.artists && row.artists[0]) || ''
    case 'group_city': return row.extras?.group_city || row.venue?.city || ''
    case 'hk_mo_tw': return row.extras?.hk_mo_tw || ''
    case 'organizer': return row.extras?.organizer || ''
    case 'organizer_city': return row.extras?.organizer_city || row.venue?.city || ''
    case 'artists': return formatArtists(row.artists)
    case 'performers': return formatPerformers(row)
    case 'category': return row.category || ''
    case 'subcategory': return row.extras?.subcategory || ''
    case 'session_count': return Array.isArray(row.sessions) ? row.sessions.length : 0
    case 'status': return row.perf_state || ''
    case 'troupe_attr': return row.extras?.troupe_attr || ''
    case 'price': return formatPriceLadder(row)
    case 'url': return row.url || ''
    default: return '' // enrich 列（key 为空串）留空
  }
}

function formatPerformers(row) {
  const list = row.extras?.performers
  if (Array.isArray(list) && list.length) return list.filter(Boolean).join('、')
  return formatArtists(row.artists)
}

// 演出时间字符串 → Date（用于派生 年/月/季度/日/星期）
function parseRowTime(t) {
  if (!t) return null
  const d = new Date(String(t))
  return isNaN(d.getTime()) ? null : d
}

function fmtPriceNum(p) {
  if (typeof p !== 'number' || Number.isNaN(p)) return ''
  return Number.isInteger(p) ? String(p) : String(p)
}

/**
 * 全部票档价格：80|180|280（升序去重）。
 * 优先 sessions.ticket_tiers；其次 price.raw 已是 ladder；再回退 min|max。
 */
function formatPriceLadder(row) {
  const nums = []
  for (const s of row.sessions || []) {
    for (const t of s.ticket_tiers || []) {
      if (typeof t.price === 'number' && !Number.isNaN(t.price)) {
        nums.push(t.price)
      }
    }
  }
  if (nums.length > 0) {
    const uniq = [...new Set(nums)].sort((a, b) => a - b)
    return uniq.map(fmtPriceNum).join('|')
  }
  const price = row.price || {}
  const raw = String(price.raw || row.extras?.price_ladder || '').trim()
  if (raw.includes('|')) {
    return raw
  }
  // 从 80-1080 / 80.00-1080.00 拆不出中间档，只能 min|max
  if (price.min_price != null && price.max_price != null) {
    if (price.min_price === price.max_price) return fmtPriceNum(price.min_price)
    return `${fmtPriceNum(price.min_price)}|${fmtPriceNum(price.max_price)}`
  }
  if (price.min_price != null) return fmtPriceNum(price.min_price)
  return raw
}

function formatTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 16)
}

// 演出状态 → 徽标样式类：未演出=蓝(待映)，演出中=绿(进行,脉动)，已演出=灰(结束)，取消=红
function statusClass(state) {
  if (state === '演出中') return 'ongoing'
  if (state === '未演出') return 'upcoming'
  if (state === '取消') return 'cancelled'
  if (state === '已演出') return 'done'
  return 'unknown'
}

// 选择逻辑
const isAllSelected = computed(() => {
  return rows.value.length > 0 && rows.value.every(r => selectedRowIds.value.includes(r.id))
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    rows.value.forEach(r => {
      const idx = selectedRowIds.value.indexOf(r.id)
      if (idx > -1) selectedRowIds.value.splice(idx, 1)
    })
  } else {
    rows.value.forEach(r => {
      if (!selectedRowIds.value.includes(r.id)) selectedRowIds.value.push(r.id)
    })
  }
}

// 导出 Modal 控制
const showExportModal = ref(false)

function handleExportClick() {
  showExportModal.value = true
}

// 清除数据 Modal 控制
const showClearModal = ref(false)
const clearing = ref(false)

async function executeClear(scope) {
  showClearModal.value = false
  clearing.value = true

  // 与导出一致：selected 走勾选 ids，filtered 走当前筛选，all 整库清空
  const payload = { scope }
  if (scope === 'selected') {
    payload.ids = selectedRowIds.value.join(',')
  } else if (scope === 'filtered') {
    if (filters.keyword.trim()) payload.keyword = filters.keyword.trim()
    if (filters.source !== 'all') payload.source = filters.source
    if (filters.city !== 'all') payload.city = filters.city
    if (filters.category !== 'all') payload.category = filters.category
    if (filters.status !== 'all') payload.perf_state = filters.status
  }

  try {
    const res = await api.clearData(payload)
    const d = res?.deleted || {}
    const n = (d.shows || 0)
    triggerToast(`已清除 ${n} 条演出数据`)
    // 清空后刷新列表与筛选项
    selectedRowIds.value = []
    await fetchShows()
    await loadFacets()
  } catch (e) {
    triggerToast(`清除失败：${e?.message || e}`, 'error')
  } finally {
    clearing.value = false
  }
}

async function executeExport(scope) {
  showExportModal.value = false
  const selectedCount = selectedRowIds.value.length
  const p = {}

  if (scope === 'selected' && selectedCount > 0) {
    p.ids = selectedRowIds.value.join(',')
  } else {
    if (filters.keyword.trim()) p.keyword = filters.keyword.trim()
    if (filters.source !== 'all') p.source = filters.source
    if (filters.city !== 'all') p.city = filters.city
    if (filters.category !== 'all') p.category = filters.category
    if (filters.status !== 'all') p.perf_state = filters.status
  }

  const url = api.exportUrl('xlsx', p)
  const scopeText = scope === 'selected' && selectedCount > 0
    ? `勾选的 ${selectedCount} 条`
    : `筛选的全部 ${total.value} 条`

  // 浏览器（vite dev）环境：交给浏览器处理 Content-Disposition 下载
  if (!IN_TAURI) {
    window.open(url, '_blank')
    triggerToast(`已开始下载${scopeText}演出数据`)
    return
  }

  // Tauri 桌面壳：WebView 不支持网页下载，走系统保存对话框后写盘
  try {
    const day = new Date().toISOString().slice(0, 10)
    const path = await save({
      title: '导出演出数据',
      defaultPath: `演出数据_${day}.xlsx`,
      filters: [{ name: 'Excel 工作簿', extensions: ['xlsx'] }],
    })
    if (!path) return // 用户取消保存

    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`导出接口返回 HTTP ${resp.status}`)
    const bytes = new Uint8Array(await resp.arrayBuffer())
    await writeFile(path, bytes)
    triggerToast(`导出成功！${scopeText}演出数据已保存`)
  } catch (e) {
    triggerToast(`导出失败：${e?.message || e}`, 'error')
  }
}

function onKeydown(e) {
  if (e.key === 'Escape' && previewImage.value) closePreview()
}

onMounted(() => {
  loadFacets()
  fetchShows()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

async function refresh() {
  await Promise.all([loadFacets(), fetchShows()])
}

// 手动刷新：转圈至少 600ms 让 loading 可感知，结束后按结果提示。
// fetchShows 内部不抛错（错误落在 errorMsg），须以 errorMsg 判定成败。
const refreshing = ref(false)

async function handleRefresh() {
  if (refreshing.value) return
  refreshing.value = true
  const minSpin = new Promise(resolve => setTimeout(resolve, 600))
  try {
    await Promise.all([refresh(), minSpin])
    if (errorMsg.value) {
      triggerToast(`刷新失败：${errorMsg.value}`, 'error')
    } else {
      triggerToast('✓ 已刷新最新数据')
    }
  } catch (e) {
    await minSpin
    triggerToast(`刷新失败：${e?.message || e}`, 'error')
  } finally {
    refreshing.value = false
  }
}

defineExpose({ refresh, fetchShows, loadFacets })
</script>

<template>
  <div class="shows-view">

    <!-- Toast 浮动提示通知栏 -->
    <transition name="toast-fade">
      <div v-if="showToast" class="toast-notification" :class="toastType">
        <div class="toast-icon">{{ toastType === 'error' ? '✕' : '✓' }}</div>
        <span class="toast-text">{{ toastMessage }}</span>
      </div>
    </transition>

    <!-- 图1/图2 经典大麦城市筛选展示卡片 -->
    <div class="city-picker-card">
      <div class="active-city-header">
        <div class="active-city-header-left">
          <span class="active-city-title">当前选中城市</span>
          <span class="active-city-badge">
            {{ filters.city === 'all' ? '全部' : filters.city }}
          </span>
        </div>

        <!-- 展开模式下的快速查找城市搜索框 -->
        <div v-if="isCityExpanded" class="city-search-box">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="city-search-icon"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input
            type="text"
            v-model="citySearchQuery"
            placeholder="搜索城市..."
            class="city-search-input"
          />
          <button v-if="citySearchQuery" class="clear-city-search" @click="citySearchQuery = ''">✕</button>
        </div>
      </div>

      <div class="city-grid-container" :class="{ expanded: isCityExpanded }">
        <div class="city-scroll-area" :class="{ expanded: isCityExpanded }">
          <div class="city-chips-list">
            <button
              v-for="c in visibleCityOptions"
              :key="c"
              class="city-chip-btn"
              :class="{ active: (c === '全部' && filters.city === 'all') || filters.city === c }"
              @click="handleCitySelect(c)"
            >
              {{ c }}
            </button>
            <div v-if="visibleCityOptions.length === 0" class="no-city-match">
              未找到匹配城市
            </div>
          </div>
        </div>

        <button class="expand-toggle-btn" @click="isCityExpanded = !isCityExpanded">
          <span>{{ isCityExpanded ? '收起' : '更多' }}</span>
          <svg v-if="isCityExpanded" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="18 15 12 9 6 15"/></svg>
          <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
      </div>
    </div>

    <!-- 顶部 Filter 综合筛选栏（全部元素单行开阔并排） -->
    <div class="filter-card">
      <div class="filter-row">
         <button class="btn-icon-refresh" :disabled="refreshing || loading" title="刷新数据" @click="handleRefresh">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" :class="{ 'icon-spin': refreshing || loading }"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
          </button>
        <!-- 1. 列显示设置 按钮 -->
        <button class="tool-btn" @click="showColumnModal = true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7m0-18H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7m0-18v18"/></svg>
          列显示
        </button>

        <!-- 2. 导出 Excel 按钮 -->
        <button class="tool-btn export" @click="handleExportClick">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          导出
        </button>

        <!-- 3. 清除数据 按钮 -->
        <button class="tool-btn danger" :disabled="clearing" @click="showClearModal = true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          清除数据
        </button>

        <div class="filter-divider"></div>

        <!-- 3. 关键词 -->
        <div class="filter-item keyword-item">
          <span class="field-label">关键词</span>
          <div class="search-input-wrap">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="search-icon"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input
              type="text"
              v-model="filters.keyword"
              placeholder="剧目名称"
              class="search-input"
              @keyup.enter="doSearch"
            />
          </div>
        </div>

        <!-- 4. 平台 -->
        <div class="filter-item">
          <span class="field-label">平台</span>
          <select v-model="filters.source" class="filter-select">
            <option value="all">全部平台</option>
            <option v-for="s in facetOptions.source" :key="s" :value="s">
              {{ SOURCE_LABELS[s] || s }}
            </option>
          </select>
        </div>
        <!-- 6. 分类 -->
        <div class="filter-item">
          <span class="field-label">分类</span>
          <select v-model="filters.category" class="filter-select">
            <option value="all">全部分类</option>
            <option v-for="cat in facetOptions.category" :key="cat" :value="cat">{{ cat }}</option>
          </select>
        </div>

        <!-- 7. 状态（演出状态，与表格「状态」列同口径） -->
        <div class="filter-item">
          <span class="field-label">状态</span>
          <select v-model="filters.status" class="filter-select">
            <option value="all">全部状态</option>
            <option v-for="o in PERF_STATE_OPTIONS" :key="o.value" :value="o.value">
              {{ o.label }}
            </option>
          </select>
        </div>

        <!-- 8. 查询 & 重置 & 刷新 按钮 -->
        <div class="filter-actions">
          <button class="btn-search" @click="doSearch">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            查询
          </button>
          <button class="btn-reset-filter" @click="resetFilters">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            重置
          </button>
         
        </div>
      </div>
    </div>

    <!-- 超宽数据表格 Wide Data Grid -->
    <div class="grid-card">
      <!-- 刷新已有数据时的半透明加载遮罩 -->
      <div v-if="(loading || refreshing) && rows.length > 0" class="table-loading-overlay">
        <div class="loading-pill">
          <span class="loading-spinner"></span>
          <span>正在刷新数据…</span>
        </div>
      </div>
      <div class="grid-table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th class="col-chk">
                <input type="checkbox" :checked="isAllSelected" @change="toggleSelectAll" />
              </th>
              <th
                v-for="(col, ci) in visibleColumns"
                :key="ci"
                :style="{ width: col.width, minWidth: col.width }"
              >
                <div class="th-content">
                  <span class="th-text">{{ col.title }}</span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && rows.length === 0">
              <td :colspan="visibleColumns.length + 1" class="empty-cell">
                <span class="loading-inline"><span class="loading-spinner small"></span> 正在加载数据…</span>
              </td>
            </tr>
            <tr v-else-if="!loading && rows.length === 0">
              <td :colspan="visibleColumns.length + 1" class="empty-cell" :class="{ 'error-cell': errorMsg }">
                {{ errorMsg || '暂无数据，请先在「数据采集」页启动采集' }}
              </td>
            </tr>
            <tr v-for="(row, rowIndex) in rows" :key="row.id" :class="{ selected: selectedRowIds.includes(row.id) }">
              <td class="col-chk">
                <input type="checkbox" :value="row.id" v-model="selectedRowIds" />
              </td>
              <td v-for="col in visibleColumns" :key="col.title" class="td-cell">
                <!-- 海报缩略图：点击放大预览 -->
                <template v-if="col.key === 'poster'">
                  <img
                    v-if="cleanPosterUrl(row.poster_url)"
                    :src="cleanPosterUrl(row.poster_url)"
                    class="poster-thumb"
                    loading="lazy"
                    referrerpolicy="no-referrer"
                    :alt="row.title"
                    @click.stop="openPreview(row.poster_url, row.title)"
                  />
                  <span v-else class="poster-empty">—</span>
                </template>

                <!-- 状态 Badge：演出状态（按演出时间与今天比较） -->
                <template v-else-if="col.key === 'status'">
                  <span v-if="row.perf_state" class="state-badge" :class="statusClass(row.perf_state)">
                    <span class="state-dot"></span>{{ row.perf_state }}
                  </span>
                  <span v-else>-</span>
                </template>

                <!-- URL 链接：点击统一由 openExternalUrl 处理（Tauri 内唤起系统浏览器），
                     保留 href 以便悬停预览/右键复制，prevent 阻止 WebView 内导航 -->
                <template v-else-if="col.key === 'url'">
                  <a
                    v-if="row.url"
                    :href="row.url"
                    class="url-link"
                    @click.stop.prevent="openExternalUrl(row.url)"
                    :title="row.url"
                  >
                    <span class="url-text">{{ row.url }}</span>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide-ext-link">
                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                      <polyline points="15 3 21 3 21 9"></polyline>
                      <line x1="10" y1="14" x2="21" y2="3"></line>
                    </svg>
                  </a>
                  <span v-else>-</span>
                </template>

                <!-- 默认文字 -->
                <template v-else>
                  {{ cellValue(row, col.key, rowIndex + 1) }}
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 底部 Footer Page Control Bar -->
      <div class="table-footer">
        <div class="footer-stat">
          当前显示 <strong>{{ total === 0 ? 0 : (page - 1) * pageSize + 1 }}-{{ Math.min(page * pageSize, total) }}</strong> / 共 <strong>{{ total }}</strong> 条 · 字段 <strong>{{ visibleColumns.length }}/{{ totalColumns }}</strong> 列
        </div>

        <div class="footer-pagination">
          <span class="page-label">每页</span>
          <select v-model.number="pageSize" @change="changePageSize" class="page-select">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>

          <div class="page-nav">
            <button class="nav-btn" :disabled="page <= 1" @click="goPage(page - 1)">&lt;</button>
            <span class="page-curr"><strong>{{ page }}</strong> / {{ totalPages }}</span>
            <button class="nav-btn" :disabled="page >= totalPages" @click="goPage(page + 1)">&gt;</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal 弹窗 -->
    <div class="modal-overlay" v-if="showColumnModal" @click.self="showColumnModal = false">
      <div class="modal-card column-two-col-modal">
        <div class="modal-header">
          <div class="header-left">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.5"><path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7m0-18H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7m0-18v18"/></svg>
            <h3>列显示与隐藏设置</h3>
            <span class="visible-badge">显示 {{ visibleColumns.length }} / {{ totalColumns }} 列</span>
          </div>
          <button class="close-btn" @click="showColumnModal = false">✕</button>
        </div>

        <!-- 快捷操作栏 -->
        <div class="modal-sub-bar">
          <div class="quick-btns">
            <button class="btn-sub" @click="selectAllColumns">全选所有字段</button>
            <button class="btn-sub" @click="invertColumns">反选</button>
            <button class="btn-sub outline" @click="resetDefaultColumns">重置默认</button>
          </div>
          <span class="hint-text">💡 勾选决定表格是否展示该数据列</span>
        </div>

        <!-- scroll-area 滚动区域 (不分类，2列卡片网格) -->
        <div class="scroll-area">
          <div class="two-col-grid">
            <label
              v-for="col in columns"
              :key="col.key"
              class="tile-card"
              :class="{ active: col.visible }"
            >
              <input type="checkbox" v-model="col.visible" class="custom-checkbox" />
              <span class="col-title">{{ col.title }}</span>
              <span class="col-key">({{ col.key }})</span>
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <div class="footer-left-info">
            显示状态：已有 {{ visibleColumns.length }} 个字段勾选生效
          </div>
          <div class="footer-right-btns">
            <button class="btn-cancel" @click="showColumnModal = false">关闭</button>
            <button class="btn-confirm" @click="showColumnModal = false">保存当前配置</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 极简导出选择确认 Modal -->
    <div class="modal-overlay" v-if="showExportModal" @click.self="showExportModal = false">
      <div class="modal-card export-simple-modal">
        <div class="modal-header">
          <div class="header-left">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <h3>数据导出确认</h3>
          </div>
          <button class="close-btn" @click="showExportModal = false">✕</button>
        </div>

        <div class="export-simple-body">
          <div class="export-single-text">
            <template v-if="selectedRowIds.length > 0">
              您当前勾选了 <strong class="count-pink">{{ selectedRowIds.length }}</strong> 条记录，包含筛选共 <strong class="count-blue">{{ total }}</strong> 条，请选择导出的范围：
            </template>
            <template v-else>
              符合当前筛选条件的演出数据共 <strong class="count-blue">{{ total }}</strong> 条，确认导出 Excel 文件吗？
            </template>
          </div>
        </div>

        <div class="modal-footer simple-footer">
          <button class="btn-cancel" @click="showExportModal = false">取消</button>
          <div class="right-btn-group">
            <button 
              v-if="selectedRowIds.length > 0"
              class="btn-export-action primary"
              @click="executeExport('selected')"
            >
              导出勾选的 {{ selectedRowIds.length }} 条
            </button>
            <button 
              class="btn-export-action outline"
              @click="executeExport('all')"
            >
              导出全部 {{ total }} 条
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 清除数据确认 Modal -->
    <div class="modal-overlay" v-if="showClearModal" @click.self="showClearModal = false">
      <div class="modal-card export-simple-modal">
        <div class="modal-header">
          <div class="header-left">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#e5484d" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            <h3>清除数据确认</h3>
          </div>
          <button class="close-btn" @click="showClearModal = false">✕</button>
        </div>

        <div class="export-simple-body">
          <div class="export-single-text">
            <template v-if="selectedRowIds.length > 0">
              您当前勾选了 <strong class="count-pink">{{ selectedRowIds.length }}</strong> 条记录，包含筛选共 <strong class="count-blue">{{ total }}</strong> 条，请选择清除的范围：
            </template>
            <template v-else>
              符合当前筛选条件的演出数据共 <strong class="count-blue">{{ total }}</strong> 条，请选择清除的范围：
            </template>
            <br /><br />
            清除会连带删除对应的原始记录，此操作不可撤销、清除后需重新采集。城市预设和系统设置会保留。
          </div>
        </div>

        <div class="modal-footer simple-footer">
          <button class="btn-cancel" @click="showClearModal = false">取消</button>
          <div class="right-btn-group">
            <button
              v-if="selectedRowIds.length > 0"
              class="btn-export-action danger"
              :disabled="clearing"
              @click="executeClear('selected')"
            >
              清除勾选的 {{ selectedRowIds.length }} 条
            </button>
            <button
              class="btn-export-action danger-outline"
              :disabled="clearing"
              @click="executeClear('filtered')"
            >
              清除筛选的 {{ total }} 条
            </button>
            <button
              class="btn-export-action danger-outline"
              :disabled="clearing"
              @click="executeClear('all')"
            >
              清除全部
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 海报图片预览灯箱 -->
    <transition name="preview-fade">
      <div v-if="previewImage" class="preview-overlay" @click.self="closePreview">
        <div class="preview-box">
          <button class="preview-close" @click="closePreview">✕</button>
          <img :src="previewImage" :alt="previewTitle" class="preview-img" />
          <div v-if="previewTitle" class="preview-caption">{{ previewTitle }}</div>
        </div>
      </div>
    </transition>

  </div>
</template>

<style scoped>
/* 海报缩略图（表格内） */
.poster-thumb {
  width: 44px;
  height: 60px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
  cursor: zoom-in;
  display: block;
  background: #f1f5f9;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.poster-thumb:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}
.poster-empty {
  color: #cbd5e1;
  font-size: 12px;
}

/* 海报预览灯箱 */
.preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
  cursor: zoom-out;
}
.preview-box {
  position: relative;
  max-width: 82vw;
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.preview-img {
  max-width: 82vw;
  max-height: 78vh;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 20px 50px -10px rgba(0, 0, 0, 0.6);
  background: #ffffff;
}
.preview-caption {
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  max-width: 80vw;
  text-align: center;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
}
.preview-close {
  position: absolute;
  top: -14px;
  right: -14px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: #ffffff;
  color: #0f172a;
  font-size: 16px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-close:hover {
  background: #f1f5f9;
}
.preview-fade-enter-active,
.preview-fade-leave-active {
  transition: opacity 0.2s ease;
}
.preview-fade-enter-from,
.preview-fade-leave-to {
  opacity: 0;
}

/* 图1/图2 经典大麦城市筛选展示卡片 */
.city-picker-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  padding: 14px 18px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.active-city-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.active-city-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.active-city-title {
  font-size: 13.5px;
  color: #94a3b8;
  font-weight: 500;
}

.active-city-badge {
  background: var(--primary, #eb4f9a);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  line-height: 1.4;
}

.city-search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.city-search-icon {
  position: absolute;
  left: 8px;
  color: #94a3b8;
  pointer-events: none;
}

.city-search-input {
  height: 26px;
  padding: 0 22px 0 26px;
  border: 1px solid #cbd5e1;
  border-radius: 13px;
  font-size: 12px;
  color: #334155;
  outline: none;
  width: 160px;
  transition: all 0.2s ease;
}

.city-search-input:focus {
  border-color: var(--primary, #eb4f9a);
  box-shadow: 0 0 0 2px var(--primary-light, rgba(235, 79, 154, 0.15));
  width: 200px;
}

.clear-city-search {
  position: absolute;
  right: 6px;
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 11px;
  cursor: pointer;
  padding: 2px;
}
.clear-city-search:hover {
  color: #334155;
}

.no-city-match {
  font-size: 12px;
  color: #94a3b8;
  padding: 4px 0;
  font-style: italic;
}

.city-grid-container {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.city-scroll-area {
  flex: 1;
  max-height: 52px;
  overflow: hidden;
  transition: max-height 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.city-scroll-area.expanded {
  max-height: 180px;
  overflow-y: auto;
  padding-right: 6px;
}

/* 定制的滚动条 */
.city-scroll-area.expanded::-webkit-scrollbar {
  width: 6px;
}
.city-scroll-area.expanded::-webkit-scrollbar-track {
  background: #f1f5f9;
  border-radius: 3px;
}
.city-scroll-area.expanded::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}
.city-scroll-area.expanded::-webkit-scrollbar-thumb:hover {
  background: var(--primary, #eb4f9a);
}

.city-chips-list {
  display: flex;
  flex-wrap: wrap;
  row-gap: 10px;
  column-gap: 24px;
  align-items: center;
}

.city-chip-btn {
  background: transparent;
  border: none;
  font-size: 13.5px;
  color: #334155;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
  transition: all 0.15s ease;
  line-height: 1.2;
}

.city-chip-btn:hover {
  color: var(--primary, #eb4f9a);
}

.city-chip-btn.active {
  background: var(--primary, #eb4f9a);
  color: #ffffff !important;
  font-weight: 600;
}

.expand-toggle-btn {
  background: transparent;
  border: none;
  font-size: 13px;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.expand-toggle-btn:hover {
  color: var(--primary, #eb4f9a);
}

/* Toast 提示 */
.toast-notification {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #0f172a;
  color: #ffffff;
  padding: 10px 20px;
  border-radius: 30px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(255, 255, 255, 0.1);
  z-index: 1000;
  font-size: 13px;
  font-weight: 600;
}

.toast-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #10b981;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: bold;
}

.toast-notification.error .toast-icon {
  background: #ef4444;
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -20px);
}

.shows-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  overflow: hidden;
  padding: 8px;
  gap: 8px;
  background-color: #f1f5f9;
}

/* 顶部 Filter 卡片 */
.filter-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  padding: 8px 14px;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  flex-wrap: nowrap;
}

.filter-divider {
  width: 1px;
  height: 18px;
  background-color: #cbd5e1;
  margin: 0 2px;
  flex-shrink: 0;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.field-label {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
  white-space: nowrap;
}

.keyword-item {
  flex: 1.2;
  min-width: 220px;
}

.search-input-wrap {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 8px;
  color: var(--primary);
}

.search-input {
  width: 100%;
  padding-left: 28px !important;
}

.filter-select {
  height: 28px;
  min-width: 90px;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.btn-search {
  background: var(--primary);
  color: #ffffff;
  border: none;
  border-radius: 6px;
  height: 28px;
  padding: 0 18px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 2px 6px var(--primary-shadow);
  transition: all 0.2s;
}
.btn-search:hover {
  background: var(--primary-hover);
  transform: translateY(-1px);
}

.btn-reset-filter {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  height: 28px;
  padding: 0 12px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}
.btn-reset-filter:hover {
  background: var(--primary-light);
  border-color: var(--primary-border);
  color: var(--primary);
}

.btn-icon-refresh {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  height: 28px;
  width: 28px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-icon-refresh:hover:not(:disabled) {
  background: var(--primary-light);
  border-color: var(--primary-border);
  color: var(--primary);
}
.btn-icon-refresh:active:not(:disabled) {
  transform: scale(0.92);
}
.btn-icon-refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.icon-spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.tool-btn {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  height: 28px;
  padding: 0 10px;
  font-size: 11px;
  color: #334155;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}
.tool-btn:hover {
  background: var(--primary-light);
  border-color: var(--primary-border);
  color: var(--primary);
}
.tool-btn.danger {
  color: #e5484d;
  border-color: #f3c7c8;
}
.tool-btn.danger:hover {
  background: #fef2f2;
  border-color: #e5484d;
  color: #c93a3e;
}
.tool-btn.danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Wide Data Grid Card */
.grid-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  position: relative;
}

.grid-table-container {
  flex: 1;
  overflow: auto;
}

/* 刷新已有数据时：盖住表格区的半透明遮罩 + 转圈胶囊 */
.table-loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(1px);
  z-index: 30;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 80px;
}
.loading-pill {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid var(--primary-border);
  border-radius: 20px;
  padding: 8px 18px;
  font-size: 13px;
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
}

.loading-spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 3px solid var(--primary-light);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
.loading-spinner.small {
  width: 13px;
  height: 13px;
  border-width: 2px;
}

.loading-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--primary);
  font-weight: 600;
}

.error-cell {
  color: #b91c1c !important;
}

.data-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

/* 表格 Header - var(--primary) 纯色与白色文字 */
.data-table th {
  background: var(--primary);
  color: #ffffff;
  padding: 9px 12px;
  font-weight: 700;
  text-align: left;
  border-right: 1px solid rgba(255, 255, 255, 0.25);
  position: sticky;
  top: 0;
  z-index: 10;
  user-select: none;
  white-space: nowrap !important;
  word-break: keep-all !important;
}

.th-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  white-space: nowrap !important;
  word-break: keep-all !important;
}

.th-text {
  white-space: nowrap !important;
  word-break: keep-all !important;
  display: inline-block;
}

.col-chk {
  width: 38px;
  text-align: center !important;
}

.data-table td {
  padding: 7px 10px;
  border-bottom: 1px solid #f1f5f9;
  border-right: 1px solid #f1f5f9;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.data-table tr:hover {
  background-color: var(--primary-light-bg);
}
.data-table tr.selected {
  background-color: var(--primary-light);
}

.empty-cell {
  text-align: center !important;
  color: #94a3b8;
  padding: 40px 0 !important;
  font-size: 13px;
}

.table-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}
.table-badge.success { background: #ecfdf5; color: #047857; }
.table-badge.danger { background: #fef2f2; color: #b91c1c; }
.table-badge.warning { background: #fffbe6; color: #d97706; }

/* 演出状态徽标：未演出(蓝)/演出中(绿·脉动)/已演出(灰)/取消(红) */
.state-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.state-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: currentColor;
}
/* 未演出：待开演，蓝 */
.state-badge.upcoming { background: #eff6ff; color: #2563eb; }
/* 演出中：今天，绿 + 呼吸动画 */
.state-badge.ongoing { background: #ecfdf5; color: #047857; }
.state-badge.ongoing .state-dot { animation: state-pulse 1.4s ease-in-out infinite; }
/* 已演出：灰 */
.state-badge.done { background: #f1f5f9; color: #64748b; }
/* 取消：红 */
.state-badge.cancelled { background: #fef2f2; color: #b91c1c; }

.state-empty { color: #cbd5e1; }

@keyframes state-pulse {
  0%, 100% { opacity: 1; transform: scale(1); box-shadow: 0 0 0 0 currentColor; }
  50% { opacity: 0.55; transform: scale(1.25); }
}

.url-link {
  color: var(--primary);
  font-family: monospace;
  font-size: 11px;
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.url-link:hover {
  color: var(--primary-hover);
}
.lucide-ext-link {
  flex-shrink: 0;
  color: var(--primary);
  opacity: 0.85;
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.url-link:hover .lucide-ext-link {
  opacity: 1;
  transform: translate(1px, -1px);
}

/* Footer Page Control Bar */
.table-footer {
  height: 36px;
  border-top: 1px solid #e2e8f0;
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  font-size: 11px;
  color: #64748b;
  flex-shrink: 0;
}

.footer-pagination {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-select {
  height: 24px;
  padding: 0 4px;
  font-size: 11px;
}

.page-nav {
  display: flex;
  align-items: center;
  gap: 6px;
}

.nav-btn {
  width: 24px;
  height: 24px;
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.nav-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}
.nav-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Modal 遮罩层 */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

/* Modal 卡片通用基类 */
.modal-card {
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 两列显示 Modal 弹窗 */
.column-two-col-modal {
  width: 620px;
  max-height: 85vh;
}

.modal-header {
  padding: 14px 20px;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--primary-light-bg);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.modal-header h3 {
  font-size: 15px;
  color: var(--primary);
  font-weight: 700;
  margin: 0;
}

.visible-badge {
  font-size: 11px;
  background: var(--primary);
  color: #ffffff;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.close-btn {
  background: transparent;
  border: none;
  font-size: 16px;
  color: #94a3b8;
  cursor: pointer;
}
.close-btn:hover { color: var(--primary); }

.modal-sub-bar {
  padding: 10px 20px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.quick-btns {
  display: flex;
  gap: 8px;
}

.btn-sub {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 11.5px;
  color: #334155;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s;
}
.btn-sub:hover {
  background: var(--primary-light);
  border-color: var(--primary-border);
  color: var(--primary);
}

.btn-sub.outline {
  color: #64748b;
}

.hint-text {
  font-size: 11px;
  color: #64748b;
}

/* scroll-area 自定义滚动区域 */
.scroll-area {
  padding: 16px 20px;
  max-height: 420px;
  overflow-y: auto;
  background: #ffffff;
}

/* 2 列平铺 Cards Grid */
.two-col-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.tile-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease-in-out;
  user-select: none;
}

.tile-card:hover {
  border-color: var(--primary-border);
  background: var(--primary-light-bg);
}

.tile-card.active {
  background: var(--primary-light);
  border-color: var(--primary);
  box-shadow: 0 2px 4px var(--primary-shadow);
}

.custom-checkbox {
  width: 17px;
  height: 17px;
  accent-color: var(--primary);
  cursor: pointer;
  flex-shrink: 0;
}

.col-title {
  font-size: 12.5px;
  font-weight: 700;
  color: #1e293b;
}

.col-key {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
}

.footer-left-info {
  font-size: 12px;
  color: #475569;
}

.footer-right-btns {
  display: flex;
  gap: 10px;
}

.btn-cancel {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 12px;
  color: #475569;
  cursor: pointer;
}

.btn-confirm {
  background: var(--primary);
  border: none;
  color: #ffffff;
  padding: 6px 20px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 2px 6px var(--primary-shadow);
}

/* 极简导出确认 Modal 专属样式 */
.export-simple-modal {
  width: 480px;
  max-width: 90vw;
  background: #ffffff !important;
  border: 1px solid #cbd5e1;
}

.export-simple-body {
  padding: 24px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  background: #ffffff;
}

.export-icon-circle {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--primary-light-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--primary-border);
}

.export-single-text {
  font-size: 13.5px;
  line-height: 1.6;
  color: #334155;
  font-weight: 500;
}

.count-pink {
  color: var(--primary);
  font-weight: 800;
  font-size: 15px;
}

.count-blue {
  color: #2563eb;
  font-weight: 800;
  font-size: 15px;
}

.simple-footer {
  padding: 12px 20px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.right-btn-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-export-action {
  height: 32px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-export-action.primary {
  background: var(--primary);
  color: #ffffff;
  border: none;
  box-shadow: 0 2px 6px var(--primary-shadow);
}
.btn-export-action.primary:hover {
  background: var(--primary-hover);
}

.btn-export-action.outline {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
}
.btn-export-action.outline:hover {
  border-color: #3b82f6;
  color: #2563eb;
  background: #eff6ff;
}

.btn-export-action.danger {
  background: #e5484d;
  color: #ffffff;
  border: none;
  box-shadow: 0 2px 6px rgba(229, 72, 77, 0.3);
}
.btn-export-action.danger:hover {
  background: #c93a3e;
}
.btn-export-action.danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-export-action.danger-outline {
  background: #ffffff;
  border: 1px solid #f1b5b7;
  color: #c93a3e;
}
.btn-export-action.danger-outline:hover {
  border-color: #e5484d;
  background: #fef2f2;
}
.btn-export-action.danger-outline:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
