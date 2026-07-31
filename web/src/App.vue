<script setup>
import { nextTick, ref, onMounted, watch } from 'vue'
import { Download } from 'lucide-vue-next'
import { api } from './api'
import { checkForUpdate } from './updater.js'
import CrawlView from './views/CrawlView.vue'
import ShowsView from './views/ShowsView.vue'
import SettingsView from './views/SettingsView.vue'
import Toaster from '@/components/ui/toast/Toaster.vue'

// 引入 shadcn UI 核心组件


// 当前激活页面: 'crawl' | 'shows' | 'settings'
const currentTab = ref('crawl')

const health = ref(null)
const healthError = ref('')

// 启动自动检查到的新版本（仅提示，安装在设置页操作）
const updateAvailableVersion = ref('')
let availableUpdate = null

// 主题配色配置 (默认 #eb4f9a)
const currentThemeColor = ref(localStorage.getItem('theme_color') || '#eb4f9a')

// CrawlView / ShowsView 组件引用
const crawlViewRef = ref(null)
const showsViewRef = ref(null)
const settingsViewRef = ref(null)

// 辅助工具：将 HEX 转为 RGBA 字符串
function hexToRgba(hex, alpha) {
  let c = hex.replace('#', '')
  if (c.length === 3) {
    c = c.split('').map(x => x + x).join('')
  }
  const num = parseInt(c, 16)
  if (isNaN(num)) return `rgba(235, 79, 154, ${alpha})`
  const r = (num >> 16) & 255
  const g = (num >> 8) & 255
  const b = num & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// 更改主题颜色
function handleThemeChange(colorHex, hoverHex = null) {
  currentThemeColor.value = colorHex
  const hover = hoverHex || colorHex
  const root = document.documentElement
  
  root.style.setProperty('--primary', colorHex)
  root.style.setProperty('--primary-hover', hover)
  root.style.setProperty('--primary-light', hexToRgba(colorHex, 0.12))
  root.style.setProperty('--primary-light-bg', hexToRgba(colorHex, 0.05))
  root.style.setProperty('--primary-border', hexToRgba(colorHex, 0.35))
  root.style.setProperty('--primary-shadow', hexToRgba(colorHex, 0.25))
  root.style.setProperty('--bg-header', colorHex)

  localStorage.setItem('theme_color', colorHex)
}

async function checkHealth() {
  try {
    health.value = await api.health()
    healthError.value = ''
  } catch (e) {
    health.value = null
    healthError.value = e.message || '后端连接失败'
  }
}

async function handleUpdatePillClick() {
  currentTab.value = 'settings'
  await nextTick()
  settingsViewRef.value?.openUpdatePanel?.(availableUpdate)
}

onMounted(() => {
  checkHealth()
  setInterval(checkHealth, 10000)
  handleThemeChange(currentThemeColor.value)
  // 启动后静默检查更新（延后几秒，避开启动时的后端拉起与首屏渲染）。
  // 只提示，不自动安装——安装由用户在设置页确认后触发。
  setTimeout(async () => {
    const update = await checkForUpdate()
    if (update) {
      availableUpdate = update
      updateAvailableVersion.value = update.version || ''
    }
  }, 4000)
})

// 标签页切换：设置→采集刷新冰拓；进入数据查询时重新拉库（v-show 不会 onMounted）
watch(currentTab, (newTab, oldTab) => {
  if (oldTab === 'settings' && newTab === 'crawl' && crawlViewRef.value?.checkBingtuoCredentials) {
    crawlViewRef.value.checkBingtuoCredentials()
  }
  if (newTab === 'shows' && showsViewRef.value?.refresh) {
    showsViewRef.value.refresh()
  }
})
</script>

<template>
  <div class="app-container">
    <!-- 全局 Shadcn UI Toast 提醒框容器 -->
    <Toaster />

    <!-- 极简 Header -->
    <header class="top-header">
      <div class="brand-area">
        <!-- Title / Logo -->
        <div class="brand-title">
          <span>演出数据采集</span>
        </div>
      </div>
      
      <!-- 中间胶囊 Tab 控制器 -->
      <div class="segmented-control">
        <button 
          class="segment-btn" 
          :class="{ active: currentTab === 'crawl' }"
          @click="currentTab = 'crawl'"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M12 12v9"/><path d="m8 17 4 4 4-4"/></svg>
          <span>数据采集</span>
        </button>

        <button 
          class="segment-btn" 
          :class="{ active: currentTab === 'shows' }"
          @click="currentTab = 'shows'"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
          <span>数据查询</span>
        </button>

        <button 
          class="segment-btn" 
          :class="{ active: currentTab === 'settings' }"
          @click="currentTab = 'settings'"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          <span>系统设置</span>
        </button>
      </div>

      <!-- 右侧 Action 区域 -->
      <div class="header-right-actions">
        <button
          v-if="updateAvailableVersion"
          class="update-pill"
          @click="handleUpdatePillClick"
          title="打开软件版本更新"
        >
          <Download :size="14" :stroke-width="2.2" aria-hidden="true" />
          <span>有新版本 v{{ updateAvailableVersion }}</span>
        </button>
      </div>
    </header>

    <!-- 中间全屏主体 -->
    <div class="main-body">
      <main class="content-area">
        <CrawlView v-show="currentTab === 'crawl'" ref="crawlViewRef" />
        <ShowsView v-show="currentTab === 'shows'" ref="showsViewRef" />
        <SettingsView
          v-show="currentTab === 'settings'"
          ref="settingsViewRef"
          :current-theme="currentThemeColor"
          @update-theme="handleThemeChange"
        />
      </main>
    </div>
  </div>
</template>
