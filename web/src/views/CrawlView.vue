<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted, defineExpose } from 'vue'
import { api } from '../api'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { translateLogText } from '@/utils/logTranslator'
import { ScrollArea } from '@/components/ui/scroll-area'
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

// 2. 按大区分类的全国完整 34 省市 (354+ 城市)
const regionCategories = [
  {
    region: '🔥 热门 & 直辖市',
    provinces: [
      { name: '直辖市 & 特区', cities: ['北京', '上海', '天津', '重庆', '香港', '澳门'] },
      { name: '核心热门市', cities: ['广州', '深圳', '成都', '杭州', '武汉', '南京', '西安', '苏州', '长沙', '青岛', '宁波', '厦门', '福州', '合肥', '郑州', '昆明', '贵阳', '南昌'] }
    ]
  },
  {
    region: '🌊 华东地区',
    provinces: [
      { name: '浙江省', cities: ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴', '金华', '衢州', '舟山', '台州', '丽水', '义乌', '慈溪'] },
      { name: '江苏省', cities: ['南京', '苏州', '无锡', '常州', '南通', '扬州', '徐州', '连云港', '淮安', '盐城', '镇江', '泰州', '宿迁', '昆山', '江阴'] },
      { name: '山东省', cities: ['济南', '青岛', '淄博', '枣庄', '东营', '烟台', '潍坊', '济宁', '泰安', '威海', '日照', '临沂', '德州', '聊城', '滨州', '菏泽'] },
      { name: '福建省', cities: ['福州', '厦门', '莆田', '三明', '泉州', '漳州', '南平', '龙岩', '宁德', '晋江'] },
      { name: '安徽省', cities: ['合肥', '芜湖', '蚌埠', '淮南', '马鞍山', '淮北', '铜陵', '安庆', '黄山', '滁州', '阜阳', '宿州', '六安', '亳州', '池州', '宣城'] }
    ]
  },
  {
    region: '🌴 华南地区',
    provinces: [
      { name: '广东省', cities: ['广州', '深圳', '珠海', '佛山', '东莞', '中山', '惠州', '江门', '汕头', '湛江', '肇庆', '清远', '韶关', '河源', '梅州', '汕尾', '阳江', '茂名', '潮州', '揭阳', '云浮'] },
      { name: '广西壮族自治区', cities: ['南宁', '柳州', '桂林', '梧州', '北海', '防城港', '钦州', '贵港', '玉林', '百色', '贺州', '河池', '来宾', '崇左'] },
      { name: '海南省', cities: ['海口', '三亚', '三沙', '儋州', '文昌', '琼海', '万宁', '东方'] }
    ]
  },
  {
    region: '🏛️ 华北 & 中原',
    provinces: [
      { name: '河南省', cities: ['郑州', '开封', '洛阳', '平顶山', '安阳', '鹤壁', '新乡', '焦作', '濮阳', '许昌', '漯河', '南阳', '商丘', '信阳', '周口', '驻马店'] },
      { name: '湖北省', cities: ['武汉', '宜昌', '襄阳', '荆州', '黄石', '十堰', '孝感', '黄冈', '咸宁', '恩施', '随州', '鄂州', '荆门'] },
      { name: '湖南省', cities: ['长沙', '株洲', '湘潭', '衡阳', '邵阳', '岳阳', '常德', '张家界', '益阳', '郴州', '永州', '怀化', '娄底'] },
      { name: '河北省', cities: ['石家庄', '唐山', '秦皇岛', '邯郸', '邢台', '保定', '张家口', '承德', '沧州', '廊坊', '衡水', '雄安新区'] },
      { name: '山西省', cities: ['太原', '大同', '阳泉', '长治', '晋城', '朔州', '晋中', '运城', '忻州', '临汾', '吕梁'] }
    ]
  },
  {
    region: '🏔️ 西南 & 西北 & 东北',
    provinces: [
      { name: '四川省', cities: ['成都', '绵阳', '德阳', '宜宾', '泸州', '南充', '乐山', '自贡', '攀枝花', '达州', '遂宁', '内江', '眉山', '广安', '雅安', '巴中', '广元'] },
      { name: '陕西省', cities: ['西安', '铜川', '宝鸡', '咸阳', '渭南', '延安', '汉中', '榆林', '安康', '商洛'] },
      { name: '云南 / 贵州', cities: ['昆明', '曲靖', '玉溪', '保山', '昭通', '丽江', '贵阳', '遵义', '六盘水', '安顺'] },
      { name: '东北三省', cities: ['沈阳', '大连', '鞍山', '锦州', '长春', '吉林', '哈尔滨', '齐齐哈尔', '大庆', '牡丹江'] },
      { name: '西北/其它', cities: ['兰州', '西宁', '银川', '乌鲁木齐', '呼和浩特', '包头', '拉萨', '台北'] }
    ]
  }
]

// 摊平全国完整城市列表 (354+ 市)
const allFlatCities = computed(() => {
  const list = []
  regionCategories.forEach(reg => {
    reg.provinces.forEach(p => {
      p.cities.forEach(c => {
        if (!list.includes(c)) list.push(c)
      })
    })
  })
  return list
})

// 已选城市列表 (默认 ['北京'])
const selectedCities = ref(['北京'])
const searchCityQuery = ref('')

const isAllSelected = computed(() => {
  return selectedCities.value.length === 1 && selectedCities.value[0] === '全部'
})

// 按大区分类并支持关键词筛选的城市分组数据
const groupedRegionCategories = computed(() => {
  const query = searchCityQuery.value.trim().toLowerCase()
  return regionCategories.map(reg => {
    const cities = []
    reg.provinces.forEach(p => {
      p.cities.forEach(c => {
        if (!cities.includes(c)) cities.push(c)
      })
    })
    const matchingCities = query
      ? cities.filter(c => c.toLowerCase().includes(query))
      : cities

    return {
      region: reg.region,
      matchingCities
    }
  })
})

function toggleCity(city) {
  if (isAllSelected.value) {
    selectedCities.value = [city]
    return
  }
  const index = selectedCities.value.indexOf(city)
  if (index > -1) {
    selectedCities.value.splice(index, 1)
  } else {
    selectedCities.value.push(city)
  }
}

// 执行参数：采集页数上限 (空字符串 = 全量)
const maxPagesInput = ref('10')
const autoRetry = ref(true)

// 冰拓凭据检查状态
const bingtuoStatus = ref({ hasCredentials: false, username: '' })
const isCheckingBingtuo = ref(false)

// ---- 真实采集任务状态（对接后端 /api/crawl）----
const activeJob = ref(null)   // 当前/最近一次任务记录
const jobs = ref([])          // 历史任务列表
const totalShows = ref(0)     // 库内已采集演出总数
const todayShows = ref(0)     // 今日本地新增采集数据数
const starting = ref(false)
const submitError = ref('')
const logConsoleEl = ref(null)
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
    .map(s => (s === 'damai' ? '大麦网' : s === 'maoyan' ? '猫眼' : s))
    .join('/') || '大麦网'
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

    out.push({
      key: j.id || index,
      taskNo,
      city,
      platform: sourcesLabel(j.job?.sources),
      pages,
      state: j.state || 'succeeded',
      count: j.result?.show_count ?? 0,
      startTime,
      endTime,
      rawJob: j
    })
  }
  return out
})

