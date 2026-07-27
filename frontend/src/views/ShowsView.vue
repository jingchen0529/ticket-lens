<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, defineExpose } from 'vue'
import { save } from '@tauri-apps/plugin-dialog'
import { writeFile } from '@tauri-apps/plugin-fs'
import { open as shellOpen } from '@tauri-apps/plugin-shell'
import { api, IN_TAURI } from '../api'

// 引入 shadcn-ui 核心组件
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Field, FieldLabel, FieldDescription } from '@/components/ui/field'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableCell,
  TableHead,
  TableEmpty,
} from '@/components/ui/table'
import {
  Pagination,
  PaginationList,
  PaginationPrev,
  PaginationNext,
  PaginationFirst,
  PaginationLast,
} from '@/components/ui/pagination'

// 引入 custom 目录下抽取的公共 Modal 业务组件
import ColumnConfigModal from '@/components/custom/ColumnConfigModal.vue'
import ExportModal from '@/components/custom/ExportModal.vue'
import ClearDataModal from '@/components/custom/ClearDataModal.vue'
import ShowDetailModal from '@/components/custom/ShowDetailModal.vue'
import ShowEditModal from '@/components/custom/ShowEditModal.vue'
import SingleDeleteModal from '@/components/custom/SingleDeleteModal.vue'
import ImagePreviewModal from '@/components/custom/ImagePreviewModal.vue'

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

function statusBadgeVariant(state) {
  if (state === '未演出' || state === 'upcoming') return 'default'
  if (state === '演出中' || state === 'ongoing') return 'secondary'
  if (state === '已演出' || state === 'done') return 'outline'
  if (state === '取消' || state === 'cancelled') return 'destructive'
  return 'secondary'
}

function statusBadgeClass(state) {
  if (state === '未演出' || state === 'upcoming') {
    return 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-800'
  }
  if (state === '演出中' || state === 'ongoing') {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800'
  }
  if (state === '已演出' || state === 'done') {
    return 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
  }
  if (state === '取消' || state === 'cancelled') {
    return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/60 dark:text-red-300 dark:border-red-800'
  }
  return 'bg-slate-100 text-slate-700 border-slate-200'
}

function formatShowTime(timeStr) {
  if (!timeStr) return '暂无时间'
  let str = String(timeStr).replace('T', ' ')
  if (str.length > 16 && str.includes(':')) {
    str = str.substring(0, 16)
  }
  return str
}

function formatSingleChip(val, index = 0) {
  let text = String(val).trim()
  if (!text) return null
  let tag = ''
  let tagType = ''

  if (text.includes('缺货') || text.includes('无票')) {
    tag = '缺货登记'
    tagType = 'soldout'
    text = text.replace(/缺货登记|缺货|无票/g, '').trim()
  } else if (text.includes('惠') || text.includes('早鸟')) {
    tag = '惠'
    tagType = 'hui'
    text = text.replace(/惠|早鸟/g, '').trim()
  }

  let numStr = text.replace(/[^0-9.]/g, '')
  if (numStr && !isNaN(numStr)) {
    let num = parseFloat(numStr)
    text = (Number.isInteger(num) ? num : num.toFixed(1)) + '元'
  } else if (!text.includes('元') && text.length > 0) {
    text = text + '元'
  }

  return {
    text: text,
    tag,
    tagType,
    isPrimary: index === 1
  }
}

