<script setup>
import { ref, onMounted } from 'vue'
import { api, IN_TAURI } from '../api.js'
import { checkForUpdate, downloadAndInstall } from '../updater.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/toast'

const props = defineProps({
  currentTheme: {
    type: String,
    default: '#eb4f9a'
  }
})

const emit = defineEmits(['update-theme'])

// 当前选中的设置 Tab ('all' | 'bingtuo' | 'captcha' | 'theme' | 'update')
const activeTab = ref('all')

// 冰拓账号与密码
const bingtuoUser = ref('')
const bingtuoPass = ref('')
const fruitCaptchaType = ref('1358')
const showPassword = ref(false)

// 过码模式：auto=自动过码（打码平台/本地，失败人工兜底）| manual=手动过码（直接弹窗人工拖滑块）
const captchaMode = ref('auto')

// 冰拓剩余打码点数
const balance = ref(null)
const balanceError = ref('')
const balanceLoading = ref(false)

async function checkBalance() {
  if (balanceLoading.value) return
  balanceLoading.value = true
  balanceError.value = ''
  try {
    const data = await api.getBingtuoBalance()
    if (!data.configured) {
      balance.value = null
      balanceError.value = '请先填写并保存冰拓账号'
      toast.warn('请先填写并保存冰拓账号')
    } else if (data.error) {
      balance.value = null
      balanceError.value = data.error
      toast.error('查询余额异常: ' + data.error)
    } else {
      balance.value = data.points
      toast.success(`冰拓打码平台剩余可用点数：${data.points} 点`)
    }
  } catch (e) {
    balance.value = null
    balanceError.value = e.message || '查询失败'
    toast.error('查询余额失败: ' + (e.message || '网络连接中断'))
  } finally {
    balanceLoading.value = false
  }
}

// 主题色彩预设
const themeOptions = [
  { name: '冰拓粉', hex: '#eb4f9a', hover: '#d83b87' },
  { name: '极光紫', hex: '#8b5cf6', hover: '#7c3aed' },
  { name: '科技蓝', hex: '#3b82f6', hover: '#2563eb' },
  { name: '翡翠绿', hex: '#10b981', hover: '#059669' },
  { name: '活力橙', hex: '#f97316', hover: '#ea580c' },
  { name: '暗夜黑', hex: '#334155', hover: '#1e293b' }
]

const customHex = ref(props.currentTheme)

function selectTheme(theme) {
  customHex.value = theme.hex
  emit('update-theme', theme.hex, theme.hover)
}

function handleColorPickerInput(e) {
  const newColor = e.target.value
  customHex.value = newColor.toUpperCase()
  emit('update-theme', newColor, newColor)
}

function handleHexInputChange() {
  if (/^#[0-9A-Fa-f]{6}$/.test(customHex.value)) {
    emit('update-theme', customHex.value, customHex.value)
  }
}

const isSaving = ref(false)

function triggerToast(msg = '系统设置已保存成功！', type = 'success') {
  if (type === 'error' || msg.includes('失败')) toast.error(msg)
  else toast.success(msg)
}

// 加载设置
async function loadSettings() {
  try {
    const data = await api.getSettings()
    if (data.bingtuo) {
      bingtuoUser.value = data.bingtuo.username || ''
      bingtuoPass.value = data.bingtuo.password || ''
    }
    if (data.fruit_captcha_type) {
      fruitCaptchaType.value = String(data.fruit_captcha_type)
    }
    if (data.captcha_mode) {
      captchaMode.value = data.captcha_mode
    }
  } catch (e) {
    console.error('加载设置失败:', e)
  }
}

// 保存所有设置
async function saveAllSettings() {
  if (isSaving.value) return
  isSaving.value = true
  
  // 点击后 0 毫秒直接触发高优先级 Toast 反馈
  toast.success('系统设置已保存成功！')

  try {
    await api.updateSettings({
      bingtuo: {
        username: bingtuoUser.value,
        password: bingtuoPass.value
      },
      fruit_captcha_type: parseInt(fruitCaptchaType.value) || 1358,
      theme_color: customHex.value,
      captcha_mode: captchaMode.value
    })
  } catch (e) {
    console.error('保存设置失败:', e)
    toast.error('保存同步到后端失败: ' + (e.message || '网络连接异常'))
  } finally {
    isSaving.value = false
  }
}

