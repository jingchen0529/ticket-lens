<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted, defineExpose } from 'vue'
import { api } from '../api'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { translateLogText } from '@/utils/logTranslator'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'

// 1. 目标平台 (目前仅开放大麦)
const selectedPlatforms = ref(['damai'])

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

// 核心热门城市
const hotCities = ['北京', '上海', '广州', '深圳', '成都', '杭州', '武汉', '南京', '重庆', '西安', '苏州', '长沙', '青岛', '天津']

// 已选城市列表 (单选模式，默认 '北京' 或 ['全部'])
const selectedCities = ref(['北京'])
const searchCityQuery = ref('')

// 采集页数：默认 '10' 页/城；空字符串 = 全部（跟大麦 totalPage）
const maxPagesInput = ref('10')

// 冰拓凭据检查状态
const bingtuoStatus = ref({ hasCredentials: false, username: '' })
const isCheckingBingtuo = ref(false)

// 计算全国所有城市总数 (354 市)
const allCitiesCount = computed(() => {
  let count = 0
  regionCategories.forEach(reg => {
    reg.provinces.forEach(p => {
      count += p.cities.length
    })
  })
  return count
})

const isAllSelected = computed(() => {
  return selectedCities.value.length === 1 && selectedCities.value[0] === '全部'
})

const isCityExpanded = ref(true)

// 摊平全国完整城市列表（供 Image 1 样式展示）
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

// 根据搜索词筛选城市
const filteredCities = computed(() => {
  if (!searchCityQuery.value.trim()) return []
  const query = searchCityQuery.value.trim().toLowerCase()
  const result = []
  regionCategories.forEach(reg => {
    reg.provinces.forEach(p => {
      p.cities.forEach(c => {
        if (c.toLowerCase().includes(query) && !result.includes(c)) {
          result.push(c)
        }
      })
    })
  })
  return result
})

function selectAllNational() {
  selectedCities.value = ['全部']
}

function selectHotCities() {
  selectedCities.value = ['北京']
}

function clearCities() {
  selectedCities.value = []
}

function toggleCity(city) {
  // 单选模式
  if (selectedCities.value.length === 1 && selectedCities.value[0] === city) {
    selectedCities.value = []
  } else {
    selectedCities.value = [city]
  }
}

// ---- 真实采集任务状态（对接后端 /api/crawl）----
const activeJob = ref(null)   // 当前/最近一次任务记录
const jobs = ref([])          // 历史任务列表
const totalShows = ref(0)     // 库内已采集演出总数
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

function statePillClass(state) {
  if (state === 'running' || state === 'succeeded') return 'running'
  if (state === 'pending') return 'pending'
  return 'failed'
}

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