function parsePriceChips(priceVal) {
  if (!priceVal) return [{ text: '暂无票价数据', raw: true }]

  let str = String(priceVal).trim()
  if (!str || str === '[object Object]' || str === 'Object' || str === 'null' || str === 'undefined') {
    return [{ text: '暂无票价数据', raw: true }]
  }

  if ((str.startsWith('[') && str.endsWith(']')) || (str.startsWith('{') && str.endsWith('}'))) {
    try {
      const parsed = JSON.parse(str)
      return parsePriceChips(parsed)
    } catch (e) {}
  }

  if (Array.isArray(priceVal)) {
    const list = priceVal.map((item, idx) => formatSingleChip(typeof item === 'object' ? item.price || item.name : item, idx)).filter(Boolean)
    return list.length > 0 ? list : [{ text: '暂无票价数据', raw: true }]
  }

  if (typeof priceVal === 'object' && priceVal !== null) {
    if (priceVal.price) return parsePriceChips(priceVal.price)
    if (priceVal.priceRange) return parsePriceChips(priceVal.priceRange)
    if (priceVal.text) return parsePriceChips(priceVal.text)
    const vals = Object.values(priceVal).filter(v => typeof v === 'string' || typeof v === 'number')
    if (vals.length > 0) return [{ text: vals.join(' / '), raw: true }]
    return [{ text: '暂无票价数据', raw: true }]
  }

  // Format A: "CNY / 166 / 866 / 166|366|566|766|866" or "120|680"
  if (str.includes('|')) {
    const parts = str.split('/')
    const pipePart = parts.find(p => p.includes('|')) || str
    const prices = pipePart.split('|').map(s => s.trim()).filter(Boolean)
    const list = prices.map((p, idx) => formatSingleChip(p, idx)).filter(Boolean)
    return list.length > 0 ? list : [{ text: str, raw: true }]
  }

  if (str.startsWith('CNY') && !str.includes('|')) {
    return [{ text: str, raw: true }]
  }

  const items = str.split(/[/,、;\s]+/).map(s => s.trim()).filter(Boolean)
  if (items.length <= 1) {
    const single = formatSingleChip(str, 0)
    return single ? [single] : [{ text: str, raw: true }]
  }

  const list = items.map((item, idx) => formatSingleChip(item, idx)).filter(Boolean)
  return list.length > 0 ? list : [{ text: str, raw: true }]
}

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

function triggerToast(msg, type = 'success') {
  if (type === 'error' || type === 'destructive') toast.error(msg)
  else if (type === 'success') toast.success(msg)
  else if (type === 'warn' || type === 'warning') toast.warn(msg)
  else toast(msg)
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
  { key: 'url', title: 'url', width: '220px', visible: true },
  { key: 'actions', title: '操作', width: '160px', visible: true }
])

// 详情、编辑、删除 模态框状态与数据
const showDetailModal = ref(false)
const detailRow = ref(null)

function openDetail(row) {
  detailRow.value = row
  showDetailModal.value = true
}

const showEditModal = ref(false)
const editRowData = reactive({
  id: '',
  seq: '',
  poster_url: '',
  title: '',
  norm_title: '',
  city: '',
  district: '',
  venue_name: '',
  norm_venue: '',
  start_time: '',
  year: '',
  month: '',
  quarter: '',
  day: '',
  weekday: '',
  holiday: '',
  troupe: '',
  group_city: '',
  hk_mo_tw: '',
  organizer: '',
  organizer_city: '',
  category: '',
  subcategory: '',
  session_count: 1,
  perf_state: '',
  troupe_attr: '',
  performers: '',
  price: '',
  url: ''
})

function openEdit(row) {
  editRowData.id = row.id || ''
  editRowData.seq = row.seq || ''
  editRowData.poster_url = row.poster_url || ''
  editRowData.title = row.title || ''
  editRowData.norm_title = row.norm_title || row.title || ''
  editRowData.city = row.city || ''
  editRowData.district = row.district || ''
  editRowData.venue_name = row.venue_name || ''
  editRowData.norm_venue = row.norm_venue || row.venue_name || ''
  editRowData.start_time = row.start_time || ''
  editRowData.year = row.year || ''
  editRowData.month = row.month || ''
  editRowData.quarter = row.quarter || ''
  editRowData.day = row.day || ''
  editRowData.weekday = row.weekday || ''
  editRowData.holiday = row.holiday || ''
  editRowData.troupe = row.troupe || ''
  editRowData.group_city = row.group_city || ''
  editRowData.hk_mo_tw = row.hk_mo_tw || ''
  editRowData.organizer = row.organizer || ''
  editRowData.organizer_city = row.organizer_city || ''
  editRowData.category = row.category || ''
  editRowData.subcategory = row.subcategory || ''
  editRowData.session_count = row.session_count || 1
  editRowData.perf_state = row.perf_state || 'upcoming'
  editRowData.troupe_attr = row.troupe_attr || ''
  editRowData.performers = row.performers || ''
  editRowData.price = row.price || ''
  editRowData.url = row.url || ''
  showEditModal.value = true
}

