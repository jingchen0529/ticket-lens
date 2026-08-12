<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted, defineExpose } from 'vue'
import { save } from '@tauri-apps/plugin-dialog'
import { writeFile } from '@tauri-apps/plugin-fs'
import { api, IN_TAURI } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toast'
import { translateLogText } from '@/utils/logTranslator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { HOT_CITIES, ALPHABET_CITY_GROUPS } from '@/data/cityData'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'

// 1. 目标平台 (目前仅开放大麦网)
const selectedPlatforms = ref(['damai', 'maoyan'])
const selectedPlatformTab = ref('all')
const damaiCategories = [
  '曲苑杂坛',
  '话剧歌剧',
  '演唱会',
  '音乐会',
  '展览休闲',
  '体育',
  '舞蹈芭蕾',
  '其他',
  '儿童亲子'
]
const selectedDamaiCategory = ref('all')
const maoyanCategories = [
  '演唱会',
  '话剧音乐剧',
  '音乐节',
  '脱口秀',
  '音乐会',
  '戏曲艺术',
  '沉浸剧场',
  '相声',
  '休闲展览',
  '亲子演出',
  '舞蹈芭蕾',
  'Livehouse',
  '电竞赛事',
  '体育赛事',
  '剧本杀',
  '其他'
]
const selectedMaoyanCategory = ref('all')

const damaiCategoryValue = computed(() =>
  selectedDamaiCategory.value === 'all' ? '' : selectedDamaiCategory.value
)

const maoyanCategoryValue = computed(() =>
  selectedMaoyanCategory.value === 'all' ? '' : selectedMaoyanCategory.value
)

function setPlatformTab(tab) {
  if (tab === 'all') {
    selectedPlatformTab.value = tab
    selectedPlatforms.value = ['damai', 'maoyan']
  } else if (tab === 'damai') {
    selectedPlatformTab.value = tab
    selectedPlatforms.value = ['damai']
  } else if (tab === 'maoyan') {
    selectedPlatformTab.value = tab
    selectedPlatforms.value = ['maoyan']
  } else if (tab === 'showstart') {
    selectedPlatformTab.value = tab
    selectedPlatforms.value = ['showstart']
    toast.warn('秀动 ShowStart 平台数据采集功能正在开发中，暂未开放')
  } else {
    selectedPlatformTab.value = tab
    selectedPlatforms.value = ['damai']
  }
}

let lastNotifiedJobIdState = ''

function triggerToast(msg, type = 'default') {
  if (type === 'error' || type === 'destructive') toast.error(msg)
  else if (type === 'success') toast.success(msg)
  else if (type === 'warn' || type === 'warning') toast.warn(msg)
  else toast(msg)
}

// 2. 演艺多平台完整城市列表 (热门城市及 A-Z 拼音字母索引)
const activeLetter = ref('ALL')
const alphabetLetters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'W', 'X', 'Y', 'Z']
const cityScrollAreaRef = ref(null)
let isProgrammaticScroll = false
let programmaticScrollTimer = null

// 摊平全国完整城市列表 (650+ 市)
const allFlatCities = computed(() => {
  const set = new Set(HOT_CITIES)
  ALPHABET_CITY_GROUPS.forEach(g => {
    g.cities.forEach(c => set.add(c))
  })
  return Array.from(set)
})

// 已选城市列表 (默认 ['北京'])
const selectedCities = ref(['北京'])
const searchCityQuery = ref('')

const isAllSelected = computed(() => {
  return selectedCities.value.length === 1 && selectedCities.value[0] === '全部'
})

// 热门城市组 (支持搜索过滤)
const filteredHotCities = computed(() => {
  const query = searchCityQuery.value.trim().toLowerCase()
  if (!query) return HOT_CITIES
  return HOT_CITIES.filter(c => c.toLowerCase().includes(query))
})

// 按字母分组 (保留所有字母组，渲染完整列表，支持定位平滑滚动及上下自由浏览)
const groupedAlphabetCategories = computed(() => {
  const query = searchCityQuery.value.trim().toLowerCase()
  return ALPHABET_CITY_GROUPS.map(g => {
    const matchingCities = query
      ? g.cities.filter(c => c.toLowerCase().includes(query))
      : g.cities

    return {
      letter: g.letter,
      matchingCities
    }
  }).filter(g => g.matchingCities.length > 0)
})

function scrollToLetter(letter) {
  activeLetter.value = letter
  isProgrammaticScroll = true
  if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer)
  programmaticScrollTimer = setTimeout(() => {
    isProgrammaticScroll = false
  }, 700)

  nextTick(() => {
    if (!cityScrollAreaRef.value) return
    const scrollEl = cityScrollAreaRef.value.$el || cityScrollAreaRef.value
    const viewport = scrollEl.querySelector?.('[data-radix-scroll-area-viewport]') || scrollEl

    if (!viewport) return

    if (letter === 'ALL') {
      viewport.scrollTo({ top: 0, behavior: 'smooth' })
      return
    }

    const targetId = `city-group-${letter}`
    const targetEl = viewport.querySelector(`#${targetId}`)
    if (targetEl) {
      const viewportRect = viewport.getBoundingClientRect()
      const targetRect = targetEl.getBoundingClientRect()
      const targetScrollTop = Math.max(
        0,
        targetRect.top - viewportRect.top + viewport.scrollTop - 12
      )
      viewport.scrollTo({ top: targetScrollTop, behavior: 'smooth' })
    }
  })
}

function handleCityAreaScroll(e) {
  if (isProgrammaticScroll) return
  const viewport = e.target
  if (!viewport) return

  const viewportRect = viewport.getBoundingClientRect()
  const groupElements = viewport.querySelectorAll('[id^="city-group-"]')

  let currentActive = 'ALL'
  let minDiff = Infinity

  groupElements.forEach(el => {
    const rect = el.getBoundingClientRect()
    const diff = Math.abs(rect.top - viewportRect.top)
    if (rect.top <= viewportRect.top + 60 && diff < minDiff) {
      minDiff = diff
      const id = el.id.replace('city-group-', '')
      currentActive = id
    }
  })

  if (currentActive) {
    activeLetter.value = currentActive
  }
}

onMounted(() => {
  nextTick(() => {
    if (!cityScrollAreaRef.value) return
    const scrollEl = cityScrollAreaRef.value.$el || cityScrollAreaRef.value
    const viewport = scrollEl.querySelector?.('[data-radix-scroll-area-viewport]') || scrollEl
    if (viewport) {
      viewport.addEventListener('scroll', handleCityAreaScroll, { passive: true })
    }
  })
})

onUnmounted(() => {
  if (cityScrollAreaRef.value) {
    const scrollEl = cityScrollAreaRef.value.$el || cityScrollAreaRef.value
    const viewport = scrollEl.querySelector?.('[data-radix-scroll-area-viewport]') || scrollEl
    if (viewport) {
      viewport.removeEventListener('scroll', handleCityAreaScroll)
    }
  }
})

function selectCity(city) {
  selectedCities.value = [city]
}

// 执行参数：采集页数上限 (空字符串 = 全量)
const maxPagesInput = ref('10')
const autoRetry = ref(true)

// 冰拓凭据检查状态
const bingtuoStatus = ref({ hasCredentials: false, username: '' })
const isCheckingBingtuo = ref(false)
const bingtuoPoints = ref(null)
const bingtuoBalanceState = ref('idle') // idle | loading | ready | unconfigured | error
const bingtuoBalanceError = ref('')