// ---- 自动更新 ----
const IS_TAURI = IN_TAURI
// idle | checking | available | downloading | uptodate | error
const updateState = ref('idle')
const updateVersion = ref('')
const updateNotes = ref('')
const updateProgress = ref(0)
const updateError = ref('')
let pendingUpdate = null

async function handleCheckUpdate() {
  if (updateState.value === 'checking' || updateState.value === 'downloading') return
  updateState.value = 'checking'
  updateError.value = ''
  try {
    const update = await checkForUpdate({ showError: true })
    if (update) {
      pendingUpdate = update
      updateVersion.value = update.version || ''
      updateNotes.value = update.body || ''
      updateState.value = 'available'
    } else {
      updateState.value = 'uptodate'
    }
  } catch (e) {
    updateState.value = 'error'
    updateError.value = e.message || '检查更新失败'
  }
}

async function handleInstallUpdate() {
  if (!pendingUpdate || updateState.value === 'downloading') return
  updateState.value = 'downloading'
  updateProgress.value = 0
  try {
    await downloadAndInstall(pendingUpdate, (p) => { updateProgress.value = p })
  } catch (e) {
    updateState.value = 'error'
    updateError.value = e.message || '下载安装失败'
  }
}

onMounted(async () => {
  await loadSettings()
  if (bingtuoUser.value && bingtuoPass.value) {
    checkBalance()
  }
})
</script>