function saveEdit() {
  const target = rows.value.find(r => r.id === editRowData.id)
  if (target) {
    Object.assign(target, JSON.parse(JSON.stringify(editRowData)))
  }
  showEditModal.value = false
  triggerToast('全量演出字段修改保存成功！', 'success')
}

const showSingleDeleteModal = ref(false)
const deleteTargetRow = ref(null)

function openDeleteConfirm(row) {
  deleteTargetRow.value = row
  showSingleDeleteModal.value = true
}

function confirmSingleDelete() {
  if (deleteTargetRow.value) {
    rows.value = rows.value.filter(r => r.id !== deleteTargetRow.value.id)
    selectedRowIds.value = selectedRowIds.value.filter(id => id !== deleteTargetRow.value.id)
    total.value = Math.max(0, total.value - 1)
    triggerToast('已删除该条演出记录', 'success')
  }
  showSingleDeleteModal.value = false
}

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
          <Input
            type="text"
            v-model="citySearchQuery"
            placeholder="搜索城市..."
            class="city-search-input"
          />
          <Button v-if="citySearchQuery" variant="ghost" class="clear-city-search" @click="citySearchQuery = ''">✕</Button>
        </div>
      </div>

      <div class="city-grid-container" :class="{ expanded: isCityExpanded }">
        <div class="city-scroll-area" :class="{ expanded: isCityExpanded }">
          <div class="city-chips-list">
            <Button
              v-for="c in visibleCityOptions"
              :key="c"
              variant="ghost"
              class="city-chip-btn"
              :class="{ active: (c === '全部' && filters.city === 'all') || filters.city === c }"
              @click="handleCitySelect(c)"
            >
              {{ c }}
            </Button>
            <div v-if="visibleCityOptions.length === 0" class="no-city-match">
              未找到匹配城市
            </div>
          </div>
        </div>

        <Button variant="ghost" class="expand-toggle-btn" @click="isCityExpanded = !isCityExpanded">
          <span>{{ isCityExpanded ? '收起' : '更多' }}</span>
          <svg v-if="isCityExpanded" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="18 15 12 9 6 15"/></svg>
          <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
        </Button>
      </div>
    </div>

    <!-- 顶部 Filter 综合筛选栏（全部元素单行开阔并排） -->
    <div class="filter-card">
      <div class="filter-row">
         <Button variant="outline" size="icon" class="h-8 w-8 shrink-0" :disabled="refreshing || loading" title="刷新数据" @click="handleRefresh">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" :class="{ 'icon-spin': refreshing || loading }"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
          </Button>
        <!-- 1. 列显示设置 按钮 -->
        <Button variant="outline" size="sm" class="h-8 text-xs gap-1.5 shrink-0" @click="showColumnModal = true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7m0-18H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7m0-18v18"/></svg>
          列显示
        </Button>

        <!-- 2. 导出 Excel 按钮 -->
        <Button variant="outline" size="sm" class="h-8 text-xs gap-1.5 shrink-0 border-blue-200 text-blue-600 hover:bg-blue-50 hover:text-blue-700 dark:border-blue-800 dark:text-blue-400" @click="handleExportClick">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          导出
        </Button>

        <!-- 3. 清除数据 按钮 -->
        <Button variant="destructive" size="sm" class="h-8 text-xs gap-1.5 shrink-0" :disabled="clearing" @click="showClearModal = true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          清除数据
        </Button>

        <div class="filter-divider"></div>

        <!-- 3. 关键词 -->
        <div class="filter-item keyword-item">
          <span class="field-label">关键词</span>
          <div class="search-input-wrap">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="search-icon"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <Input
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

        <!-- 8. 查询 & 重置 按钮 -->
        <div class="filter-actions flex items-center gap-2">
          <Button variant="default" size="sm" class="h-8 text-xs gap-1.5 btn-theme-primary text-white" @click="doSearch">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            查询
          </Button>
          <Button variant="outline" size="sm" class="h-8 text-xs gap-1.5" @click="resetFilters">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            重置
          </Button>
        </div>
      </div>
    </div>

    <!-- 超宽数据表格 Wide Data Grid (独立卡片，表格与分页解耦，支持畅快横滑与表头吸顶) -->
    <div class="table-card-container flex-1 min-h-0 rounded-md border border-slate-200/80 dark:border-slate-800 shadow-sm bg-card transition-all relative flex flex-col overflow-hidden">
      <!-- 刷新已有数据时的半透明加载遮罩 -->
      <div v-if="(loading || refreshing) && rows.length > 0" class="table-loading-overlay">
        <div class="loading-pill">
          <span class="loading-spinner"></span>
          <span>正在刷新数据…</span>
        </div>
      </div>

      <!-- 独立 Table 滚动视图：包裹层为唯一的 overflow-auto 产生真正的滚动上下文 -->
      <Table wrapperClass="w-full h-full overflow-auto custom-table-scrollbar" class="data-table border-collapse min-w-[1400px]">
        <TableHeader class="sticky top-0 z-30 shadow-xs">
          <TableRow class="hover:bg-transparent">
            <!-- 勾选列 Header (吸顶 + 左浮) -->
            <TableHead class="col-chk w-[44px] text-center sticky top-0 left-0 z-40 bg-slate-100 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
              <Checkbox :checked="isAllSelected" @update:checked="toggleSelectAll" />
            </TableHead>
            <!-- 各数据列 Header (吸顶) -->
            <TableHead
              v-for="(col, ci) in visibleColumns"
              :key="ci"
              :style="{ width: col.width, minWidth: col.width }"
              class="text-xs font-bold text-slate-700 dark:text-slate-200 py-3 tracking-wide sticky top-0 z-30 bg-slate-100 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800"
              :class="{ 'sticky right-0 z-40 bg-slate-100 dark:bg-slate-900 border-l border-slate-300 dark:border-slate-700 shadow-[-12px_0_20px_-3px_rgba(0,0,0,0.18)] text-center': col.key === 'actions' }"
            >
              <div class="th-content">
                <span class="th-text">{{ col.title }}</span>
              </div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-if="loading && rows.length === 0">
            <TableCell :colspan="visibleColumns.length + 1" class="empty-cell text-center py-10">
              <span class="loading-inline"><span class="loading-spinner small"></span> 正在加载数据…</span>
            </TableCell>
          </TableRow>
          <TableRow v-else-if="!loading && rows.length === 0">
            <TableCell :colspan="visibleColumns.length + 1" class="empty-cell text-center py-10" :class="{ 'error-cell': errorMsg }">
              {{ errorMsg || '暂无数据，请先在「数据采集」页启动采集' }}
            </TableCell>
          </TableRow>
          <TableRow
            v-for="(row, rowIndex) in rows"
            :key="row.id"
            class="group border-b border-slate-100 dark:border-slate-800/60 hover:bg-slate-50/80 dark:hover:bg-slate-900/50 transition-colors text-xs"
            :class="{ 'bg-pink-100/60 dark:bg-pink-950/50 font-medium': selectedRowIds.includes(row.id) }"
          >
            <TableCell class="col-chk text-center">
              <Checkbox :checked="selectedRowIds.includes(row.id)" @update:checked="(v) => { if (v) { if (!selectedRowIds.includes(row.id)) selectedRowIds.push(row.id) } else { selectedRowIds = selectedRowIds.filter(id => id !== row.id) } }" />
            </TableCell>
            <TableCell
              v-for="col in visibleColumns"
              :key="col.title"
              class="td-cell py-3"
              :class="{ 'sticky right-0 z-20 bg-white dark:bg-slate-950 group-hover:bg-slate-50 dark:group-hover:bg-slate-900 border-l border-slate-300 dark:border-slate-700 shadow-[-12px_0_20px_-3px_rgba(0,0,0,0.15)]': col.key === 'actions' }"
            >
              <!-- 海报缩略图：点击放大预览 -->
              <template v-if="col.key === 'poster'">
                <img
                  v-if="cleanPosterUrl(row.poster_url)"
                  :src="cleanPosterUrl(row.poster_url)"
                  class="poster-thumb w-8 h-11 rounded border object-cover shadow-2xs cursor-pointer hover:scale-110 transition-transform"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  :alt="row.title"
                  @click.stop="openPreview(row.poster_url, row.title)"
                />
                <span v-else class="poster-empty text-slate-300">—</span>
              </template>

              <!-- 状态 Badge：演出状态 -->
              <template v-else-if="col.key === 'status'">
                <span
                  v-if="row.perf_state"
                  class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border shadow-2xs"
                  :class="statusBadgeClass(row.perf_state)"
                >
                  <span
                    class="w-1.5 h-1.5 rounded-full shrink-0"
                    :class="{
                      'bg-blue-600': row.perf_state === '未演出' || row.perf_state === 'upcoming',
                      'bg-emerald-600 animate-pulse': row.perf_state === '演出中' || row.perf_state === 'ongoing',
                      'bg-slate-500': row.perf_state === '已演出' || row.perf_state === 'done',
                      'bg-red-600': row.perf_state === '取消' || row.perf_state === 'cancelled'
                    }"
                  ></span>
                  <span>{{ row.perf_state }}</span>
                </span>
                <span v-else class="text-slate-300">-</span>
              </template>

              <!-- URL 链接 -->
              <template v-else-if="col.key === 'url'">
                <a
                  v-if="row.url"
                  :href="row.url"
                  class="url-link text-blue-600 hover:underline font-mono text-[11px] flex items-center gap-1"
                  @click.stop.prevent="openExternalUrl(row.url)"
                  :title="row.url"
                >
                  <span class="url-text truncate max-w-[180px]">{{ row.url }}</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                </a>
                <span v-else class="text-slate-300">-</span>
              </template>

              <!-- 操作列：固钉在右侧 (Sticky Right) 的 Outlined 按钮组 (详情, 编辑, 删除) -->
              <template v-else-if="col.key === 'actions'">
                <div class="flex items-center justify-center gap-1.5 shrink-0" @click.stop>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-7 px-2.5 rounded-md text-xs font-semibold text-blue-600 border-blue-200 hover:bg-blue-50 hover:border-blue-300 dark:border-blue-800 dark:text-blue-400"
                    @click="openDetail(row)"
                  >
                    详情
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-7 px-2.5 rounded-md text-xs font-semibold text-slate-700 border-slate-200 hover:bg-slate-100 hover:text-slate-900 dark:border-slate-700 dark:text-slate-200"
                    @click="openEdit(row)"
                  >
                    编辑
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-7 px-2.5 rounded-md text-xs font-semibold text-red-600 border-red-200 hover:bg-red-50 hover:border-red-300 dark:border-red-900 dark:text-red-400"
                    @click="openDeleteConfirm(row)"
                  >
                    删除
                  </Button>
                </div>
              </template>

              <!-- 默认文字 -->
              <template v-else>
                {{ cellValue(row, col.key, rowIndex + 1) }}
              </template>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <!-- 2. 独立分页控制卡片 (与表格解耦，避免阻塞横向滚动条) -->
    <div class="pagination-card-container flex items-center justify-between px-5 py-3 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm bg-card text-xs text-slate-500 shrink-0">
      <div class="footer-stat text-xs text-slate-500">
        当前显示 <strong>{{ total === 0 ? 0 : (page - 1) * pageSize + 1 }}-{{ Math.min(page * pageSize, total) }}</strong> / 共 <strong class="text-slate-800 dark:text-slate-200">{{ total }}</strong> 条记录
        <span v-if="selectedRowIds.length > 0" class="ml-2 text-pink-600 font-semibold">(已选中 {{ selectedRowIds.length }} 项)</span>
      </div>

      <div class="footer-pagination flex items-center gap-4">
        <div class="flex items-center gap-1.5 text-xs text-slate-500">
          <span>每页条数</span>
          <select v-model.number="pageSize" @change="changePageSize" class="page-select text-xs h-7 border rounded px-2 bg-background font-medium">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </div>

        <Pagination
          :total="total"
          :items-per-page="pageSize"
          :page="page"
          @update:page="goPage"
        >
          <PaginationList class="flex items-center gap-1">
            <PaginationFirst @click="goPage(1)" :disabled="page <= 1" />
            <PaginationPrev @click="goPage(page - 1)" :disabled="page <= 1" />
            <span class="text-xs px-2 font-medium">第 <strong>{{ page }}</strong> 页，共 {{ totalPages }} 页</span>
            <PaginationNext @click="goPage(page + 1)" :disabled="page >= totalPages" />
            <PaginationLast @click="goPage(totalPages)" :disabled="page >= totalPages" />
          </PaginationList>
        </Pagination>
      </div>
    </div>

    <!-- 抽离到 custom/ 目录下的专业 Modal 公共业务组件 -->
    <ColumnConfigModal
      v-model:open="showColumnModal"
      :columns="columns"
      @save="showColumnModal = false"
    />

    <ExportModal
      v-model:open="showExportModal"
      :selected-count="selectedRowIds.length"
      :total="total"
      @export="executeExport"
    />

    <ClearDataModal
      v-model:open="showClearModal"
      :selected-count="selectedRowIds.length"
      :total="total"
      :clearing="clearing"
      @clear="executeClear"
    />

    <ShowDetailModal
      v-model:open="showDetailModal"
      :detail-row="detailRow"
      :clean-poster-url="cleanPosterUrl"
      :format-show-time="formatShowTime"
      :parse-price-chips="parsePriceChips"
      :status-badge-class="statusBadgeClass"
      @open-preview="openPreview"
      @open-external-url="openExternalUrl"
    />

    <ShowEditModal
      v-model:open="showEditModal"
      :edit-row-data="editRowData"
      @save="saveEdit"
    />

    <SingleDeleteModal
      v-model:open="showSingleDeleteModal"
      :target-row="deleteTargetRow"
      @confirm="confirmSingleDelete"
    />

    <ImagePreviewModal
      :open="!!previewImage"
      @update:open="(v) => { if (!v) closePreview() }"
      :image-url="previewImage"
      :title="previewTitle"
    />

  </div>