const bingtuoPointsDisplay = computed(() => {
  if (bingtuoBalanceState.value === 'loading') return '...'
  if (bingtuoPoints.value === null || bingtuoPoints.value === undefined) return '--'
  const points = Number(bingtuoPoints.value)
  return Number.isFinite(points) ? points.toLocaleString() : String(bingtuoPoints.value)
})

const bingtuoBalanceHint = computed(() => {
  if (bingtuoBalanceState.value === 'loading') return '正在查询平台余额'
  if (bingtuoBalanceState.value === 'unconfigured') return '请先在系统设置中配置'
  if (bingtuoBalanceState.value === 'error') return '查询失败，点击卡片重试'
  if (bingtuoBalanceState.value === 'ready') return '点击卡片可刷新余额'
  return '等待查询余额'
})

// ---- 真实采集任务状态（对接后端 /api/crawl）----
const activeJob = ref(null)   // 当前/最近一次任务记录
const jobs = ref([])          // 历史任务列表
const totalShows = ref(0)     // 库内已采集演出总数
const todayShows = ref(0)     // 今日本地新增采集数据数
const starting = ref(false)
const submitError = ref('')
const logConsoleEl = ref(null)
const exportingLogs = ref(false)
let pollTimer = null

// 后端 JobState → 中文
const STATE_LABELS = {
  pending: '排队中', running: '抓取中',
  succeeded: '已完成', failed: '异常', cancelled: '已取消'
}

// 是否有任务在跑
const isCrawling = computed(() =>
  !!activeJob.value && ['pending', 'running'].includes(activeJob.value.state)
)

function sourcesLabel(sources) {
  return (sources || [])
    .map(s => (s === 'damai' ? '大麦网' : s === 'maoyan' ? '猫眼' : s === 'showstart' ? '秀动' : s))
    .join('/') || '大麦网'
}

function taskResultCounts(result = {}) {
  const imported = Number(result.show_count ?? 0) || 0
  const breakdown = result.ledger_hidden_by_category || {}
  const breakdownHidden = Object.values(breakdown)
    .reduce((sum, value) => sum + (Number(value) || 0), 0)
  const hidden = Number(result.ledger_hidden_count ?? breakdownHidden) || 0
  const visible = Number(result.ledger_visible_count ?? Math.max(0, imported - hidden)) || 0
  return { imported, visible, hidden }
}

// ---- 任务格式化与分页 ----
const taskPage = ref(1)
const taskPageSize = ref(10)
const jumpPageInput = ref(1)

