<script setup>
import { ref, onMounted } from 'vue'
import { api, IN_TAURI } from '../api.js'
import { checkForUpdate, downloadAndInstall } from '../updater.js'

const props = defineProps({
  currentTheme: {
    type: String,
    default: '#eb4f9a'
  }
})

const emit = defineEmits(['update-theme'])

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
    } else if (data.error) {
      balance.value = null
      balanceError.value = data.error
    } else {
      balance.value = data.points
    }
  } catch (e) {
    balance.value = null
    balanceError.value = e.message || '查询失败'
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

// Toast 提示状态
const showToast = ref(false)
const toastMessage = ref('')
const isSaving = ref(false)

function triggerToast(msg = '系统设置已保存成功！') {
  toastMessage.value = msg
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 2600)
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
    triggerToast('系统设置配置成功')
  } catch (e) {
    triggerToast('保存失败: ' + e.message)
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
    // 完成后 relaunch()，此后代码不再执行
    await downloadAndInstall(pendingUpdate, (p) => { updateProgress.value = p })
  } catch (e) {
    updateState.value = 'error'
    updateError.value = e.message || '下载安装失败'
  }
}

onMounted(async () => {
  await loadSettings()
  // 已配置账号才查余额，避免每次进设置页都弹「请先填账号」
  if (bingtuoUser.value && bingtuoPass.value) {
    checkBalance()
  }
})
</script>