</template>

<style scoped>
/* 自定义表格滚动条：高度加粗(14px)且动态绑定系统主题色 var(--primary) */
.custom-table-scrollbar::-webkit-scrollbar {
  width: 8px;
  height: 10px;
}
.custom-table-scrollbar::-webkit-scrollbar-track {
  background: #f1f5f9;
  border-radius: 7px;
}
.dark .custom-table-scrollbar::-webkit-scrollbar-track {
  background: #1e293b;
}
.custom-table-scrollbar::-webkit-scrollbar-thumb {
  background: var(--primary, #eb4f9a);
  border-radius: 7px;
  border: 2px solid #f1f5f9;
  transition: background-color 0.2s ease;
}
.dark .custom-table-scrollbar::-webkit-scrollbar-thumb {
  border: 2px solid #1e293b;
}
.custom-table-scrollbar::-webkit-scrollbar-thumb:hover {
  background: var(--primary-hover, #d83b87);
}

/* 关联系统主题色的动态按钮 */
.btn-theme-primary {
  background-color: var(--primary, #eb4f9a) !important;
  color: #ffffff !important;
  border: none !important;
  transition: background-color 0.2s ease, box-shadow 0.2s ease;
}
.btn-theme-primary:hover {
  background-color: var(--primary-hover, #d83b87) !important;
  box-shadow: 0 4px 12px var(--primary-shadow, rgba(235, 79, 154, 0.3));
}

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