// ---- 日志清空与复制 ----
const isLogCleared = ref(false)

function clearLogs() {
  isLogCleared.value = true
  triggerToast('✓ 已成功清空实时日志输出', 'success')
}

async function copyLogs() {
  if (displayLogs.value.length === 0) {
    triggerToast('当前没有可复制的日志内容', 'warn')
    return
  }
  const text = displayLogs.value.map(l => `[${l.time}] [${l.type}] ${l.text}`).join('\n')
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

function mapLogLevel(level) {
  const u = String(level || 'INFO').toUpperCase()
  if (u === 'WARNING' || u === 'WARN') return 'WARN'
  if (u === 'ERROR' || u === 'CRITICAL') return 'ERROR'
  if (u === 'DEBUG') return 'DEBUG'
  return 'INFO'
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
        time: formatLogTime(row.ts),
        text: translateLogText(row.text || '')
      })
    }
    return out
  }

  out.push({
    type: 'INFO',
    time: formatLogTime(j.started_at || j.created_at),
    text: `任务 ${j.id.slice(0, 8)} 状态=${STATE_LABELS[j.state] || j.state}，城市=${(j.job?.cities || []).join('、')}`
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
    if (el) el.scrollTop = el.scrollHeight
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
    activeJob.value = j
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
    await api.startCrawl({
      sources: selectedPlatforms.value,
      cities: citiesToSubmit,
      keywords: [],
      max_pages: maxPages,
      headed: true
    })
    const hint = isAllSelected.value ? '全国全量' : `${citiesToSubmit.length} 城`
    toast.success(`已启动采集（${hint} · 最多 ${maxPages || '全部'} 页/城）`)
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
  checkBingtuo()
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

defineExpose({ refreshTotal, refreshJobs, checkBingtuo })
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

        <!-- 右侧三大核心指标卡片 (系统主题透明 Glass Cards) -->
        <div class="banner-right-stats grid grid-cols-1 sm:grid-cols-3 gap-3.5 w-full lg:w-auto">
          
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

        </div>
      </div>
    </div>

    <!-- 2. 中部主控制区 (Middle Section - 2 Columns Grid) -->
    <div class="middle-grid-container grid grid-cols-1 lg:grid-cols-12 gap-5 shrink-0">
      
      <!-- 左列: >_ 任务控制台 (7 列) -->
      <div class="lg:col-span-7 bg-white rounded-2xl p-6 border border-slate-200/80 shadow-sm flex flex-col justify-between">
        <div>
          <!-- Card Header -->
          <div class="flex items-center justify-between pb-4 border-b border-slate-100 mb-5">
            <div class="flex items-center gap-2 font-bold text-slate-800 text-base">
              <span class="font-mono font-bold text-lg" :style="{ color: 'var(--primary)' }">>_</span>
              <span>任务控制台</span>
            </div>
            <span class="text-xs text-slate-400 font-normal">配置需要采集的物理及网络目标</span>
          </div>

          <!-- Step 1: 选择目标演艺平台 (Platform) -->
          <div class="step-group mb-6">
            <div class="text-xs font-bold text-slate-700 mb-3">1. 选择目标演艺平台 (Platform)</div>
            <div class="segmented-control bg-slate-100/80 p-1.5 rounded-xl flex items-center gap-1.5 border border-slate-200/60">
              <button 
                class="seg-btn flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-all text-center cursor-pointer"
                :class="selectedPlatformTab === 'all' ? 'bg-white text-slate-900 font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                @click="setPlatformTab('all')"
              >
                全部平台 (All Platforms)
              </button>
              <button 
                class="seg-btn flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-all text-center cursor-pointer"
                :class="selectedPlatformTab === 'damai' ? 'bg-white font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                :style="selectedPlatformTab === 'damai' ? { color: 'var(--primary)' } : {}"
                @click="setPlatformTab('damai')"
              >
                大麦网 (Damai)
              </button>
              <button 
                class="seg-btn flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-all text-center"
                :class="selectedPlatformTab === 'maoyan' ? 'bg-white text-slate-900 font-bold shadow-xs' : 'text-slate-400'"
                @click="setPlatformTab('maoyan')"
              >
                猫眼演出
              </button>
            </div>
          </div>

          <!-- Step 2: 选择目标地域城市 (Target Cities) -->
          <div class="step-group">
            <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div class="flex items-center gap-2">
                <span class="text-xs font-bold text-slate-700">2. 选择目标地域城市 (Target Cities)</span>
                <span class="text-[11px] text-slate-400 font-normal">全量 {{ allFlatCities.length }} 市</span>
              </div>

              <div class="flex items-center gap-2">
                <!-- 搜索框 -->
                <div class="relative w-40">
                  <input 
                    type="text" 
                    v-model="searchCityQuery" 
                    placeholder="搜索城市..." 
                    class="w-full bg-slate-50 border border-slate-200 text-slate-700 text-xs rounded-lg px-2.5 py-1 outline-none focus:border-[var(--primary)] focus:bg-white transition-all pr-6"
                  />
                  <span v-if="searchCityQuery" class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600 cursor-pointer" @click="searchCityQuery = ''">✕</span>
                </div>

                <button 
                  class="text-xs font-medium hover:underline cursor-pointer transition-colors"
                  :style="{ color: 'var(--primary)' }"
                  @click="selectedCities = ['全部']"
                >
                  全选
                </button>
                <span class="text-slate-300 text-xs">|</span>
                <button 
                  class="text-xs font-medium text-slate-400 hover:text-slate-600 cursor-pointer"
                  @click="selectedCities = []"
                >
                  重置
                </button>
              </div>
            </div>

            <!-- 当前已选概况 -->
            <div class="flex items-center gap-2 mb-2 text-xs">
              <span class="text-slate-400 font-medium shrink-0">当前已选：</span>
              <span v-if="isAllSelected" class="px-2 py-0.5 rounded text-[11px] font-bold" :style="{ backgroundColor: 'var(--primary-light)', color: 'var(--primary)' }">全国全量 (354+ 市)</span>
              <span v-else-if="selectedCities.length === 0" class="text-slate-400 italic">未选择</span>
              <div v-else class="flex flex-wrap gap-1 max-h-12 overflow-y-auto">
                <span v-for="c in selectedCities.slice(0, 15)" :key="c" class="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-700 border border-slate-200">
                  {{ c }}
                </span>
                <span v-if="selectedCities.length > 15" class="text-[11px] text-slate-400">等 {{ selectedCities.length }} 市</span>
              </div>
            </div>

            <!-- 使用 Shadcn UI ScrollArea 组件：按区域（华东、华南、华北中原等）分组渲染 -->
            <ScrollArea class="h-56 rounded-xl border border-slate-200/60 bg-slate-50/70 p-3">
              <div class="space-y-3.5 pr-2">
                <!-- "全国全量" 快捷按键 -->
                <div v-if="!searchCityQuery" class="flex items-center gap-2 pb-2 border-b border-slate-200/50">
                  <span class="text-[11px] font-bold text-slate-400 w-16 shrink-0">快捷选</span>
                  <button 
                    class="px-3 py-1 rounded-lg border text-xs font-semibold transition-all cursor-pointer"
                    :class="isAllSelected ? 'shadow-xs' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-100'"
                    :style="isAllSelected ? {
                      backgroundColor: 'var(--primary-light, #fde8f3)',
                      borderColor: 'var(--primary-border, #f9a8d4)',
                      color: 'var(--primary)'
                    } : {}"
                    @click="selectedCities = ['全部']"
                  >
                    🌐 全国全量 (所有 354+ 城市)
                  </button>
                </div>

                <!-- 按大区分类渲染城市 -->
                <template v-for="reg in groupedRegionCategories" :key="reg.region">
                  <div v-if="reg.matchingCities.length > 0" class="region-block space-y-1.5">
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-bold text-slate-700">{{ reg.region }}</span>
                      <span class="text-[10px] text-slate-400 font-mono">({{ reg.matchingCities.length }})</span>
                    </div>
                    <div class="flex flex-wrap gap-1.5 pl-0.5">
                      <button
                        v-for="c in reg.matchingCities"
                        :key="c"
                        class="city-chip px-2.5 py-1 rounded-lg border text-xs font-medium transition-all cursor-pointer"
                        :class="selectedCities.includes(c) ? 'shadow-xs font-semibold' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-100'"
                        :style="selectedCities.includes(c) ? {
                          backgroundColor: 'var(--primary-light, #fde8f3)',
                          borderColor: 'var(--primary-border, #f9a8d4)',
                          color: 'var(--primary)'
                        } : {}"
                        @click="toggleCity(c)"
                      >
                        {{ c }}
                      </button>
                    </div>
                  </div>
                </template>

                <!-- 搜索无匹配时的提示 -->
                <div v-if="groupedRegionCategories.every(r => r.matchingCities.length === 0)" class="py-8 text-center text-xs text-slate-400">
                  未找到匹配“{{ searchCityQuery }}”的城市
                </div>
              </div>
            </ScrollArea>
          </div>
        </div>
      </div>

      <!-- 右列: 执行参数 (5 列) -->
      <div class="lg:col-span-5 bg-white rounded-2xl p-6 border border-slate-200/80 shadow-sm flex flex-col justify-between">
        <div>
          <!-- Card Header -->
          <div class="flex items-center justify-between pb-4 border-b border-slate-100 mb-5">
            <div class="flex items-center gap-2 font-bold text-slate-800 text-base">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>
              </svg>
              <span>执行参数</span>
            </div>
            <span class="text-xs text-slate-400 font-normal">限制爬虫线程及范围</span>
          </div>

          <div class="space-y-4">
            <!-- 采集页数上限 (Max Pages) -->
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1.5">采集页数上限 (Max Pages)</label>
              <div class="relative">
                <input 
                  type="number" 
                  v-model="maxPagesInput" 
                  min="1" 
                  max="9999" 
                  placeholder="留空 = 采集全量页"
                  class="w-full bg-slate-50 border border-slate-200 text-slate-800 font-semibold text-xs rounded-xl px-3.5 py-2.5 outline-none focus:border-[var(--primary)] focus:bg-white transition-all pr-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
                <span class="absolute right-3.5 top-1/2 -translate-y-1/2 text-xs font-medium text-slate-400 pointer-events-none">页 / 城</span>
              </div>
              
              <!-- 快捷页数选项 -->
              <div class="flex items-center gap-1.5 mt-2 bg-slate-100/70 p-1 rounded-xl border border-slate-200/50">
                <button 
                  type="button" 
                  class="flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all cursor-pointer text-center"
                  :class="maxPagesInput === '' ? 'bg-white font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                  :style="maxPagesInput === '' ? { color: 'var(--primary)' } : {}"
                  @click="maxPagesInput = ''"
                >
                  全量
                </button>
                <button 
                  type="button" 
                  class="flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all cursor-pointer text-center"
                  :class="maxPagesInput === '3' ? 'bg-white font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                  :style="maxPagesInput === '3' ? { color: 'var(--primary)' } : {}"
                  @click="maxPagesInput = '3'"
                >
                  3 页
                </button>
                <button 
                  type="button" 
                  class="flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all cursor-pointer text-center"
                  :class="maxPagesInput === '10' ? 'bg-white font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                  :style="maxPagesInput === '10' ? { color: 'var(--primary)' } : {}"
                  @click="maxPagesInput = '10'"
                >
                  10 页
                </button>
                <button 
                  type="button" 
                  class="flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all cursor-pointer text-center"
                  :class="maxPagesInput === '50' ? 'bg-white font-bold shadow-xs' : 'text-slate-500 hover:text-slate-800'"
                  :style="maxPagesInput === '50' ? { color: 'var(--primary)' } : {}"
                  @click="maxPagesInput = '50'"
                >
                  50 页
                </button>
              </div>
            </div>

            <!-- 失败任务自动重试 Switch -->
            <div class="pt-2">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-xs font-bold text-slate-800">失败任务自动重试</div>
                  <div class="text-[11px] text-slate-400 mt-0.5">开启后，请求失败将尝试最多3次重试</div>
                </div>
                <label class="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" v-model="autoRetry" class="sr-only peer">
                  <div 
                    class="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all"
                    :class="autoRetry ? 'bg-[var(--primary)]' : 'bg-slate-200'"
                    :style="autoRetry ? { backgroundColor: 'var(--primary)' } : {}"
                  ></div>
                </label>
              </div>
            </div>
          </div>
        </div>

        <!-- Primary Action Button -->
        <div class="pt-6">
          <div v-if="submitError" class="text-xs text-red-500 font-medium mb-2">{{ submitError }}</div>
          <button 
            class="w-full py-3 px-4 rounded-xl text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg transition-all active:scale-[0.99] cursor-pointer"
            :style="{ 
              backgroundColor: 'var(--primary)',
              boxShadow: '0 8px 20px -4px var(--primary-shadow, rgba(235, 79, 154, 0.3))' 
            }"
            :disabled="starting"
            @click="onEngineButton"
          >
            <template v-if="starting">
              <span>启动中...</span>
            </template>
            <template v-else-if="isCrawling">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12"/></svg>
              <span>停止数据采集任务</span>
            </template>
            <template v-else>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>开始数据采集任务</span>
            </template>
          </button>
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
          <span class="font-mono text-xs font-bold text-slate-300 tracking-wide">LIVE STDOUT - 运行日志</span>
        </div>

        <div class="flex items-center gap-3">
          <span class="flex items-center gap-1.5 text-[11px] font-bold text-emerald-400 font-mono">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            LIVE
          </span>
          <button 
            class="px-2.5 py-1 rounded-md text-xs text-slate-400 bg-slate-800 hover:bg-slate-700 hover:text-white font-mono transition-all cursor-pointer"
            @click="clearLogs"
          >
            Clear
          </button>
        </div>
      </div>

      <!-- Console Log Output Area -->
      <div class="terminal-body p-4 font-mono text-xs text-slate-300 min-h-[160px] max-h-[260px] overflow-y-auto leading-relaxed space-y-1.5 custom-dark-scrollbar" ref="logConsoleEl">
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
              {{ l.type }}
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
            <span class="text-slate-500">入库演出数量：</span>
            <span class="font-mono font-bold text-pink-600 text-sm">{{ currentSelectedTaskDetail.count }} 条</span>
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