// 对应截图标准列: 任务号 / 城市 / 平台 / 页数 / 状态 / 采集数量 / 开始时间 / 结束时间 / 操作
const taskRowsFormatted = computed(() => {
  const out = []
  if (jobs.value.length === 0) {
    return out
  }
  for (let index = 0; index < jobs.value.length; index++) {
    const j = jobs.value[index]
    const taskNo = `TASK-${j.id ? j.id.slice(0, 8).toUpperCase() : (20250727001 + index)}`
    const city = (j.job?.cities && j.job.cities.length) ? (j.job.cities.length > 2 ? `${j.job.cities[0]}等${j.job.cities.length}市` : j.job.cities.join('、')) : '全国'
    const pages = j.job?.max_pages === 0 ? '全部' : (j.job?.max_pages || 10)
    const startTime = j.started_at ? formatDateTime(j.started_at) : (j.created_at ? formatDateTime(j.created_at) : '2025-07-27 10:30:45')
    const endTime = j.finished_at ? formatDateTime(j.finished_at) : (j.state === 'running' ? '-' : '-')

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

const paginatedTaskRows = computed(() => {
  const start = (taskPage.value - 1) * taskPageSize.value
  return taskRowsFormatted.value.slice(start, start + taskPageSize.value)
})

const totalTaskPages = computed(() => {
  return Math.ceil(taskRowsFormatted.value.length / taskPageSize.value) || 1
})

function goToTaskPage(p) {
  if (p >= 1 && p <= totalTaskPages.value) {
    taskPage.value = p
    jumpPageInput.value = p
  }
}

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

const displayLogs = computed(() => {
  if (isLogCleared.value) return []
  return logs.value
})

const showTaskDetailModal = ref(false)
const currentSelectedTaskDetail = ref(null)

function viewTaskDetail(task) {
  currentSelectedTaskDetail.value = task
  showTaskDetailModal.value = true
}

const activeTaskCount = computed(
  () => jobs.value.filter(j => ['pending', 'running'].includes(j.state)).length
)

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

function mapLogLevel(level) {
  const u = String(level || 'INFO').toUpperCase()
  if (u === 'WARNING' || u === 'WARN') return 'WARN'
  if (u === 'ERROR' || u === 'CRITICAL') return 'ERROR'
  if (u === 'DEBUG') return 'DEBUG'
  return 'INFO'
}

// 实时日志
const logs = computed(() => {
  const out = []
  const j = activeJob.value
  if (!j) {
    out.push({ type: 'INFO', time: formatLogTime(), text: '等待采集任务… 点击左下角「开始采集」启动' })
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
    if (['pending', 'running'].includes(j.state)) {
      out.push({
        type: 'DEBUG',
        time: formatLogTime(),
        text: `状态=${STATE_LABELS[j.state] || j.state}（验证码/抓取细节见上方引擎日志）`
      })
    }
    return out
  }

  out.push({
    type: 'INFO',
    time: formatLogTime(j.started_at || j.created_at),
    text: `任务 ${j.id.slice(0, 8)} 状态=${STATE_LABELS[j.state] || j.state}，城市=${(j.job?.cities || []).join('、')}`
  })
  if (j.started_at) {
    out.push({ type: 'DEBUG', time: formatLogTime(j.started_at), text: `开始时间 ${j.started_at}` })
  }
  if (j.result) {
    out.push({
      type: 'INFO',
      time: formatLogTime(j.finished_at),
      text: `原始抓取 ${j.result.raw_count} 条，规范化入库 ${j.result.show_count} 条`
    })
    for (const [src, n] of Object.entries(j.result.by_source || {})) {
      out.push({ type: 'INFO', time: formatLogTime(j.finished_at), text: `来源 ${src}: ${n} 条` })
    }
  }
  const errs = j.error ? [j.error] : (j.result?.errors || [])
  for (const err of errs) {
    out.push({ type: 'ERROR', time: formatLogTime(j.finished_at), text: translateLogText(err) })
  }
  if (j.finished_at) {
    out.push({ type: 'INFO', time: formatLogTime(j.finished_at), text: `结束时间 ${j.finished_at}` })
  }
  return out
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

// 监测任务完成/终止，触发 Toast (首次打开软件/页面静默，不弹出历史 Toast)
watch(
  activeJob,
  (j) => {
    if (!j) return
    const key = `${j.id}:${j.state}`
    if (key === lastNotifiedJobIdState) return

    if (['succeeded', 'failed', 'cancelled'].includes(j.state)) {
      lastNotifiedJobIdState = key
      const imported = j.result?.show_count || 0
      const errCount = (j.result?.errors || []).length || (j.error ? 1 : 0)

      if (j.state === 'succeeded') {
        toast.success(`采集成功完成！已规范入库 ${imported} 条演出数据`)
      } else if (j.state === 'failed') {
        toast.error(`采集任务终止失败：${j.error || '引擎中断'}`)
      } else if (j.state === 'cancelled') {
        toast.warn(`采集任务已停止，成功入库 ${imported} 条演出数据`)
      }
    }
  },
  { deep: true }
)

// 统计卡片
const stat = computed(() => {
  const j = activeJob.value
  return {
    total: totalShows.value,
    lastImported: j?.result?.show_count ?? 0,
    state: j ? (STATE_LABELS[j.state] || j.state) : '空闲'
  }
})

async function refreshTotal() {
  try {
    const data = await api.listShows({ limit: 1, offset: 0 })
    totalShows.value = data.total || 0
  } catch (e) {
    // 忽略
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
      // 首次加载初始化静态任务标识，静默屏蔽历史已完成 Toast
      lastNotifiedJobIdState = `${j.id}:${j.state}`
      isFirstLoad = false
    }
  } catch (e) {
    // 忽略
  }
}

function resolveMaxPages() {
  const raw = String(maxPagesInput.value ?? '').trim()
  if (!raw) return 0 // 0 = 后端全量
  const n = parseInt(raw, 10)
  if (!Number.isFinite(n) || n < 0) {
    return null // 非法
  }
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

  // 提交时校验冰拓凭据，若未配置则阻止提交并弹窗提示
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
      max_pages: maxPages, // 0=全部，正整数=上限
      headed: true
    })
    const pagesHint = maxPages === 0 ? '全部页' : `${maxPages} 页`
    const citiesCountHint = selectedCities.value.includes('全部') ? '全国全量' : `${citiesToSubmit.length} 城`
    toast.success(`已启动采集（${citiesCountHint} · 每城 ${pagesHint} · 含详情）`)
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
  <div class="crawl-view">

    <!-- 1. 最上方：采集任务配置 (Top Section) -->
    <div class="crawl-section top-section">
      <div class="config-panel">
        <div class="panel-header">
          <span class="panel-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
            采集任务配置
          </span>

          <div class="header-right-tools">
            <button class="btn-reset" @click="clearCities">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
              重置城市
            </button>
          </div>
        </div>

        <div class="config-content-body">
           <!-- 3. 红框区域：数据指标卡片 (独占一行！Image 2 需求) -->
          <div class="full-width-stats-row">
            <div class="stat-pill pink">
              <span class="lbl">采集任务（已采集演出）</span>
              <span class="val">{{ stat.total }} <small style="font-size:11px;font-weight:normal;color:#64748b;">条</small></span>
            </div>
            <div class="stat-pill blue">
              <span class="lbl">最近入库</span>
              <span class="val">{{ stat.lastImported }} <small style="font-size:11px;font-weight:normal;color:#64748b;">条</small></span>
            </div>
            <div class="stat-pill green">
              <span class="lbl">引擎状态</span>
              <span class="val" style="font-size:13px;">{{ stat.state }}</span>
            </div>
          </div>
          <!-- 1. 城市选择 (Image 1 样式) -->
          <div class="config-group city-section-group">
            <div class="city-clean-selector">
              <!-- Header Toolbar (Image 1) -->
              <div class="selector-top-toolbar">
                <div class="selected-status-left">
                   <span class="num">1</span>
                  <span class="lbl-prefix">当前选中城市</span>
                  <span v-if="isAllSelected" class="active-badge-pink">全部</span>
                  <span v-else-if="selectedCities.length === 0" class="badge-gray">未选择</span>
                  <div v-else class="selected-tags-inline">
                    <span v-for="c in selectedCities.slice(0, 10)" :key="c" class="selected-inline-tag">
                      {{ c }}
                    </span>
                    <span v-if="selectedCities.length > 10" class="more-cities-tag">
                      等 {{ selectedCities.length }} 市
                    </span>
                  </div>
                </div>

                <div class="topbar-controls-right">
                  <div class="city-search-input-wrap">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    <input 
                      type="text" 
                      v-model="searchCityQuery" 
                      placeholder="搜索城市..." 
                      class="city-search-input"
                    />
                    <span v-if="searchCityQuery" class="clear-search" @click="searchCityQuery = ''">✕</span>
                  </div>

                  <button class="btn-toggle-expand" @click="isCityExpanded = !isCityExpanded">
                    <span>{{ isCityExpanded ? '收起' : '展开' }}</span>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" :style="{ transform: isCityExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }"><polyline points="6 9 12 15 18 9"/></svg>
                  </button>
                </div>
              </div>

              <!-- 平铺城市 Chips 区域 (Image 1 样式) -->
              <div v-show="isCityExpanded" class="city-chips-grid-wrap">
                <span 
                  class="city-chip pink-all"
                  :class="{ active: isAllSelected }"
                  @click="isAllSelected ? clearCities() : selectAllNational()"
                >
                  全部
                </span>

                <span 
                  v-for="c in (searchCityQuery ? filteredCities : allFlatCities)"
                  :key="c"
                  class="city-chip"
                  :class="{ active: selectedCities.includes(c) }"
                  @click="toggleCity(c)"
                >
                  {{ c }}
                </span>
              </div>
            </div>
          </div>

          <!-- 2. 目标平台 -->
          <div class="config-group platform-full-card">
            <div class="group-title">
              <span class="num">2</span>
              <span>目标平台</span>
              <span class="platform-note">多平台支持</span>
            </div>
            
            <div class="platform-cards-grid">
              <!-- 大麦网 (已接入) -->
              <div class="platform-single-card active">
                <div class="p-brand">
                  <div class="p-logo damai-logo">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/></svg>
                  </div>
                  <div class="p-meta">
                    <div class="p-title">大麦网 <span class="p-domain">damai.cn</span></div>
                    <div class="p-sub">官方 API 就绪</div>
                  </div>
                </div>
                <div class="p-badge online">● 已接入</div>
              </div>

              <!-- 猫眼演出 (暂未开放 / 禁用) -->
              <div class="platform-single-card disabled" title="猫眼演出暂未开放选抓">
                <div class="p-brand">
                  <div class="p-logo maoyan-logo">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2.2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                  </div>
                  <div class="p-meta">
                    <div class="p-title">猫眼演出 <span class="p-domain">maoyan.com</span></div>
                    <div class="p-sub">对接中 · 敬请期待</div>
                  </div>
                </div>
                <div class="p-badge offline">○ 暂未开放</div>
              </div>
            </div>
          </div>

         

          <!-- 4. 采集页数与开始采集数据 合在一行 (快捷按键放在输入框右侧) -->
          <div class="pages-and-action-combined-row">
            <div class="pages-config-combined">
              <div class="group-title">
                <span class="num">3</span>
                <span>采集页数</span>
                <span class="platform-note">单城独立翻页</span>
              </div>

              <div class="pages-input-inline-bar">
                <div class="pages-input-wrap">
                  <input
                    v-model="maxPagesInput"
                    type="number"
                    min="1"
                    max="9999"
                    step="1"
                    placeholder="留空 = 全部页"
                    class="pages-input"
                  />
                  <span class="pages-unit">页 / 城</span>
                </div>

                <!-- 预设快捷键在输入框右侧！ -->
                <div class="pages-presets-right">
                  <button type="button" class="preset-btn" :class="{ active: maxPagesInput === '' }" @click="maxPagesInput = ''">全部</button>
                  <button type="button" class="preset-btn" :class="{ active: maxPagesInput === '3' }" @click="maxPagesInput = '3'">3 页</button>
                  <button type="button" class="preset-btn" :class="{ active: maxPagesInput === '10' }" @click="maxPagesInput = '10'">10 页</button>
                  <button type="button" class="preset-btn" :class="{ active: maxPagesInput === '50' }" @click="maxPagesInput = '50'">50 页</button>
                </div>
              </div>
            </div>

            <!-- 开始采集按钮 (与采集页数合在一行) -->
            <div class="start-action-container">
              <div v-if="submitError" class="submit-error">{{ submitError }}</div>
              <button 
                class="btn-start"
                :class="{ running: isCrawling }"
                :disabled="starting"
                @click="onEngineButton"
              >
                <template v-if="starting">
                  <span>启动中...</span>
                </template>
                <template v-else-if="isCrawling">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12"/></svg>
                  <span>停止采集任务</span>
                </template>
                <template v-else>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  <span>开始采集数据</span>
                </template>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 2 & 3. 左右双列排版：左侧【爬取任务记录】+ 右侧【实时日志】 (与用户截图完全一致) -->
    <div class="crawl-section bottom-grid-row">
      <!-- 左侧：爬取任务记录 -->
      <div class="monitor-card tasks-card left-tasks-panel">
        <div class="card-header">
          <div class="header-title">
            <span class="font-bold text-slate-800 text-sm">爬取任务记录</span>
          </div>
        </div>

        <div class="table-wrap custom-table-scrollbar">
          <table class="monitor-table">
            <thead>
              <tr>
                <th>任务号</th>
                <th>城市</th>
                <th>平台</th>
                <th>页数</th>
                <th>状态</th>
                <th>采集数量</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th class="text-center col-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="taskRowsFormatted.length === 0">
                <td colspan="9" style="text-align:center; color:#94a3b8; padding:40px 0;">
                  暂无任务记录
                </td>
              </tr>
              <tr v-for="t in paginatedTaskRows" :key="t.key">
                <td class="font-mono text-xs text-slate-700 font-semibold whitespace-nowrap">{{ t.taskNo }}</td>
                <td class="whitespace-nowrap">{{ t.city }}</td>
                <td class="whitespace-nowrap"><span class="platform-name-tag">{{ t.platform }}</span></td>
                <td class="font-mono whitespace-nowrap">{{ t.pages }}</td>
                <td class="whitespace-nowrap">
                  <span class="status-pill-badge" :class="t.state">
                    {{ STATE_LABELS[t.state] || t.state }}
                  </span>
                </td>
                <td class="font-mono font-bold text-slate-700 whitespace-nowrap">{{ t.count }}</td>
                <td class="text-xs text-slate-500 font-mono whitespace-nowrap">{{ t.startTime }}</td>
                <td class="text-xs text-slate-500 font-mono whitespace-nowrap">{{ t.endTime }}</td>
                <td class="text-center col-action whitespace-nowrap">
                  <button class="btn-action-detail" @click="viewTaskDetail(t)">
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 底部 Pagination 分页器 -->
        <div class="table-footer-bar">
          <span class="footer-count">共 {{ taskRowsFormatted.length }} 条</span>
          
          <div class="pagination-controls-bar">
            <select v-model="taskPageSize" class="page-select" @change="taskPage = 1">
              <option :value="5">5条/页</option>
              <option :value="10">10条/页</option>
              <option :value="20">20条/页</option>
            </select>
            
            <div class="pg-buttons">
              <button class="pg-arrow" :disabled="taskPage <= 1" @click="goToTaskPage(taskPage - 1)">‹</button>
              <button 
                v-for="p in totalTaskPages" 
                :key="p" 
                class="pg-num"
                :class="{ active: p === taskPage }"
                @click="goToTaskPage(p)"
              >
                {{ p }}
              </button>
              <button class="pg-arrow" :disabled="taskPage >= totalTaskPages" @click="goToTaskPage(taskPage + 1)">›</button>
            </div>

            <div class="page-jump-wrap">
              <span>前往</span>
              <input type="number" v-model.number="jumpPageInput" min="1" :max="totalTaskPages" class="jump-input" @keyup.enter="goToTaskPage(jumpPageInput)" />
              <span>页</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：实时日志 (带清空和复制按钮) -->
      <div class="monitor-card log-card right-log-panel">
        <div class="card-header dark">
          <div class="header-title">
            <span class="font-bold text-white text-sm">实时日志</span>
          </div>
          
          <div class="log-actions-bar">
            <button class="btn-log-action clear" @click="clearLogs" title="清空所有当前打印日志">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              <span>清空日志</span>
            </button>
            <button class="btn-log-action copy" @click="copyLogs" title="一键复制日志文本到剪贴板">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <span>复制日志</span>
            </button>
          </div>
        </div>

        <div class="log-console custom-table-scrollbar" ref="logConsoleEl">
          <template v-if="displayLogs.length > 0">
            <div v-for="(l, i) in displayLogs" :key="i" class="log-line">
              <span class="log-time">[{{ l.time }}]</span>
              <span :class="['log-level', l.type.toLowerCase()]">[{{ l.type }}]</span>
              <span class="log-content">{{ l.text }}</span>
            </div>
          </template>
          <template v-else>
            <div class="log-empty-tip">
              [日志已清空] 启动新采集任务后自动刷新最新引擎运行日志
            </div>
          </template>
        </div>
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
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">启动时间：</span>
            <span class="font-mono text-slate-700 dark:text-slate-300">{{ currentSelectedTaskDetail.startTime }}</span>
          </div>
          <div class="flex items-center justify-between border-b pb-2">
            <span class="text-slate-500">结束时间：</span>
            <span class="font-mono text-slate-700 dark:text-slate-300">{{ currentSelectedTaskDetail.endTime }}</span>
          </div>
        </div>

        <DialogFooter class="pt-2 border-t">
          <Button variant="outline" class="w-full text-xs" @click="showTaskDetailModal = false">关闭窗口</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

  </div>
</template>

<style scoped>
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

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -20px);
}

.crawl-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  width: 100%;
  overflow-y: auto;
  padding: 12px 16px;
  background-color: #f1f5f9;
}