<template>
  <div class="settings-page w-full h-full p-4 sm:p-6 bg-slate-50/50 dark:bg-slate-950 flex flex-col min-h-0 overflow-hidden relative">

    <!-- 顶栏标题 Header Bar -->
    <div class="settings-top-bar flex items-center justify-between pb-4 mb-4 border-b border-slate-200/80 dark:border-slate-800 shrink-0">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-pink-100 dark:bg-pink-950/50 flex items-center justify-center text-pink-600 dark:text-pink-400 font-bold shadow-2xs" style="color: var(--primary)">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </div>
        <div>
          <h1 class="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">系统设置与偏好</h1>
          <p class="text-xs text-slate-500 dark:text-slate-400">配置第三方打码平台凭据、验证码过码逻辑与系统专属主题外观</p>
        </div>
      </div>

      <!-- 右侧快速保存按钮 -->
      <Button variant="default" class="btn-theme-primary px-5 h-9 text-xs font-semibold gap-2 shadow-sm" :disabled="isSaving" @click.stop.prevent="saveAllSettings">
        <svg v-if="!isSaving" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
        <span v-else class="loading-spinner small white"></span>
        <span>{{ isSaving ? '正在保存…' : '保存所有设置' }}</span>
      </Button>
    </div>

    <!-- 左右分栏 Split Container (充满剩余视口高度) -->
    <div class="settings-split-layout flex-1 min-h-0 flex gap-5 overflow-hidden">
      
      <!-- 左侧分类侧边栏 Left Sidebar (宽度 240px) -->
      <div class="sidebar-nav w-60 shrink-0 bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-3 flex flex-col justify-between shadow-2xs">
        
        <div class="space-y-1">
          <div class="px-3 py-2 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">设置导航</div>

          <button
            type="button"
            class="nav-tab-item w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all text-left"
            :class="activeTab === 'all' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 shadow-2xs border border-slate-200/60 dark:border-slate-700' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
            @click="activeTab = 'all'"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0" :style="activeTab === 'all' ? 'color: var(--primary)' : ''"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
            <span class="flex-1">全部配置总览</span>
          </button>

          <button
            type="button"
            class="nav-tab-item w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all text-left"
            :class="activeTab === 'bingtuo' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 shadow-2xs border border-slate-200/60 dark:border-slate-700' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
            @click="activeTab = 'bingtuo'"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0" :style="activeTab === 'bingtuo' ? 'color: var(--primary)' : ''"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
            <span class="flex-1">冰拓打码服务</span>
            <Badge v-if="balance !== null" variant="secondary" class="h-5 px-1.5 text-[10px] font-mono">{{ balance }}点</Badge>
          </button>

          <button
            type="button"
            class="nav-tab-item w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all text-left"
            :class="activeTab === 'captcha' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 shadow-2xs border border-slate-200/60 dark:border-slate-700' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
            @click="activeTab = 'captcha'"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0" :style="activeTab === 'captcha' ? 'color: var(--primary)' : ''"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span class="flex-1">验证码过码模式</span>
            <Badge variant="outline" class="h-5 px-1.5 text-[10px]">{{ captchaMode === 'auto' ? '自动' : '手动' }}</Badge>
          </button>

          <button
            type="button"
            class="nav-tab-item w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all text-left"
            :class="activeTab === 'theme' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 shadow-2xs border border-slate-200/60 dark:border-slate-700' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
            @click="activeTab = 'theme'"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0" :style="activeTab === 'theme' ? 'color: var(--primary)' : ''"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.92 0 1.7-.75 1.7-1.67 0-.42-.16-.84-.45-1.16-.28-.31-.45-.73-.45-1.17 0-.92.75-1.67 1.67-1.67H16c3.31 0 6-2.69 6-6 0-4.96-4.49-9-10-9z"/></svg>
            <span class="flex-1">主题与视觉外观</span>
            <span class="w-3 h-3 rounded-full border border-slate-300 shadow-2xs shrink-0" :style="{ backgroundColor: customHex }"></span>
          </button>

          <button
            v-if="IS_TAURI"
            type="button"
            class="nav-tab-item w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all text-left"
            :class="activeTab === 'update' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 shadow-2xs border border-slate-200/60 dark:border-slate-700' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
            @click="activeTab = 'update'"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0" :style="activeTab === 'update' ? 'color: var(--primary)' : ''"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg>
            <span class="flex-1">软件版本更新</span>
            <Badge v-if="updateState === 'available'" variant="destructive" class="h-5 px-1.5 text-[10px] animate-pulse">新版本</Badge>
          </button>
        </div>

        <!-- 侧边栏底部说明卡片与保存按钮 -->
        <div class="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
          <div class="p-3 bg-slate-50 dark:bg-slate-950/60 rounded-xl border border-slate-200/60 dark:border-slate-800/80 text-[11px] text-slate-400 space-y-1">
            <div class="font-medium text-slate-600 dark:text-slate-300 flex items-center gap-1.5">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
              配置提示
            </div>
            <p class="leading-relaxed">所有设置修改后需点击底部或右顶部的「保存所有设置」生效。</p>
          </div>

          <Button variant="default" class="btn-theme-primary w-full h-9 text-xs font-semibold gap-1.5 shadow-2xs" :disabled="isSaving" @click.stop.prevent="saveAllSettings">
            <svg v-if="!isSaving" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
            <span>{{ isSaving ? '保存中…' : '保存系统设置' }}</span>
          </Button>
        </div>

      </div>

      <!-- 右侧核心工作区 Right Main Area (占满剩余宽度，带有自适应滚动) -->
      <div class="flex-1 min-w-0 h-full overflow-y-auto pr-1 space-y-5 custom-table-scrollbar">
        
        <!-- 1. 冰拓 (Bingtuo) 平台凭据卡片 -->
        <div v-show="activeTab === 'all' || activeTab === 'bingtuo'" class="setting-card bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-5 shadow-2xs space-y-5">
          <div class="card-header flex items-start justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
            <div>
              <h3 class="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="color: var(--primary)"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
                冰拓 (Bingtuo) 平台打码凭据
              </h3>
              <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">配置大麦网演出数据采集自动滑动验证码的解算账号与密钥</p>
            </div>
            <Button variant="outline" size="sm" class="h-7 text-xs gap-1.5" :disabled="balanceLoading" @click="checkBalance">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'icon-spin': balanceLoading }"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
              查询余额
            </Button>
          </div>

          <div class="space-y-4 w-full">
            <!-- 账号 (独占一行) -->
            <div class="space-y-1.5 w-full">
              <label class="text-xs font-semibold text-slate-700 dark:text-slate-300">冰拓账号</label>
              <Input
                type="text"
                v-model="bingtuoUser"
                placeholder="请输入冰拓平台账号"
                class="h-9 text-xs w-full"
              />
            </div>

            <!-- 密码 (独占一行) -->
            <div class="space-y-1.5 w-full">
              <label class="text-xs font-semibold text-slate-700 dark:text-slate-300">冰拓密码</label>
              <div class="relative flex items-center w-full">
                <Input
                  :type="showPassword ? 'text' : 'password'"
                  v-model="bingtuoPass"
                  placeholder="请输入冰拓平台密码"
                  class="h-9 text-xs pr-9 w-full"
                />
                <button
                  type="button"
                  class="absolute right-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1"
                  @click="showPassword = !showPassword"
                >
                  <svg v-if="showPassword" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                </button>
              </div>
            </div>

            <!-- 水果滑块类型 ID (独占一行) -->
            <div class="space-y-1.5 w-full">
              <div class="flex items-center justify-between">
                <label class="text-xs font-semibold text-slate-700 dark:text-slate-300">水果滑块类型 ID</label>
                <span class="text-[11px] text-slate-400">大麦网水果拼图滑动验证码平台类型码 (默认: 1358)</span>
              </div>
              <Input
                type="text"
                v-model="fruitCaptchaType"
                placeholder="1358"
                class="h-9 text-xs font-mono w-full"
              />
            </div>
          </div>

          <!-- 打码余额 Dashboard Widget -->
          <div class="p-3.5 bg-slate-50 dark:bg-slate-950 rounded-xl border border-slate-200/80 dark:border-slate-800 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-lg bg-emerald-100 dark:bg-emerald-950/60 flex items-center justify-center text-emerald-600 dark:text-emerald-400 shrink-0">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 6v2m0 8v2"/></svg>
              </div>
              <div>
                <div class="text-[11px] font-medium text-slate-400">冰拓打码平台剩余可用点数</div>
                <div class="flex items-baseline gap-1 mt-0.5">
                  <template v-if="balanceLoading">
                    <span class="text-xs text-slate-400">正在联网查询余额…</span>
                  </template>
                  <template v-else-if="balance !== null">
                    <span class="text-lg font-bold font-mono text-emerald-600 dark:text-emerald-400">{{ balance }}</span>
                    <span class="text-xs text-slate-500 font-medium">点数</span>
                  </template>
                  <template v-else>
                    <span class="text-xs text-amber-600 dark:text-amber-400 font-medium">{{ balanceError || '尚未查询' }}</span>
                  </template>
                </div>
              </div>
            </div>

            <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="balanceLoading" @click="checkBalance">
              刷新点数
            </Button>
          </div>
        </div>

        <!-- 2. 验证码过码模式 (自动 / 手动) 卡片 -->
        <div v-show="activeTab === 'all' || activeTab === 'captcha'" class="setting-card bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-5 shadow-2xs space-y-4">
          <div class="card-header pb-3 border-b border-slate-100 dark:border-slate-800">
            <h3 class="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="color: var(--primary)"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              验证码处理模式 (Captcha Mode)
            </h3>
            <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">选择在采集大麦演出遇到拼图滑块时的解算策略</p>
          </div>

          <!-- 每项独占一行全宽 -->
          <div class="space-y-3.5 w-full">
            <!-- 自动过码 -->
            <div
              class="captcha-option-box p-4 rounded-xl border-2 transition-all cursor-pointer flex items-start gap-3.5 relative overflow-hidden w-full"
              :class="captchaMode === 'auto' ? 'border-[var(--primary)] bg-pink-50/20 dark:bg-pink-950/10 shadow-xs' : 'border-slate-200/80 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-white dark:bg-slate-900'"
              @click="captchaMode = 'auto'"
            >
              <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" :class="captchaMode === 'auto' ? 'bg-[var(--primary)] text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
              </div>
              <div class="flex-1">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-slate-900 dark:text-slate-100">自动打码识别 (推荐)</span>
                  <Badge v-if="captchaMode === 'auto'" variant="default" class="btn-theme-primary h-4 px-1.5 text-[9px]">生效中</Badge>
                </div>
                <p class="text-[11px] text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">系统优先调用冰拓打码平台或本地算法解码，识别失败时自动弹窗人工兜底滑块</p>
              </div>
            </div>

            <!-- 手动过码 -->
            <div
              class="captcha-option-box p-4 rounded-xl border-2 transition-all cursor-pointer flex items-start gap-3.5 relative overflow-hidden w-full"
              :class="captchaMode === 'manual' ? 'border-[var(--primary)] bg-pink-50/20 dark:bg-pink-950/10 shadow-xs' : 'border-slate-200/80 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-white dark:bg-slate-900'"
              @click="captchaMode = 'manual'"
            >
              <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" :class="captchaMode === 'manual' ? 'bg-[var(--primary)] text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>
              </div>
              <div class="flex-1">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-slate-900 dark:text-slate-100">纯人工拖动过码</span>
                  <Badge v-if="captchaMode === 'manual'" variant="default" class="btn-theme-primary h-4 px-1.5 text-[9px]">生效中</Badge>
                </div>
                <p class="text-[11px] text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">不消耗打码平台点数，每次遇到拼图滑块直接弹出窗口，由人工手动滑动完成过码</p>
              </div>
            </div>
          </div>
        </div>

        <!-- 3. 主题与视觉外观 卡片 -->
        <div v-show="activeTab === 'all' || activeTab === 'theme'" class="setting-card bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-5 shadow-2xs space-y-4">
          <div class="card-header pb-3 border-b border-slate-100 dark:border-slate-800">
            <h3 class="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="color: var(--primary)"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.92 0 1.7-.75 1.7-1.67 0-.42-.16-.84-.45-1.16-.28-.31-.45-.73-.45-1.17 0-.92.75-1.67 1.67-1.67H16c3.31 0 6-2.69 6-6 0-4.96-4.49-9-10-9z"/></svg>
              全局系统主题外观 (Theme System)
            </h3>
            <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">选择预设配色调色盘，或自定义专属 Hex 色值</p>
          </div>

          <!-- 预设配色盘 Pills -->
          <div class="space-y-2">
            <div class="text-[11px] font-semibold text-slate-500">预设官方配色：</div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2.5">
              <button 
                v-for="t in themeOptions" 
                :key="t.hex"
                type="button"
                class="theme-swatch-btn flex items-center justify-center gap-2 px-3 py-2 rounded-xl border text-xs font-semibold transition-all relative overflow-hidden"
                :class="props.currentTheme.toLowerCase() === t.hex.toLowerCase() ? 'border-[var(--primary)] bg-slate-50 dark:bg-slate-800 shadow-2xs' : 'border-slate-200/80 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
                @click="selectTheme(t)"
              >
                <span class="w-3.5 h-3.5 rounded-full shrink-0 shadow-2xs" :style="{ backgroundColor: t.hex }"></span>
                <span class="text-slate-700 dark:text-slate-200 text-xs">{{ t.name }}</span>
                <svg v-if="props.currentTheme.toLowerCase() === t.hex.toLowerCase()" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" class="ml-auto" style="color: var(--primary)"><polyline points="20 6 9 17 4 12"/></svg>
              </button>
            </div>
          </div>

          <!-- 自定义颜色 Picker -->
          <div class="pt-2 flex items-center gap-3">
            <span class="text-xs font-semibold text-slate-700 dark:text-slate-300">自定义 Hex 色值：</span>
            <div class="flex items-center gap-2 bg-slate-50 dark:bg-slate-950 p-1.5 rounded-xl border border-slate-200/80 dark:border-slate-800">
              <label class="w-6 h-6 rounded-lg cursor-pointer shadow-2xs flex items-center justify-center relative overflow-hidden" :style="{ backgroundColor: customHex }">
                <input 
                  type="color" 
                  :value="customHex" 
                  @input="handleColorPickerInput"
                  class="opacity-0 absolute inset-0 cursor-pointer w-full h-full" 
                />
              </label>
              <span class="text-xs font-mono text-slate-400">#</span>
              <Input 
                type="text" 
                v-model="customHex" 
                class="h-7 w-24 text-xs font-mono border-none focus-visible:ring-0 px-1" 
                @change="handleHexInputChange"
              />
            </div>
          </div>
        </div>

        <!-- 4. 软件版本更新 (仅 Tauri 桌面环境) 卡片 -->
        <div v-if="IS_TAURI" v-show="activeTab === 'all' || activeTab === 'update'" class="setting-card bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-5 shadow-2xs space-y-4">
          <div class="card-header pb-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <div>
              <h3 class="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="color: var(--primary)"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg>
                桌面客户端版本更新
              </h3>
              <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">检测并在线升级客户端版本</p>
            </div>

            <Button
              v-if="updateState === 'available'"
              variant="default"
              size="sm"
              class="btn-theme-primary h-8 text-xs gap-1.5"
              @click="handleInstallUpdate"
            >
              立即升级版本
            </Button>
            <Button
              v-else
              variant="outline"
              size="sm"
              class="h-8 text-xs gap-1.5"
              :disabled="updateState === 'checking' || updateState === 'downloading'"
              @click="handleCheckUpdate"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'icon-spin': updateState === 'checking' }"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
              {{ updateState === 'checking' ? '正在联网检查…' : '检查软件更新' }}
            </Button>
          </div>

          <!-- 状态展示 -->
          <div class="p-3.5 bg-slate-50 dark:bg-slate-950 rounded-xl border border-slate-200/80 dark:border-slate-800 text-xs">
            <template v-if="updateState === 'available'">
              <div class="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-semibold">
                <span>发现可用的新版本：v{{ updateVersion }}</span>
              </div>
              <p v-if="updateNotes" class="text-[11px] text-slate-500 mt-1 font-mono whitespace-pre-wrap">{{ updateNotes }}</p>
            </template>
            <template v-else-if="updateState === 'downloading'">
              <div class="space-y-1.5">
                <div class="flex justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                  <span>正在下载升级包…</span>
                  <span>{{ updateProgress }}%</span>
                </div>
                <div class="w-full h-2 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div class="h-full bg-[var(--primary)] transition-all duration-200" :style="{ width: updateProgress + '%' }"></div>
                </div>
              </div>
            </template>
            <template v-else-if="updateState === 'uptodate'">
              <span class="text-slate-600 dark:text-slate-400">目前已是最新版本，无需升级。</span>
            </template>
            <template v-else-if="updateState === 'error'">
              <span class="text-red-500 font-medium">更新异常: {{ updateError }}</span>
            </template>
            <template v-else>
              <span class="text-slate-400">点击右上角「检查软件更新」按钮检测是否有新版本发布。</span>
            </template>
          </div>
        </div>

      </div>

    </div>

  </div>
</template>

<style scoped>
/* Toast 浮动提示 */
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

/* 结合主题色的通用按钮类 */
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

/* 自定义右侧面板滚动条 */
.custom-table-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-table-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-table-scrollbar::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}
.dark .custom-table-scrollbar::-webkit-scrollbar-thumb {
  background: #334155;
}
.custom-table-scrollbar::-webkit-scrollbar-thumb:hover {
  background: var(--primary, #eb4f9a);
}

/* Spinner 动画 */
.icon-spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