<template>
  <div class="settings-page">
    <div class="settings-container">

      <!-- Toast 浮动提示通知栏 -->
      <transition name="toast-fade">
        <div v-if="showToast" class="toast-notification">
          <div class="toast-icon">✓</div>
          <span class="toast-text">{{ toastMessage }}</span>
        </div>
      </transition>

      <!-- 1. 冰拓 (Bingtuo) 平台凭据 -->
      <div class="setting-block">
        <div class="block-header">
          <h3 class="block-title">冰拓 (Bingtuo) 平台账号与密码</h3>
          <p class="block-desc">配置演出数据采集源的验证账号及访问密码。</p>
        </div>

        <div class="single-column-inputs">
          <div class="field-item">
            <label class="field-lbl">冰拓账号</label>
            <input
              type="text"
              v-model="bingtuoUser"
              placeholder="请输入冰拓账号"
              class="setting-input-full"
            />
          </div>

          <div class="field-item">
            <label class="field-lbl">冰拓密码</label>
            <div class="password-input-wrapper">
              <input
                :type="showPassword ? 'text' : 'password'"
                v-model="bingtuoPass"
                placeholder="请输入冰拓密码"
                class="setting-input-full password-input"
              />
              <button
                type="button"
                class="eye-toggle-btn"
                @click="showPassword = !showPassword"
                :title="showPassword ? '隐藏密码' : '显示密码'"
              >
                <!-- 睁眼 Eye Icon -->
                <svg v-if="showPassword" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
                <!-- 闭眼 EyeOff Icon -->
                <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
              </button>
            </div>
          </div>

          <div class="field-item">
            <label class="field-lbl">水果滑块类型 ID</label>
            <input
              type="text"
              v-model="fruitCaptchaType"
              placeholder="冰拓验证码类型 ID (默认: 1358)"
              class="setting-input-full"
            />
            <p class="field-hint">冰拓平台水果滑块验证码的类型标识,默认为 1358</p>
          </div>

          <!-- 冰拓剩余打码点数 -->
          <div class="field-item">
            <label class="field-lbl">冰拓剩余点数</label>
            <div class="balance-card">
              <div class="balance-left">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="2" y="5" width="20" height="14" rx="2"/>
                  <line x1="2" y1="10" x2="22" y2="10"/>
                </svg>
                <template v-if="balanceLoading">
                  <span class="balance-loading">查询中…</span>
                </template>
                <template v-else-if="balance !== null">
                  <span class="balance-num">{{ balance }}</span>
                  <span class="balance-unit">点</span>
                </template>
                <template v-else>
                  <span class="balance-err">{{ balanceError || '尚未查询' }}</span>
                </template>
              </div>
              <button type="button" class="balance-refresh-btn" :disabled="balanceLoading" @click="checkBalance">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" :class="{ 'icon-spin': balanceLoading }">
                  <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
                查询余额
              </button>
            </div>
            <p class="field-hint">实时查询冰拓平台账号的剩余打码点数（需先保存账号密码）</p>
          </div>
        </div>
      </div>

      <!-- 2. 过码模式选择 (自动 / 手动) -->
      <div class="setting-block">
        <div class="block-header">
          <h3 class="block-title">验证码过码模式</h3>
          <p class="block-desc">选择大麦滑块验证码的处理方式。自动过码优先走打码平台/本地识别，失败时人工兜底；手动过码则每次都弹窗由人工拖动滑块。</p>
        </div>

        <div class="captcha-mode-tabs">
          <button
            type="button"
            class="mode-tab"
            :class="{ active: captchaMode === 'auto' }"
            @click="captchaMode = 'auto'"
          >
            <div class="mode-head">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
              </svg>
              <span class="mode-title">自动过码</span>
            </div>
            <span class="mode-sub">打码平台 / 本地识别，失败人工兜底</span>
          </button>
          <button
            type="button"
            class="mode-tab"
            :class="{ active: captchaMode === 'manual' }"
            @click="captchaMode = 'manual'"
          >
            <div class="mode-head">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8"/>
                <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>
              </svg>
              <span class="mode-title">手动过码</span>
            </div>
            <span class="mode-sub">每次弹窗由人工拖动滑块</span>
          </button>
        </div>
      </div>

      <!-- 3. 系统全局主题色配置 (放在最后面) -->
      <div class="setting-block">
        <div class="block-header">
          <h3 class="block-title">系统全局主题色配置 (Theme Color)</h3>
          <p class="block-desc">选择经典预设配色，或通过颜色选择器自定义系统 Hex 色彩。</p>
        </div>

        <!-- 预设配色 Pills -->
        <div class="color-options-flex">
          <button 
            v-for="t in themeOptions" 
            :key="t.hex"
            class="color-pill-btn"
            :class="{ active: props.currentTheme.toLowerCase() === t.hex.toLowerCase() }"
            @click="selectTheme(t)"
          >
            <span class="color-dot" :style="{ backgroundColor: t.hex }"></span>
            <span class="color-name">{{ t.name }}</span>
          </button>
        </div>

        <!-- 自定义颜色选择器 (原生 Color Picker + HEX 输入框) -->
        <div class="custom-color-picker-row">
          <span class="picker-label">自定义颜色选择器:</span>
          
          <div class="color-picker-box">
            <!-- 原生 Color Picker 触发选择器 -->
            <label class="native-color-trigger" :style="{ backgroundColor: customHex }" title="点击选择颜色">
              <input 
                type="color" 
                :value="customHex" 
                @input="handleColorPickerInput"
                class="native-color-input" 
              />
            </label>
            
            <span class="hex-prefix">#</span>
            <input 
              type="text" 
              v-model="customHex" 
              class="hex-text-input" 
              @change="handleHexInputChange"
            />
          </div>
        </div>
      </div>

      <!-- 4. 软件更新 (仅桌面客户端) -->
      <div class="setting-block" v-if="IS_TAURI">
        <div class="block-header">
          <h3 class="block-title">软件更新</h3>
          <p class="block-desc">检查并安装最新版本。发现新版本后可一键下载，安装完成会自动重启应用。</p>
        </div>

        <div class="update-card">
          <div class="update-left">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
              <polyline points="21 3 21 9 15 9"/>
            </svg>

            <template v-if="updateState === 'checking'">
              <span class="update-txt">正在检查更新…</span>
            </template>
            <template v-else-if="updateState === 'available'">
              <span class="update-txt update-hl">发现新版本 v{{ updateVersion }}</span>
            </template>
            <template v-else-if="updateState === 'downloading'">
              <span class="update-txt">下载中 {{ updateProgress }}%</span>
            </template>
            <template v-else-if="updateState === 'uptodate'">
              <span class="update-txt">已是最新版本</span>
            </template>
            <template v-else-if="updateState === 'error'">
              <span class="update-txt update-err">{{ updateError }}</span>
            </template>
            <template v-else>
              <span class="update-txt">点击右侧按钮检查是否有新版本</span>
            </template>
          </div>

          <button
            v-if="updateState === 'available'"
            type="button"
            class="update-btn update-btn-primary"
            @click="handleInstallUpdate"
          >
            立即更新并重启
          </button>
          <button
            v-else
            type="button"
            class="update-btn"
            :disabled="updateState === 'checking' || updateState === 'downloading'"
            @click="handleCheckUpdate"
          >
            {{ updateState === 'checking' ? '检查中…' : '检查更新' }}
          </button>
        </div>

        <div v-if="updateState === 'downloading'" class="update-progress-track">
          <div class="update-progress-bar" :style="{ width: updateProgress + '%' }"></div>
        </div>
      </div>

      <!-- 底部 保存按钮 -->
      <div class="settings-footer">
        <button class="btn-save-all" @click="saveAllSettings" :disabled="isSaving">
          {{ isSaving ? '保存中...' : '保存所有系统设置' }}
        </button>
      </div>

    </div>
  </div>
</template>

<style scoped>
.settings-page {
  height: 100%;
  width: 100%;
  overflow-y: auto;
  background-color: #ffffff;
  padding: 36px 48px;
  display: flex;
  justify-content: center;
  position: relative;
}