.crawl-section {
  width: 100%;
}

.config-panel {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.config-content-body {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.config-middle-row {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
  align-items: start;
}

.stats-card-group {
  display: flex;
  gap: 8px;
}

.pages-and-action-combined-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  background: linear-gradient(135deg, var(--primary-light-bg, #fdf2f8) 0%, #ffffff 60%);
  border-radius: 10px;
  padding: 14px 16px;
  border: 1px solid var(--primary-border, #f0abca);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.pages-config-combined {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}

.pages-input-inline-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.pages-presets-right {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 3px;
}

/* 采集页数预设分段按钮 */
.preset-btn {
  height: 28px;
  padding: 0 14px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.preset-btn:hover {
  color: var(--primary);
}

.preset-btn.active {
  background: #ffffff;
  color: var(--primary);
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}

.start-action-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.full-width-stats-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  width: 100%;
}

.stat-pill {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

.stat-pill.pink { border-top: 3px solid var(--primary); }
.stat-pill.blue { border-top: 3px solid #3b82f6; }
.stat-pill.green { border-top: 3px solid #10b981; }

.stat-pill .lbl {
  font-size: 11.5px;
  color: #64748b;
  font-weight: 600;
}

.stat-pill .val {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.city-section-group {
  flex: 1;
}

.start-action-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.header-right-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-header {
  height: 38px;
  padding: 0 12px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
  flex-shrink: 0;
}

.panel-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-reset {
  background: transparent;
  border: none;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 3px;
}
.btn-reset:hover { color: var(--primary); }

.pages-config-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pages-input-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 4px;
  flex: 1;
  min-width: 200px;
  transition: all 0.15s;
}

.pages-input-wrap:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}

.pages-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  outline: none;
  min-width: 0;
  width: 100%;
}

.pages-input::placeholder {
  color: #94a3b8;
  font-weight: 500;
}

.pages-unit {
  font-size: 11px;
  color: #64748b;
  flex-shrink: 0;
  white-space: nowrap;
}

.pages-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pages-hint {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.45;
  color: #64748b;
}

.pages-hint code {
  font-size: 10.5px;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
  color: #475569;
}

.config-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
}

.group-title .num {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.platform-note {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--primary);
  background: var(--primary-light);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.selected-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--primary);
  font-weight: 600;
}

.platform-cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.platform-single-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 8px;
  transition: all 0.2s;
}

.platform-single-card.active {
  background: var(--primary-light);
  border: 1px solid var(--primary);
}

.platform-single-card.disabled {
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  opacity: 0.75;
  cursor: not-allowed;
  user-select: none;
}

.p-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.p-logo {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 3px var(--primary-shadow);
}

.p-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.p-domain {
  font-size: 10.5px;
  color: var(--primary);
  font-family: monospace;
  margin-left: 4px;
}

.p-sub {
  font-size: 10.5px;
  color: #64748b;
}

.p-badge.online {
  font-size: 10.5px;
  color: #047857;
  background: #ecfdf5;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
  border: 1px solid #a7f3d0;
}

.p-badge.offline {
  font-size: 10.5px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
  border: 1px solid #cbd5e1;
}

.city-clean-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  overflow: hidden;
}

.selector-top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.selected-status-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.lbl-prefix {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}

.active-badge-pink {
  background: var(--primary, #eb4f9a);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.badge-gray {
  background: #e2e8f0;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.selected-tags-inline {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.selected-inline-tag {
  background: var(--primary-light);
  color: var(--primary);
  border: 1px solid var(--primary-border);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}

.more-cities-tag {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
}

.topbar-controls-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.city-search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.city-search-input-wrap svg {
  position: absolute;
  left: 10px;
}
.city-search-input {
  width: 180px;
  height: 28px;
  padding-left: 28px;
  padding-right: 20px;
  border: 1px solid #cbd5e1;
  border-radius: 20px;
  font-size: 11.5px;
  outline: none;
  background: #ffffff;
  transition: all 0.2s;
}
.city-search-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-light);
}

.btn-toggle-expand {
  background: transparent;
  border: none;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}
.btn-toggle-expand:hover {
  color: var(--primary);
  background: #f1f5f9;
}

.city-chips-grid-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  padding: 12px 14px;
  max-height: 180px;
  overflow-y: auto;
  background: #ffffff;
}