function formatDateTime(ts) {
  if (!ts) return '-'
  try {
    const d = new Date(ts)
    if (Number.isNaN(d.getTime())) return String(ts)
    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`
  } catch {
    return String(ts)
  }
}

const taskRowsFormatted = computed(() => {
  const out = []
  if (jobs.value.length === 0) return out
  for (let index = 0; index < jobs.value.length; index++) {
    const j = jobs.value[index]
    const taskNo = `TASK-${j.id ? j.id.slice(0, 8).toUpperCase() : String(index + 1).padStart(3, '0')}`
    const city = (j.job?.cities && j.job.cities.length) ? (j.job.cities.length > 2 ? `${j.job.cities[0]}等${j.job.cities.length}市` : j.job.cities.join('、')) : '全国'
    const pages = j.job?.max_pages === 0 ? '全部' : (j.job?.max_pages || 10)
    const startTime = j.started_at ? formatDateTime(j.started_at) : (j.created_at ? formatDateTime(j.created_at) : '-')
    const endTime = j.finished_at ? formatDateTime(j.finished_at) : '-'
    const resultCounts = taskResultCounts(j.result)

    out.push({
      key: j.id || index,
      taskNo,
      city,
      platform: sourcesLabel(j.job?.sources),
      category: j.job?.category || '全部分类',
      pages,
      state: j.state || 'succeeded',
      count: resultCounts.imported,
      ledgerVisibleCount: resultCounts.visible,
      ledgerHiddenCount: resultCounts.hidden,
      startTime,
      endTime,
      rawJob: j
    })
  }
  return out
})

// ---- 日志清空与复制 ----
const isLogCleared = ref(false)
const isUserScrolledUpLogConsole = ref(false)

function handleLogConsoleScroll(e) {
  const el = e?.target || logConsoleEl.value
  if (!el) return
  const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  // 距离底部大于 30px 时判定为用户主动向上翻页查看历史日志，暂停强制置底
  isUserScrolledUpLogConsole.value = distanceFromBottom > 15
}

function scrollToLogBottom() {
  isUserScrolledUpLogConsole.value = false
  nextTick(() => {
    const el = logConsoleEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function activateJobRecord(job) {
  const currentId = activeJob.value?.id || ''
  const nextId = job?.id || ''
  if (nextId && nextId !== currentId) {
    // 新任务必须使用全新的日志视图；之前点过 Clear 也不能影响新任务。
    isLogCleared.value = false
    isUserScrolledUpLogConsole.value = false
  }
  activeJob.value = job
}

function clearLogs() {
  isLogCleared.value = true
  isUserScrolledUpLogConsole.value = false
  triggerToast('✓ 已成功清空实时日志输出', 'success')
}

async function copyLogs() {
  if (displayLogs.value.length === 0) {
    triggerToast('当前没有可复制的日志内容', 'warn')
    return
  }
  const text = displayLogs.value
    .map(l => `[${l.time}] [${l.levelLabel || mapLogLevelLabel(l.type)}] ${l.text}`)
    .join('\n')
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    triggerToast('✓ 已成功将实时日志复制到剪贴板！', 'success')
  } catch {
    triggerToast('复制日志失败，请手动选择复制', 'error')
  }
}

function buildTaskLogExport(job) {
  const rows = Array.isArray(job?.logs) ? job.logs : []
  const taskId = job?.id ? `任务-${job.id.slice(0, 8).toUpperCase()}` : '未知任务'
  const sources = sourcesLabel(job?.job?.sources)
  const cities = Array.isArray(job?.job?.cities) && job.job.cities.length
    ? job.job.cities.join('、')
    : '全国'
  const pages = !job?.job?.max_pages || job.job.max_pages <= 0
    ? '全部'
    : String(job.job.max_pages)
  const state = STATE_LABELS[job?.state] || job?.state || '未知'
  const result = job?.result || {}
  const resultCounts = taskResultCounts(result)
  const lines = [
    '大喜演出数据采集 - 任务运行日志',
    '========================================',
    `任务编号：${taskId}`,
    `任务状态：${state}`,
    `目标平台：${sources}`,
    `目标城市：${cities}`,
    `采集分类：${job?.job?.category || '全部分类'}`,
    `采集页数：${pages} 页/城`,
    `创建时间：${formatDateTime(job?.created_at)}`,
    `开始时间：${formatDateTime(job?.started_at)}`,
    `结束时间：${formatDateTime(job?.finished_at)}`,
    `原始数据：${result.raw_count ?? 0} 条`,
    `入库：${resultCounts.imported} 条`,
    `台账可见：${resultCounts.visible} 条`,
    `隐藏展览休闲/体育：${resultCounts.hidden} 条`,
    `错误摘要：${job?.error ? translateLogText(job.error) : '无'}`,
    `日志条数：${rows.length} 条`,
    '',
    '================ 运行日志 ================',
    '',
  ]

  for (const row of rows) {
    const time = formatDateTime(row?.ts)
    const level = mapLogLevelLabel(row?.level)
    const text = translateLogText(row?.text || '')
    lines.push(`[${time}] [${level}] ${text}`)
  }

  return lines.join('\r\n')
}

function taskLogFilename(job) {
  const id = job?.id ? job.id.slice(0, 8).toUpperCase() : '未知'
  const date = new Date(job?.started_at || job?.created_at || Date.now())
  const pad = value => String(value).padStart(2, '0')
  const stamp = Number.isNaN(date.getTime())
    ? '未知时间'
    : `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  const state = STATE_LABELS[job?.state] || '运行中'
  return `任务-${id}_${stamp}_${state}.txt`
}

async function exportCurrentTaskLogs() {
  const job = activeJob.value
  const rows = Array.isArray(job?.logs) ? job.logs : []
  if (!job || rows.length === 0) {
    triggerToast('当前任务还没有可导出的日志', 'warn')
    return
  }

  const filename = taskLogFilename(job)
  const content = `\uFEFF${buildTaskLogExport(job)}`
  exportingLogs.value = true
  try {
    if (IN_TAURI) {
      const path = await save({
        title: '导出当前任务日志',
        defaultPath: filename,
        filters: [{ name: '文本日志', extensions: ['txt'] }],
      })
      if (!path) return
      await writeFile(path, new TextEncoder().encode(content))
    } else {
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    }
    triggerToast(`✓ 当前任务日志已导出：${filename}`, 'success')
  } catch (e) {
    triggerToast(`导出任务日志失败：${e?.message || e}`, 'error')
  } finally {
    exportingLogs.value = false
  }
}

function mapLogLevel(level) {
  const u = String(level || 'INFO').toUpperCase()
  if (u === 'WARNING' || u === 'WARN') return 'WARN'
  if (u === 'ERROR' || u === 'CRITICAL') return 'ERROR'
  if (u === 'DEBUG') return 'DEBUG'
  return 'INFO'
}

function mapLogLevelLabel(level) {
  const normalized = mapLogLevel(level)
  if (normalized === 'ERROR') return '错误'
  if (normalized === 'WARN') return '警告'
  if (normalized === 'DEBUG') return '调试'
  if (normalized === 'SUCCESS') return '成功'
  return '信息'
}

function formatLogTime(ts) {
  if (!ts) {
    const d = new Date()
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  }
  try {
    const d = new Date(ts)
    if (Number.isNaN(d.getTime())) return String(ts).slice(11, 19) || ts
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return String(ts).slice(11, 19) || ''
  }
}

// 实时日志
const logs = computed(() => {
  const out = []
  const j = activeJob.value
  if (!j) {
    out.push({
      type: 'INFO',
      time: formatLogTime(),
      text: '数据采集系统就绪。在上方配置要采集的平台、城市及页数后，点击【开始数据采集任务】发起采集。'
    })
    return out
  }

  const engineLogs = Array.isArray(j.logs) ? j.logs : []
  if (engineLogs.length > 0) {
    for (const row of engineLogs) {
      out.push({
        type: mapLogLevel(row.level),
        levelLabel: mapLogLevelLabel(row.level),
        time: formatLogTime(row.ts),
        text: translateLogText(row.text || '')
      })
    }
    return out
  }

  out.push({
    type: 'INFO',
    levelLabel: '信息',
    time: formatLogTime(j.started_at || j.created_at),
    text: `任务 ${j.id.slice(0, 8)}，状态：${STATE_LABELS[j.state] || '未知'}，城市：${(j.job?.cities || []).join('、') || '全国'}`
  })
  return out
})

const displayLogs = computed(() => {
  if (isLogCleared.value) return []
  return logs.value
})

watch(
  logs,
  async () => {
    await nextTick()
    const el = logConsoleEl.value
    // 只有当用户没有主动向上滚动查看历史日志时，才自动随新日志刷到底部
    if (el && !isUserScrolledUpLogConsole.value) {
      el.scrollTop = el.scrollHeight
    }
  },
  { deep: true }
)

// 统计数据
const stat = computed(() => {
  const j = activeJob.value
  return {
    total: totalShows.value,
    lastImported: j?.result?.show_count ?? 0,
    state: j ? (STATE_LABELS[j.state] || j.state) : '空闲'
  }
})

// 真实任务成功率（基于历史已结束的任务）
const computedSuccessRate = computed(() => {
  const finished = jobs.value.filter(j => ['succeeded', 'failed'].includes(j.state))
  if (finished.length === 0) return '100.0'
  const succ = finished.filter(j => j.state === 'succeeded').length
  return ((succ / finished.length) * 100).toFixed(1)
})

async function refreshTotal() {
  try {
    const data = await api.getStats()
    totalShows.value = data.total_shows || 0
    todayShows.value = data.today_shows || 0
  } catch {
    try {
      const data = await api.listShows({ limit: 1, offset: 0 })
      totalShows.value = data.total || 0
      todayShows.value = 0
    } catch {
      // 忽略
    }
  }
}

let isFirstLoad = true

async function refreshJobs() {
  try {
    const [activeResp, listResp] = await Promise.all([api.activeCrawl(), api.listCrawls()])
    jobs.value = listResp.items || []
    const j = activeResp.active || (jobs.value.length ? jobs.value[0] : null)
    const previousJob = activeJob.value
    activateJobRecord(j)
    if (
      previousJob?.id &&
      previousJob.id === j?.id &&
      previousJob.state !== j.state &&
      ['succeeded', 'failed', 'cancelled'].includes(j.state)
    ) {
      refreshBingtuoBalance()
    }
    if (isFirstLoad && j) {
      lastNotifiedJobIdState = `${j.id}:${j.state}`
      isFirstLoad = false
    }
  } catch (e) {
    // 忽略
  }
}

function resolveMaxPages() {
  const raw = String(maxPagesInput.value ?? '').trim()
  if (!raw) return 0
  const n = parseInt(raw, 10)
  if (!Number.isFinite(n) || n < 0) return null
  if (n === 0) return 0
  if (n > 9999) return null
  return n
}

async function startCrawl() {
  if (selectedCities.value.length === 0) {
    submitError.value = '请至少选择一个城市'
    return
  }
  const maxPages = resolveMaxPages()
  if (maxPages === null) {
    submitError.value = '采集页数请留空（全部）或填写 1–9999 的整数'
    return
  }

  const hasBingtuo = await checkBingtuo()
  if (!hasBingtuo) {
    submitError.value = '未配置冰拓验证码账号，请前往 [系统设置] 配置验证码服务'
    toast.error('未配置冰拓账号，请前往 [系统设置] 配置')
    return
  }

  starting.value = true
  submitError.value = ''

  let citiesToSubmit = []
  if (selectedCities.value.includes('全部') || selectedCities.value.length === 0) {
    citiesToSubmit = allFlatCities.value
  } else {
    citiesToSubmit = selectedCities.value
  }

  try {
    const submittedJob = await api.startCrawl({
      sources: selectedPlatforms.value,
      cities: citiesToSubmit,
      keywords: [],
      category: selectedPlatformTab.value === 'damai'
        ? damaiCategoryValue.value
        : selectedPlatformTab.value === 'maoyan'
          ? maoyanCategoryValue.value
          : '',
      max_pages: maxPages,
      headed: true
    })
    // 提交接口已返回新任务及首批日志，立即切换，不等待下一轮轮询。
    activateJobRecord(submittedJob)
    jobs.value = [submittedJob, ...jobs.value.filter(job => job.id !== submittedJob.id)]
    const hint = isAllSelected.value ? '全国全量' : `${citiesToSubmit.length} 城`
    const categoryHint = selectedPlatformTab.value === 'damai'
      ? ` · 大麦${damaiCategoryValue.value || '全部分类'}`
      : selectedPlatformTab.value === 'maoyan'
        ? ` · 猫眼${maoyanCategoryValue.value || '全部分类'}`
        : ''
    toast.success(`已启动采集（${hint}${categoryHint} · 最多 ${maxPages || '全部'} 页/城）`)
    await refreshJobs()
  } catch (e) {
    submitError.value = e.message || '启动采集失败'
  } finally {
    starting.value = false
  }
}

async function stopCrawl() {
  const j = activeJob.value
  if (!j) return
  try {
    await api.cancelCrawl(j.id)
    toast.warn('已成功发出停止采集指令')
    await refreshJobs()
  } catch (e) {
    submitError.value = e.message || '取消失败'
  }
}

function onEngineButton() {
  if (isCrawling.value) stopCrawl()
  else startCrawl()
}

async function checkBingtuo() {
  isCheckingBingtuo.value = true
  try {
    const info = await api.getBingtuoCredentials()
    const hasCredentials = !!(info.username && info.has_password)
    bingtuoStatus.value = {
      hasCredentials,
      username: info.username || ''
    }
    return hasCredentials
  } catch {
    bingtuoStatus.value = { hasCredentials: false, username: '' }
    return false
  } finally {
    isCheckingBingtuo.value = false
  }
}

async function refreshBingtuoBalance() {
  if (bingtuoBalanceState.value === 'loading') return
  bingtuoBalanceState.value = 'loading'
  bingtuoBalanceError.value = ''
  try {
    const data = await api.getBingtuoBalance()
    if (!data.configured) {
      bingtuoPoints.value = null
      bingtuoBalanceState.value = 'unconfigured'
      return
    }
    if (data.error) {
      bingtuoPoints.value = null
      bingtuoBalanceState.value = 'error'
      bingtuoBalanceError.value = data.error
      return
    }
    bingtuoPoints.value = data.points ?? 0
    bingtuoBalanceState.value = 'ready'
  } catch (e) {
    bingtuoPoints.value = null
    bingtuoBalanceState.value = 'error'
    bingtuoBalanceError.value = e?.message || '余额查询失败'
  }
}

async function checkBingtuoCredentials() {
  const [hasCredentials] = await Promise.all([
    checkBingtuo(),
    refreshBingtuoBalance(),
  ])
  return hasCredentials
}

const showTaskDetailModal = ref(false)
const currentSelectedTaskDetail = ref(null)

const manualCaptchaModalOpen = ref(false)
const dismissedManualCaptchaKey = ref('')
const manualCaptchaAlertKey = computed(() => {
  const alert = activeJob.value?.manual_captcha_required
  if (!alert?.required) return ''
  return alert.updated_at || `${activeJob.value?.id || ''}:${alert.provider || ''}:${alert.reason || ''}`
})
const manualCaptchaReason = computed(() => {
  return activeJob.value?.manual_captcha_required?.reason || '冰拓打码连续 3 次未返回有效距离或解析错误，需要人工介入。'
})

watch(
  manualCaptchaAlertKey,
  (alertKey) => {
    if (alertKey && alertKey !== dismissedManualCaptchaKey.value) {
      manualCaptchaModalOpen.value = true
    } else if (!alertKey) {
      manualCaptchaModalOpen.value = false
      dismissedManualCaptchaKey.value = ''
    }
  },
  { immediate: true }
)

function dismissManualCaptchaModal() {
  dismissedManualCaptchaKey.value = manualCaptchaAlertKey.value
  manualCaptchaModalOpen.value = false
}

async function cancelCurrentCrawlFromModal() {
  if (activeJob.value?.id) {
    try {
      await api.cancelCrawl(activeJob.value.id)
      triggerToast('已成功提交取消操作', 'warn')
    } catch (e) {
      triggerToast(e.message || '取消任务失败', 'error')
    }
  }
  dismissManualCaptchaModal()
}

onMounted(() => {
  checkBingtuoCredentials()
  refreshTotal()
  refreshJobs()
  pollTimer = setInterval(() => {
    refreshTotal()
    refreshJobs()
  }, 2500)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

defineExpose({
  refreshTotal,
  refreshJobs,
  checkBingtuo,
  checkBingtuoCredentials,
  refreshBingtuoBalance,
})
</script>

<template>
  <div class="crawl-view-container flex flex-col gap-5 p-5 bg-[#f8fafc] h-full overflow-y-auto min-h-0 pb-10">

    <!-- 1. 顶部状态 Banner (Top Banner Header - Dynamic Theme System Color Glassmorphism Card) -->
    <div
      class="top-status-banner relative rounded-2xl p-6 md:p-7 text-white shadow-lg overflow-hidden transition-all shrink-0 border border-white/10"
      :style="{ background: 'linear-gradient(135deg, var(--primary) 0%, var(--primary-hover, var(--primary)) 100%)' }"
    >
      <!-- 动态发光底纹 -->
      <div class="absolute -right-16 -top-16 w-80 h-80 bg-white/10 rounded-full blur-3xl pointer-events-none"></div>
      <div class="absolute left-1/3 -bottom-20 w-80 h-80 bg-black/10 rounded-full blur-3xl pointer-events-none"></div>

      <div class="relative z-10 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6">
        <!-- 左侧标题与描述 -->
        <div class="banner-left max-w-xl">
          <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold tracking-wide mb-3 border border-white/25 bg-black/15 backdrop-blur-md text-white">
            <span class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-white"></span>
            </span>
            <span>{{ isCrawling ? '采集引擎正在运行中' : '数据采集系统就绪待命' }}</span>
          </div>

          <h1 class="text-xl md:text-2xl font-black tracking-tight text-white flex items-center gap-2">
            {{ isCrawling ? '演艺数据实时采集任务执行中' : '数据采集系统正处于就绪状态' }}
          </h1>
          <p class="text-xs md:text-sm text-white/85 mt-2 leading-relaxed font-normal">
            本模块支持实时采集大麦网等平台全国范围的演出、演艺数据，集成智能代理分发、失败自动重试及第三方验证码自主识别策略。
          </p>
        </div>

        <!-- 右侧核心指标卡片 (系统主题透明 Glass Cards) -->
        <div class="banner-right-stats grid grid-cols-2 lg:grid-cols-4 gap-3.5 w-full lg:w-auto">

          <!-- 指标 1：活跃采集任务 -->
          <div class="stat-card bg-white/15 backdrop-blur-md border border-white/20 rounded-xl p-4 min-w-[150px] flex flex-col justify-between hover:bg-white/20 transition-all shadow-xs">
            <div class="flex items-center justify-between text-xs text-white/90 font-medium">
              <span>活跃采集任务</span>
              <svg class="w-4 h-4 text-white/80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div class="flex items-baseline gap-1 mt-2.5 mb-1.5">
              <span class="text-2xl font-black tracking-tight text-white font-mono">{{ isCrawling ? '1' : '0' }}</span>
              <span class="text-xs text-white/80 font-medium">个</span>
            </div>
            <div class="text-[11px] text-white/85 flex items-center gap-1.5 mt-0.5">
              <span class="w-1.5 h-1.5 rounded-full bg-white" :class="{ 'animate-pulse': isCrawling }"></span>
              <span>{{ isCrawling ? '线程并发中' : '资源就绪待命' }}</span>
            </div>
          </div>

          <!-- 指标 2：今日已采集数据 -->
          <div class="stat-card bg-white/15 backdrop-blur-md border border-white/20 rounded-xl p-4 min-w-[160px] flex flex-col justify-between hover:bg-white/20 transition-all shadow-xs">
            <div class="flex items-center justify-between text-xs text-white/90 font-medium">
              <span>今日已采集数据</span>
              <svg class="w-4 h-4 text-white/80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s-8-1.79-8-4" />
              </svg>
            </div>
            <div class="flex items-baseline gap-1 mt-2.5 mb-1.5">
              <span class="text-2xl font-black tracking-tight text-white font-mono">{{ todayShows.toLocaleString() }}</span>
              <span class="text-xs text-white/80 font-medium">条</span>
            </div>
            <div class="text-[11px] text-white/85">
              库内总计 {{ totalShows.toLocaleString() }} 条
            </div>
          </div>

          <!-- 指标 3：采集成功率 -->
          <div class="stat-card bg-white/15 backdrop-blur-md border border-white/20 rounded-xl p-4 min-w-[150px] flex flex-col justify-between hover:bg-white/20 transition-all shadow-xs">
            <div class="flex items-center justify-between text-xs text-white/90 font-medium">
              <span>采集成功率</span>
              <svg class="w-4 h-4 text-white/80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div class="flex items-baseline gap-1 mt-2.5 mb-1.5">
              <span class="text-2xl font-black tracking-tight text-white font-mono">{{ computedSuccessRate }}</span>
              <span class="text-xs text-white/80 font-medium">%</span>
            </div>
            <div class="text-[11px] text-white/85">
              基于 {{ jobs.filter(j => ['succeeded', 'failed'].includes(j.state)).length }} 次历史任务
            </div>
          </div>

          <!-- 指标 4：冰拓剩余点数 -->
          <button
            type="button"
            class="stat-card bg-white/15 backdrop-blur-md border border-white/20 rounded-xl p-4 min-w-[150px] flex flex-col justify-between hover:bg-white/20 transition-all shadow-xs text-left disabled:cursor-wait"
            :disabled="bingtuoBalanceState === 'loading'"
            :title="bingtuoBalanceError || '点击刷新冰拓剩余点数'"
            @click="refreshBingtuoBalance"
          >
            <div class="flex items-center justify-between text-xs text-white/90 font-medium w-full">
              <span>冰拓剩余点数</span>
              <svg class="w-4 h-4 text-white/80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="9" stroke-width="2" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.5 9.5h6a2 2 0 0 1 0 4h-5a2 2 0 0 0 0 4h6M12 7v2.5M12 17.5V20" />
              </svg>
            </div>
            <div class="flex items-baseline gap-1 mt-2.5 mb-1.5">
              <span class="text-2xl font-black tracking-tight text-white font-mono">{{ bingtuoPointsDisplay }}</span>
              <span class="text-xs text-white/80 font-medium">点</span>
            </div>
            <div class="text-[11px] text-white/85 flex items-center gap-1.5 mt-0.5">
              <span
                class="w-1.5 h-1.5 rounded-full bg-white"
                :class="{ 'animate-pulse': bingtuoBalanceState === 'loading' }"
              ></span>
              <span>{{ bingtuoBalanceHint }}</span>
            </div>
          </button>

        </div>
      </div>
    </div>

    <!-- 2. 中部主控制区 (Middle Section - Task Console Full Width Row) -->
    <div class="middle-grid-container w-full shrink-0 mb-5">

      <!-- 任务控制台 (全宽单行) -->
      <div class="bg-white rounded-2xl p-6 border border-slate-200/80 shadow-sm flex flex-col gap-6">
        <div>
          <!-- Card Header -->
          <div class="flex items-center justify-between pb-4 border-b border-slate-100 mb-5">
            <div class="flex items-center gap-2 font-bold text-slate-800 text-base">
              <span class="font-mono font-bold text-lg" :style="{ color: 'var(--primary)' }">>_</span>
              <span>任务控制台</span>
            </div>
            <span class="text-xs text-slate-400 font-normal">配置采集目标平台、地域城市及执行参数</span>
          </div>

          <!-- Step 1: 选择目标演艺平台 (Platform) -->
          <div class="step-group mb-6">
            <div class="text-xs font-bold text-slate-700 mb-3">1. 选择目标演艺平台 (Platform)</div>
            <div class="segmented-control bg-slate-100/80 p-1.5 rounded-xl flex items-center gap-1.5 border border-slate-200/60">
              <Button
                variant="ghost"
                class="seg-btn flex-1 h-auto py-2 px-3 rounded-lg text-xs font-medium transition-all text-center cursor-pointer"
                :class="selectedPlatformTab === 'all' ? 'bg-white text-slate-900 font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                @click="setPlatformTab('all')"
              >
                全部平台 (All Platforms)
              </Button>
              <Button
                variant="ghost"
                class="seg-btn flex-1 h-auto py-2 px-3 rounded-lg text-xs font-medium transition-all text-center cursor-pointer"
                :class="selectedPlatformTab === 'damai' ? 'bg-white font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                :style="selectedPlatformTab === 'damai' ? { color: 'var(--primary)' } : {}"
                @click="setPlatformTab('damai')"
              >
                大麦网 (Damai)
              </Button>
              <Button
                variant="ghost"
                class="seg-btn flex-1 h-auto py-2 px-3 rounded-lg text-xs font-medium transition-all text-center cursor-pointer"
                :class="selectedPlatformTab === 'maoyan' ? 'bg-white text-slate-900 font-bold shadow-xs' : 'text-slate-400'"
                @click="setPlatformTab('maoyan')"
              >
                猫眼演出
              </Button>
              <Button
                variant="ghost"
                class="seg-btn flex-1 h-auto py-2 px-3 rounded-lg text-xs font-medium transition-all text-center cursor-pointer"
                :class="selectedPlatformTab === 'showstart' ? 'bg-white text-slate-900 font-bold shadow-xs' : 'text-slate-400'"
                @click="setPlatformTab('showstart')"
              >
                秀动ShowStart
              </Button>
            </div>

            <div v-if="selectedPlatformTab === 'showstart'" class="mt-4 p-3.5 bg-slate-50 border border-slate-200/80 rounded-xl text-xs text-slate-500 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                <span class="font-medium">秀动 ShowStart 平台采集接口正在适配中，暂未开放。</span>
              </div>
              <span class="text-[11px] font-semibold text-slate-400 px-2 py-0.5 rounded bg-slate-200/60">暂未开放</span>
            </div>

            <div v-if="selectedPlatformTab === 'damai'" class="mt-4 flex items-start gap-3">
              <span class="text-xs font-bold text-slate-500 shrink-0 leading-8">分类：</span>
              <div class="flex flex-wrap items-center gap-x-1.5 gap-y-2">
                <Button
                  type="button"
                  variant="ghost"
                  class="h-8 px-3 text-xs font-semibold transition-colors cursor-pointer"
                  :class="selectedDamaiCategory === 'all' ? 'text-white' : 'text-slate-700 hover:bg-slate-100'"
                  :style="selectedDamaiCategory === 'all' ? { backgroundColor: 'var(--primary)' } : {}"
                  @click="selectedDamaiCategory = 'all'"
                >
                  全部
                </Button>
                <Button
                  v-for="category in damaiCategories"
                  :key="category"
                  type="button"
                  variant="ghost"
                  class="h-8 px-3 text-xs font-semibold transition-colors cursor-pointer"
                  :class="selectedDamaiCategory === category ? 'text-white' : 'text-slate-700 hover:bg-slate-100'"
                  :style="selectedDamaiCategory === category ? { backgroundColor: 'var(--primary)' } : {}"
                  @click="selectedDamaiCategory = category"
                >
                  {{ category }}
                </Button>
              </div>
            </div>

            <div v-if="selectedPlatformTab === 'maoyan'" class="mt-4 flex items-start gap-3">
              <span class="text-xs font-bold text-slate-500 shrink-0 leading-8">分类：</span>
              <div class="flex flex-wrap items-center gap-x-1.5 gap-y-2">
                <Button
                  type="button"
                  variant="ghost"
                  class="h-8 px-3 text-xs font-semibold transition-colors cursor-pointer"
                  :class="selectedMaoyanCategory === 'all' ? 'text-white' : 'text-slate-700 hover:bg-slate-100'"
                  :style="selectedMaoyanCategory === 'all' ? { backgroundColor: 'var(--primary)' } : {}"
                  @click="selectedMaoyanCategory = 'all'"
                >
                  全部
                </Button>
                <Button
                  v-for="category in maoyanCategories"
                  :key="category"
                  type="button"
                  variant="ghost"
                  class="h-8 px-3 text-xs font-semibold transition-colors cursor-pointer"
                  :class="selectedMaoyanCategory === category ? 'text-white' : 'text-slate-700 hover:bg-slate-100'"
                  :style="selectedMaoyanCategory === category ? { backgroundColor: 'var(--primary)' } : {}"
                  @click="selectedMaoyanCategory = category"
                >
                  {{ category }}
                </Button>
              </div>
            </div>
          </div>

          <!-- Step 2: 选择目标地域城市 (Target Cities) -->
          <div class="step-group mb-5">
            <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div class="flex items-center gap-2">
                <span class="text-xs font-bold text-slate-700">2. 选择目标地域城市</span>
                <span class="text-[11px] text-slate-400 font-normal">共 {{ allFlatCities.length }} 市</span>
              </div>

              <div class="flex items-center gap-2.5">
                <!-- 搜索框 -->
                <div class="relative w-44">
                  <Input
                    type="text"
                    v-model="searchCityQuery"
                    placeholder="搜索城市..."
                    class="w-full bg-slate-50 border border-slate-200 text-slate-700 text-xs rounded-lg px-2.5 py-1 outline-none focus:border-[var(--primary)] focus:bg-white transition-all pr-6 h-8"
                  />
                  <span v-if="searchCityQuery" class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600 cursor-pointer" @click="searchCityQuery = ''">✕</span>
                </div>

                <Button
                  variant="link"
                  class="h-auto p-0 text-xs font-medium text-slate-400 hover:text-slate-600 cursor-pointer"
                  @click="selectedCities = []"
                >
                  重置
                </Button>
              </div>
            </div>

            <!-- 当前已选概况 -->
            <div class="flex items-center gap-2 mb-3 text-xs">
              <span class="text-slate-400 font-medium shrink-0">当前已选：</span>
              <span v-if="isAllSelected" class="px-2.5 py-0.5 rounded text-[11px] font-bold" :style="{ backgroundColor: 'var(--primary-light)', color: 'var(--primary)' }">🌐 全国全量 ({{ allFlatCities.length }} 市)</span>
              <span v-else-if="selectedCities.length === 0" class="text-slate-400 italic">未选择</span>
              <div v-else class="flex flex-wrap gap-1.5">
                <span v-for="c in selectedCities" :key="c" class="px-2.5 py-0.5 rounded text-[11px] font-bold" :style="{ backgroundColor: 'var(--primary-light)', color: 'var(--primary)' }">
                  {{ c }}
                </span>
              </div>
            </div>

            <!-- 按字母查找 快速索引定位条 (Alphabet Navigation Index) -->
            <div class="flex items-center gap-1.5 overflow-x-auto py-1.5 mb-3 text-[11px] font-medium custom-dark-scrollbar border-b border-slate-100">
              <span class="text-slate-400 font-bold shrink-0 mr-1">按字母查找:</span>
              <Button
                type="button"
                variant="ghost"
                class="h-auto px-2 py-0.5 rounded text-[11px] font-bold transition-all cursor-pointer shrink-0"
                :class="activeLetter === 'ALL' ? 'text-white shadow-2xs' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'"
                :style="activeLetter === 'ALL' ? { backgroundColor: 'var(--primary)' } : {}"
                @click="scrollToLetter('ALL')"
              >
                全部
              </Button>
              <Button
                type="button"
                variant="ghost"
                class="h-auto px-2 py-0.5 rounded text-[11px] font-bold transition-all cursor-pointer shrink-0"
                :class="activeLetter === 'HOT' ? 'text-white shadow-2xs' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'"
                :style="activeLetter === 'HOT' ? { backgroundColor: 'var(--primary)' } : {}"
                @click="scrollToLetter('HOT')"
              >
                热门
              </Button>
              <Button
                v-for="letter in alphabetLetters"
                :key="letter"
                type="button"
                variant="ghost"
                class="h-auto px-1.5 py-0.5 rounded text-[11px] font-mono font-bold transition-all cursor-pointer shrink-0"
                :class="activeLetter === letter ? 'text-white shadow-2xs' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'"
                :style="activeLetter === letter ? { backgroundColor: 'var(--primary)' } : {}"
                @click="scrollToLetter(letter)"
              >
                {{ letter }}
              </Button>
            </div>

            <!-- 固定高度的独立滚动视口，字母索引只滚动这里，不带动整个页面 -->
            <ScrollArea
              ref="cityScrollAreaRef"
              class="h-[360px] rounded-xl border border-slate-200/60 bg-slate-50/70"
            >
              <div class="space-y-3 p-3 pr-5">
                <!-- "全国全量" 快捷单选按钮 -->
                <!-- <div v-if="!searchCityQuery && activeLetter === 'ALL'" class="flex items-center gap-2 pb-2 border-b border-slate-200/50">
                  <span class="text-[11px] font-bold text-slate-400 w-16 shrink-0">快捷选</span>
                  <Button
                    variant="outline"
                    class="h-auto px-3 py-1 rounded-lg border text-xs font-semibold transition-all cursor-pointer"
                    :class="isAllSelected ? 'shadow-xs font-semibold' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-100'"
                    :style="isAllSelected ? {
                      backgroundColor: 'var(--primary-light, #fde8f3)',
                      borderColor: 'var(--primary-border, #f9a8d4)',
                      color: 'var(--primary)'
                    } : {}"
                    @click="selectCity('全部')"
                  >
                    🌐 全国全量 (所有 {{ allFlatCities.length }} 城市)
                  </Button>
                </div> -->

                <!-- 1. 热门城市分组 -->
                <div
                  v-if="filteredHotCities.length > 0"
                  id="city-group-HOT"
                  class="region-block space-y-2 pb-2 border-b border-slate-200/40"
                >
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-bold text-slate-800 flex items-center gap-1">
                      <span class="text-pink-500">🔥</span> 热门城市
                    </span>
                    <span class="text-[10px] text-slate-400 font-mono">({{ filteredHotCities.length }})</span>
                  </div>
                  <div class="flex flex-wrap gap-2 pl-0.5">
                    <Button
                      v-for="c in filteredHotCities"
                      :key="'hot-' + c"
                      variant="outline"
                      class="city-chip h-auto px-2.5 py-1 rounded-lg border text-xs font-medium transition-all cursor-pointer"
                      :class="selectedCities.includes(c) ? 'shadow-xs font-semibold' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-100'"
                      :style="selectedCities.includes(c) ? {
                        backgroundColor: 'var(--primary-light, #fde8f3)',
                        borderColor: 'var(--primary-border, #f9a8d4)',
                        color: 'var(--primary)'
                      } : {}"
                      @click="selectCity(c)"
                    >
                      {{ c }}
                    </Button>
                  </div>
                </div>

                <!-- 2. 按 A-Z 拼音字母分类渲染城市 -->
                <template v-for="g in groupedAlphabetCategories" :key="g.letter">
                  <div :id="`city-group-${g.letter}`" class="region-block space-y-2">
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-mono font-black text-slate-700 bg-slate-200/70 px-2 py-0.5 rounded-md">{{ g.letter }}</span>
                      <span class="text-[10px] text-slate-400 font-mono">({{ g.matchingCities.length }})</span>
                    </div>
                    <div class="flex flex-wrap gap-2 pl-0.5">
                      <Button
                        v-for="c in g.matchingCities"
                        :key="g.letter + '-' + c"
                        variant="outline"
                        class="city-chip h-auto px-2.5 py-1 rounded-lg border text-xs font-medium transition-all cursor-pointer"
                        :class="selectedCities.includes(c) ? 'shadow-xs font-semibold' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-100'"
                        :style="selectedCities.includes(c) ? {
                          backgroundColor: 'var(--primary-light, #fde8f3)',
                          borderColor: 'var(--primary-border, #f9a8d4)',
                          color: 'var(--primary)'
                        } : {}"
                        @click="selectCity(c)"
                      >
                        {{ c }}
                      </Button>
                    </div>
                  </div>
                </template>

                <!-- 搜索无匹配时的提示 -->
                <div v-if="filteredHotCities.length === 0 && groupedAlphabetCategories.length === 0" class="py-6 text-center text-xs text-slate-400">
                  未找到匹配“{{ searchCityQuery }}”的城市
                </div>
              </div>
            </ScrollArea>
          </div>

          <!-- Step 3: 执行参数融入目标地域城市底部 (Execution Parameters & Action Button) -->
          <div class="step-group pt-5 mt-5 border-t border-slate-100">
            <div class="flex items-center justify-between mb-3.5">
              <div class="flex items-center gap-2 font-bold text-slate-800 text-xs">
                <div class="w-6 h-6 rounded-lg flex items-center justify-center shrink-0" :style="{ color: 'var(--primary)', backgroundColor: 'var(--primary-light, #fde8f3)' }">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>
                  </svg>
                </div>
                <span>3. 执行参数与任务控制 (Execution Parameters)</span>
              </div>
              <span class="text-[11px] text-slate-400 font-normal">限制爬虫页数及自动重试策略</span>
            </div>

            <!-- 参数配置区 (双卡片 50-50 平行布局，精致瘦身) -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">

              <!-- 左卡片: 采集页数上限 -->
              <div class="bg-slate-50/80 rounded-xl py-2 px-3.5 border border-slate-200/60 flex items-center justify-between gap-3 flex-wrap sm:flex-nowrap">
                <span class="text-xs font-bold text-slate-700 shrink-0 flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full" :style="{ backgroundColor: 'var(--primary)' }"></span>
                  页数上限
                </span>

                <div class="flex items-center gap-2">
                  <div class="relative w-28 shrink-0">
                    <Input
                      type="number"
                      v-model="maxPagesInput"
                      min="1"
                      max="9999"
                      placeholder="全量"
                      class="w-full bg-white border border-slate-200 text-slate-800 font-semibold text-xs rounded-lg px-2.5 py-1 outline-none focus:border-[var(--primary)] focus:bg-white transition-all pr-7 text-center shadow-2xs h-7.5"
                    />
                    <span class="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] font-medium text-slate-400 pointer-events-none">页</span>
                  </div>

                  <!-- 快捷 preset 按钮 -->
                  <div class="flex items-center gap-0.5 bg-slate-200/50 p-0.5 rounded-lg shrink-0 border border-slate-200/60">
                    <Button
                      type="button"
                      variant="ghost"
                      class="h-6.5 px-2 rounded-md text-[11px] font-semibold transition-all cursor-pointer text-center"
                      :class="maxPagesInput === '' ? 'text-white font-bold shadow-2xs' : 'text-slate-500 hover:text-slate-800'"
                      :style="maxPagesInput === '' ? { backgroundColor: 'var(--primary)' } : {}"
                      @click="maxPagesInput = ''"
                    >
                      全量
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      class="h-6.5 px-2 rounded-md text-[11px] font-semibold transition-all cursor-pointer text-center"
                      :class="maxPagesInput === '3' ? 'text-white font-bold shadow-2xs' : 'text-slate-500 hover:text-slate-800'"
                      :style="maxPagesInput === '3' ? { backgroundColor: 'var(--primary)' } : {}"
                      @click="maxPagesInput = '3'"
                    >
                      3页
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      class="h-6.5 px-2 rounded-md text-[11px] font-semibold transition-all cursor-pointer text-center"
                      :class="maxPagesInput === '10' ? 'text-white font-bold shadow-2xs' : 'text-slate-500 hover:text-slate-800'"
                      :style="maxPagesInput === '10' ? { backgroundColor: 'var(--primary)' } : {}"
                      @click="maxPagesInput = '10'"
                    >
                      10页
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      class="h-6.5 px-2 rounded-md text-[11px] font-semibold transition-all cursor-pointer text-center"
                      :class="maxPagesInput === '50' ? 'text-white font-bold shadow-2xs' : 'text-slate-500 hover:text-slate-800'"
                      :style="maxPagesInput === '50' ? { backgroundColor: 'var(--primary)' } : {}"
                      @click="maxPagesInput = '50'"
                    >
                      50页
                    </Button>
                  </div>
                </div>
              </div>

              <!-- 右卡片: 失败任务自动重试 Switch -->
              <div class="bg-slate-50/80 rounded-xl py-2 px-3.5 border border-slate-200/60 flex items-center justify-between gap-3">
                <div>
                  <div class="text-xs font-bold text-slate-700 leading-tight">失败任务自动重试</div>
                  <div class="text-[10px] text-slate-400 leading-tight mt-0.5">开启后，请求失败将自动重试最多3次</div>
                </div>
                <Switch
                  v-model:checked="autoRetry"
                  :style="autoRetry ? { backgroundColor: 'var(--primary)', borderColor: 'transparent' } : {}"
                />
              </div>

            </div>

            <!-- 主任务启动按钮 (单独单行) -->
            <div class="w-full flex flex-col justify-center">
              <div v-if="submitError" class="text-xs text-red-500 font-medium mb-1.5 text-center">{{ submitError }}</div>
              <Button
                class="w-full h-auto py-3.5 px-5 rounded-2xl text-white font-bold text-xs sm:text-sm flex items-center justify-center gap-2 shadow-lg hover:shadow-xl hover:opacity-95 active:scale-[0.99] transition-all cursor-pointer"
                :style="{
                  backgroundColor: 'var(--primary)',
                  boxShadow: '0 6px 18px -4px var(--primary-shadow, rgba(235, 79, 154, 0.35))'
                }"
                :disabled="starting"
                @click="onEngineButton"
              >
                <template v-if="starting">
                  <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  <span>启动中...</span>
                </template>
                <template v-else-if="isCrawling">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12"/></svg>
                  <span>停止数据采集任务</span>
                </template>
                <template v-else>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  <span>开始数据采集任务</span>
                </template>
              </Button>
            </div>
          </div>

        </div>
      </div>

    </div>

    <!-- 3. 底部终端运行日志 (Bottom Live Stdout Terminal Window) -->
    <div class="terminal-card bg-[#181825] rounded-2xl border border-slate-800/80 overflow-hidden shadow-xl shrink-0 mb-6">
      <!-- Window Top Header Bar -->
      <div class="terminal-header px-4 py-3 bg-[#1e1e2e] border-b border-slate-800/60 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <!-- macOS 3 Window Dots -->
          <div class="flex items-center gap-1.5">
            <span class="w-3 h-3 rounded-full bg-[#ff5f56] inline-block"></span>
            <span class="w-3 h-3 rounded-full bg-[#ffbd2e] inline-block"></span>
            <span class="w-3 h-3 rounded-full bg-[#27c93f] inline-block"></span>
          </div>
          <span class="font-mono text-xs font-bold text-slate-300 tracking-wide">实时输出 - 运行日志</span>
        </div>

        <div class="flex items-center gap-3">
          <span class="flex items-center gap-1.5 text-[11px] font-bold text-emerald-400 font-mono">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            实时
          </span>
          <Button
            variant="ghost"
            class="h-auto px-2.5 py-1 rounded-md text-xs text-slate-300 bg-slate-800 hover:bg-slate-700 hover:text-white font-mono transition-all cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="exportingLogs || !activeJob || !activeJob.logs?.length"
            title="将当前任务的参数、结果和中文运行日志导出为 TXT"
            @click="exportCurrentTaskLogs"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            {{ exportingLogs ? '导出中…' : '导出' }}
          </Button>
          <Button
            variant="ghost"
            class="h-auto px-2.5 py-1 rounded-md text-xs text-slate-400 bg-slate-800 hover:bg-slate-700 hover:text-white font-mono transition-all cursor-pointer"
            @click="clearLogs"
          >
            清空
          </Button>
        </div>
      </div>

      <!-- Console Log Output Area -->
      <div class="relative">
        <div class="terminal-body p-4 font-mono text-xs text-slate-300 min-h-[160px] max-h-[260px] overflow-y-auto leading-relaxed space-y-1.5 custom-dark-scrollbar" ref="logConsoleEl" @scroll="handleLogConsoleScroll">
          <template v-if="displayLogs.length > 0">
            <div v-for="(l, i) in displayLogs" :key="i" class="log-line flex items-start gap-2.5">
              <span class="text-slate-500 shrink-0 font-normal">{{ l.time }}</span>
              <span
                class="px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 leading-none"
                :class="{
                  'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30': l.type === 'SUCCESS',
                  'bg-sky-500/20 text-sky-400 border border-sky-500/30': l.type === 'INFO',
                  'bg-amber-500/20 text-amber-400 border border-amber-500/30': l.type === 'WARN',
                  'bg-rose-500/20 text-rose-400 border border-rose-500/30': l.type === 'ERROR',
                  'bg-slate-700 text-slate-400': l.type === 'DEBUG'
                }"
              >
                {{ l.levelLabel || mapLogLevelLabel(l.type) }}
              </span>
              <span class="text-slate-200 font-normal break-all">{{ l.text }}</span>
            </div>
          </template>
          <template v-else>
            <div class="text-slate-600 text-xs py-8 text-center font-mono">
              [日志已清空] 启动新采集任务后自动刷出最新引擎运行日志
            </div>
          </template>
        </div>

        <!-- 向上翻阅日志时的快捷“恢复置底”按钮 -->
        <button
          v-if="isUserScrolledUpLogConsole"
          type="button"
          class="absolute right-6 bottom-4 px-2.5 py-1 rounded-full text-[11px] font-mono bg-slate-800/90 text-sky-400 hover:bg-slate-700 hover:text-white border border-sky-500/40 shadow-lg backdrop-blur-xs flex items-center gap-1 transition-all cursor-pointer z-10"
          @click="scrollToLogBottom"
        >
          <span>↓ 恢复自动置底</span>
        </button>
      </div>
    </div>

    <!-- 任务详情 Modal -->
    <Dialog v-model:open="showTaskDetailModal">
      <DialogContent class="max-w-md p-6 rounded-2xl bg-white dark:bg-slate-950">
        <DialogHeader class="border-b pb-3">
          <DialogTitle class="text-base font-bold flex items-center justify-between">
            <span>任务详细参数 (Task Details)</span>
            <span class="font-mono text-xs text-slate-500">{{ currentSelectedTaskDetail?.taskNo }}</span>
          </DialogTitle>
        </DialogHeader>

        <div v-if="currentSelectedTaskDetail" class="py-4 space-y-3 text-xs">
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">目标平台：</span>
            <span class="font-bold text-slate-800 dark:text-slate-200">{{ currentSelectedTaskDetail.platform }}</span>
          </div>
          <div v-if="currentSelectedTaskDetail.rawJob?.job?.sources?.length === 1" class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">{{ currentSelectedTaskDetail.rawJob.job.sources[0] === 'damai' ? '大麦分类：' : '猫眼分类：' }}</span>
            <span class="font-bold text-slate-800 dark:text-slate-200">{{ currentSelectedTaskDetail.category }}</span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">目标城市：</span>
            <span class="font-bold text-slate-800 dark:text-slate-200">{{ currentSelectedTaskDetail.city }}</span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">采集页数：</span>
            <span class="font-bold font-mono text-slate-800 dark:text-slate-200">{{ currentSelectedTaskDetail.pages }} 页/城</span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">运行状态：</span>
            <span class="status-pill-badge" :class="currentSelectedTaskDetail.state">
              {{ STATE_LABELS[currentSelectedTaskDetail.state] || currentSelectedTaskDetail.state }}
            </span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">入库：</span>
            <span class="font-mono font-bold text-pink-600 text-sm">{{ currentSelectedTaskDetail.count }} 条</span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">台账可见：</span>
            <span class="font-mono font-bold text-emerald-600 text-sm">{{ currentSelectedTaskDetail.ledgerVisibleCount }} 条</span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">隐藏展览休闲/体育：</span>
            <span class="font-mono font-bold text-amber-600 text-sm">{{ currentSelectedTaskDetail.ledgerHiddenCount }} 条</span>
          </div>
        </div>

        <DialogFooter class="pt-2 border-t">
          <Button variant="outline" class="w-full text-xs" @click="showTaskDetailModal = false">关闭窗口</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 人工介入过验证码提示 Modal -->
    <Dialog v-model:open="manualCaptchaModalOpen">
      <DialogContent class="max-w-md p-6 rounded-2xl bg-white dark:bg-slate-950 border-amber-500/30">
        <DialogHeader class="border-b pb-3">
          <DialogTitle class="text-base font-bold flex items-center gap-2 text-amber-600 dark:text-amber-400">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <span>需要人工介入过验证</span>
          </DialogTitle>
        </DialogHeader>

        <div class="py-4 space-y-3 text-sm">
          <p class="text-slate-700 dark:text-slate-300 leading-relaxed font-medium">
            {{ manualCaptchaReason }}
          </p>
          <div class="p-3 bg-amber-50 dark:bg-amber-950/40 rounded-xl border border-amber-200/60 dark:border-amber-900/50 text-xs text-amber-800 dark:text-amber-300 space-y-1.5">
            <div class="font-bold flex items-center gap-1.5">
              <span>💡 操作指引：</span>
            </div>
            <ol class="list-decimal list-inside space-y-1 text-slate-600 dark:text-slate-400">
              <li>请切换到已打开的 Playwright 浏览器窗口；</li>
              <li>在网页中手动拖动滑块完成安全验证；</li>
              <li>验证成功后，采集任务将自动恢复并继续运行。</li>
            </ol>
          </div>
        </div>

        <DialogFooter class="pt-3 border-t flex items-center justify-between gap-3">
          <Button variant="outline" class="text-xs text-slate-500 hover:text-red-600" @click="cancelCurrentCrawlFromModal">
            取消本次采集
          </Button>
          <Button class="text-xs bg-amber-600 hover:bg-amber-700 text-white font-bold" @click="dismissManualCaptchaModal">
            我知道了（前往浏览器）
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

  </div>
</template>

<style scoped>
/* 隐藏数字输入框默认上下调节按钮，防止与右侧 "页 / 城" 单位重叠 */
input[type=number]::-webkit-inner-spin-button,
input[type=number]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type=number] {
  -moz-appearance: textfield;
}

.custom-dark-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-dark-scrollbar::-webkit-scrollbar-track {
  background: #181825;
}
.custom-dark-scrollbar::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 4px;
}
.custom-dark-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #45475a;
}
</style>