.settings-container {
  width: 100%;
  max-width: 820px;
  display: flex;
  flex-direction: column;
  gap: 40px;
  padding-bottom: 60px;
  position: relative;
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

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -20px);
}

.setting-block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.block-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.block-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.block-desc {
  font-size: 12.5px;
  color: #64748b;
  margin: 0;
}

/* 独占一行全宽输入框 */
.single-column-inputs {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

.field-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.field-lbl {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.field-hint {
  font-size: 11px;
  color: #94a3b8;
  margin: 0;
  margin-top: 4px;
}

/* 冰拓余额卡片 */
.balance-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 46px;
  padding: 0 8px 0 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--primary-light) 0%, #ffffff 90%);
}

.balance-left {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--primary);
}

.balance-left svg {
  align-self: center;
}

.balance-num {
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.balance-unit {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.balance-loading,
.balance-err {
  font-size: 13px;
  color: #94a3b8;
  font-weight: 500;
  align-self: center;
}

.balance-err {
  color: #ef4444;
}

.balance-refresh-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--primary-border, #f0abca);
  background: #ffffff;
  color: var(--primary);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.balance-refresh-btn:hover:not(:disabled) {
  background: var(--primary);
  color: #ffffff;
}

.balance-refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.icon-spin {
  animation: settings-spin 0.8s linear infinite;
}

/* 软件更新卡片 */
.update-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  padding: 8px 8px 8px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

.update-left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  min-width: 0;
}

.update-txt {
  font-size: 13px;
  color: #475569;
  font-weight: 500;
}

.update-hl {
  color: var(--primary);
  font-weight: 700;
}

.update-err {
  color: #ef4444;
}

.update-btn {
  height: 32px;
  padding: 0 16px;
  border: 1px solid var(--primary-border, #f0abca);
  background: #ffffff;
  color: var(--primary);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.update-btn:hover:not(:disabled) {
  background: var(--primary);
  color: #ffffff;
}

.update-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.update-btn-primary {
  background: var(--primary);
  color: #ffffff;
  border-color: var(--primary);
}

.update-btn-primary:hover {
  background: var(--primary-hover);
}

.update-progress-track {
  margin-top: 10px;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  overflow: hidden;
}

.update-progress-bar {
  height: 100%;
  background: var(--primary);
  border-radius: 3px;
  transition: width 0.2s ease;
}

@keyframes settings-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 过码模式 Tab 选择 */
.captcha-mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.mode-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px 14px;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.18s;
  text-align: left;
  color: #94a3b8;
}

.mode-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mode-head svg {
  flex-shrink: 0;
}

.mode-tab:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.mode-tab.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  box-shadow: 0 2px 8px var(--primary-shadow);
}

.mode-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.mode-tab.active .mode-title {
  color: var(--primary);
}

.mode-sub {
  font-size: 11.5px;
  color: #64748b;
  font-weight: 500;
}

.setting-input-full {
  width: 100%;
  height: 38px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0 14px;
  font-size: 13px;
  color: #0f172a;
  background: #ffffff;
  outline: none;
  transition: all 0.15s;
}

.setting-input-full:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}

/* 密码 Eye 图标 Wrapper */
.password-input-wrapper {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
}

.password-input {
  padding-right: 40px !important;
}

.eye-toggle-btn {
  position: absolute;
  right: 8px;
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: color 0.15s;
}

.eye-toggle-btn:hover {
  color: var(--primary);
}

/* 预设配色 Pills */
.color-options-flex {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.color-pill-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  border-radius: 20px;
  font-size: 12.5px;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s;
}

.color-pill-btn:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.color-pill-btn.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 700;
}

.color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

/* 自定义颜色选择器 (原生 Color Picker) */
.custom-color-picker-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 6px;
}

.picker-label {
  font-size: 12.5px;
  color: #475569;
  font-weight: 600;
}

.color-picker-box {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 4px 10px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.native-color-trigger {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(0,0,0,0.15);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.3);
}

.native-color-input {
  position: absolute;
  top: -10px;
  left: -10px;
  width: 50px;
  height: 50px;
  opacity: 0;
  cursor: pointer;
}

.hex-prefix {
  font-family: monospace;
  font-size: 13px;
  color: #64748b;
  font-weight: 700;
}

.hex-text-input {
  border: none;
  font-family: monospace;
  font-size: 13px;
  width: 80px;
  outline: none;
  text-transform: uppercase;
  color: #0f172a;
  font-weight: 600;
}

/* 底部保存按钮 */
.settings-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

.btn-save-all {
  background: var(--primary);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  height: 40px;
  padding: 0 32px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 12px var(--primary-shadow);
  transition: all 0.15s;
}

.btn-save-all:hover {
  background: var(--primary-hover);
  transform: translateY(-1px);
}
</style>