.city-chip.pink-all {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  font-weight: 700;
}

.city-chip.pink-all.active {
  background: var(--primary, #eb4f9a);
  color: #ffffff;
  border-color: var(--primary, #eb4f9a);
}

.active-selected-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: var(--primary-light);
  color: var(--primary);
  border: 1px solid var(--primary-border);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.remove-tag {
  cursor: pointer;
  font-weight: bold;
  font-size: 10px;
  color: var(--primary);
}
.remove-tag:hover { opacity: 0.8; }

.all-selected-banner {
  background: var(--primary-light);
  color: var(--primary);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  border: 1px solid var(--primary-border);
}

.search-results-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px;
  background: #ffffff;
  border: 1px solid var(--primary);
  border-radius: 6px;
}

.city-flat-list-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 140px;
  overflow-y: auto;
}

.region-flat-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.region-title-badge {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-light-bg);
  padding: 2px 8px;
  border-radius: 4px;
  width: fit-content;
  border-left: 3px solid var(--primary);
}

.provinces-vertical-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-left: 4px;
}

.prov-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  border-bottom: 1px dashed #f1f5f9;
  padding-bottom: 4px;
}

.prov-name-lbl {
  font-size: 10.5px;
  font-weight: 700;
  color: #64748b;
  margin-top: 2px;
}

.city-chips-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.city-chip {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #334155;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
}

.city-chip:hover {
  background: var(--primary-light-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

.city-chip.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
  font-weight: 700;
  box-shadow: 0 1px 3px var(--primary-shadow);
}

.check-mark {
  font-size: 10px;
  margin-left: 2px;
}

.submit-error {
  font-size: 11.5px;
  color: #dc2626;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 5px 8px;
}

.btn-start {
  width: 100%;
  height: 40px;
  background: var(--primary);
  color: #ffffff;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  box-shadow: 0 2px 6px var(--primary-shadow);
  transition: all 0.2s;
}

.btn-start:hover {
  background: var(--primary-hover);
  transform: translateY(-1px);
}

.btn-start.running {
  background: #ef4444;
  box-shadow: 0 2px 6px rgba(239, 68, 68, 0.3);
}

.stat-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stat-card.pink { border-left: 4px solid var(--primary); }
.stat-card.blue { border-left: 4px solid #3b82f6; }
.stat-card.green { border-left: 4px solid #10b981; }

.stat-meta {
  display: flex;
  flex-direction: column;
}

.stat-title {
  font-size: 11px;
  color: #64748b;
}

.stat-sub {
  font-size: 10px;
  color: #94a3b8;
}

.stat-num {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.monitor-card {
  background: #ffffff;
  border-radius: 12px;
  border: 1px solid #cbd5e1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.card-header {
  height: 44px;
  padding: 0 16px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
  shrink: 0;
}

.card-header.dark {
  background: #0f172a;
  color: #f8fafc;
  border-bottom: 1px solid #1e293b;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.header-badge {
  font-size: 11px;
  background: #e2e8f0;
  color: #475569;
  padding: 2px 8px;
  border-radius: 6px;
}

.live-dot {
  font-size: 11px;
  color: #4ade80;
  font-weight: 700;
}

.table-wrap {
  flex: 1;
  min-height: 380px;
  overflow-y: auto;
  overflow-x: auto;
}

.table-footer-bar {
  height: 42px;
  padding: 0 16px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #64748b;
  flex-shrink: 0;
}

.monitor-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.monitor-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
}

.monitor-table td {
  padding: 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
  vertical-align: middle;
}

.col-action {
  min-width: 90px !important;
  width: 90px !important;
  white-space: nowrap !important;
}

.font-mono {
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
}

/* ---- 左右双列网格布局 (高度拉大至 480px) ---- */
.bottom-grid-row {
  display: flex;
  flex-direction: row;
  gap: 16px;
  width: 100%;
  align-items: stretch;
  min-height: 460px;
}

@media (max-width: 1024px) {
  .bottom-grid-row {
    flex-direction: column;
  }
}

.left-tasks-panel {
  flex: 3.2;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 460px;
}

.right-log-panel {
  flex: 2;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 460px;
}

/* 状态徽章 */
.status-pill-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 12px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
}

.status-pill-badge.succeeded {
  background-color: #dcfce7;
  color: #15803d;
}

.status-pill-badge.running {
  background-color: #dbeafe;
  color: #1d4ed8;
}

.status-pill-badge.failed, .status-pill-badge.cancelled {
  background-color: #ffe4e6;
  color: #be123c;
}

.status-pill-badge.pending {
  background-color: #fef3c7;
  color: #b45309;
}

.platform-name-tag {
  color: #475569;
  font-weight: 600;
}

.btn-action-detail {
  color: var(--primary, #eb4f9a);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  background: none;
  border: none;
  padding: 0;
  white-space: nowrap;
  transition: color 0.15s;
}

.btn-action-detail:hover {
  text-decoration: underline;
  color: var(--primary-hover, #d83b87);
}

/* 分页器组件控制条 */
.pagination-controls-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-select {
  height: 26px;
  padding: 0 6px;
  font-size: 11.5px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #475569;
  outline: none;
}

.pg-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}

.pg-arrow, .pg-num {
  height: 26px;
  min-width: 26px;
  padding: 0 6px;
  font-size: 11.5px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  color: #475569;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.pg-num.active {
  background: var(--primary, #eb4f9a);
  border-color: var(--primary, #eb4f9a);
  color: #ffffff;
  font-weight: 700;
  box-shadow: 0 1px 4px var(--primary-shadow, rgba(235, 79, 154, 0.25));
}

.pg-arrow:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-jump-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: #64748b;
}

.jump-input {
  width: 36px;
  height: 26px;
  text-align: center;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 11.5px;
  outline: none;
}

/* 日志控制台与工具按钮 (清空/复制) */
.log-card {
  height: 100%;
}

.log-console {
  flex: 1;
  min-height: 380px;
  background: #020617;
  color: #f1f5f9;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.75;
  padding: 14px 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.log-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.log-time {
  color: #64748b;
  flex-shrink: 0;
  white-space: nowrap;
  font-family: 'JetBrains Mono', Consolas, monospace;
}

.log-level {
  flex-shrink: 0;
  white-space: nowrap;
  font-weight: 700;
  font-family: 'JetBrains Mono', Consolas, monospace;
}

.log-level.info { color: #38bdf8; }
.log-level.warn { color: #fbbf24; }
.log-level.error { color: #f87171; }
.log-level.debug { color: #c084fc; }

.log-content {
  color: #f1f5f9;
  flex: 1;
  min-width: 0;
  word-break: break-all;
  overflow-wrap: anywhere;
}

.log-actions-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-log-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  font-size: 11.5px;
  border-radius: 6px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 600;
}

.btn-log-action:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.btn-log-action.clear {
  border-color: #fca5a5;
  color: #ef4444;
  background: #ffffff;
}

.btn-log-action.clear:hover {
  background: #fef2f2;
  border-color: #f87171;
}

.log-empty-tip {
  color: #64748b;
  font-size: 12px;
  text-align: center;
  padding: 80px 12px;
}

.status-pill {
  font-size: 10.5px;
  font-weight: 600;
}
.status-pill.running { color: #059669; }
.status-pill.pending { color: #d97706; }
.status-pill.failed { color: #dc2626; }

.log-card {
  height: 180px;
}

.log-console {
  flex: 1;
  height: 145px;
  background: #020617;
  color: #e2e8f0;
  font-family: monospace;
  font-size: 11px;
  padding: 8px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.log-line {
  display: flex;
  gap: 8px;
  line-height: 1.4;
}

.log-time { color: #64748b; }
.log-level.info { color: #38bdf8; }
.log-level.warn { color: #fbbf24; }
.log-level.error { color: #f87171; }
.log-level.debug { color: #a78bfa; }
.log-content { color: #f1f5f9; word-break: break-all; }

.num {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
