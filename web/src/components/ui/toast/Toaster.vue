<script setup>
import { useToastStore } from './index'

const { toasts, removeToast } = useToastStore()

function cleanMessage(text) {
  if (!text) return ''
  // 擦除开头的冗余符号（如 ✓ ✕ ⚠️ 🚀 等）
  return String(text).replace(/^[✓✕⚠️🚀\s]+/, '').trim()
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed top-5 right-5 z-[999999] flex flex-col items-end gap-2.5 pointer-events-none max-w-sm w-auto">
      <transition-group name="shadcn-toast-right">
        <div
          v-for="t in toasts"
          :key="t.id"
          class="pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border bg-white/95 dark:bg-slate-900/95 backdrop-blur-md shadow-[0_10px_30px_rgba(0,0,0,0.1)] text-slate-800 dark:text-slate-100 text-xs sm:text-sm font-medium transition-all duration-300 w-fit max-w-full"
          :class="{
            'border-red-200 dark:border-red-900/60 bg-red-50/90 dark:bg-red-950/90 text-red-900 dark:text-red-200': t.variant === 'destructive' || t.variant === 'error',
            'border-emerald-200/80 dark:border-emerald-900/60 bg-emerald-50/90 dark:bg-emerald-950/90 text-emerald-900 dark:text-emerald-200': t.variant === 'success',
            'border-amber-200 dark:border-amber-900/60 bg-amber-50/90 dark:bg-amber-950/90 text-amber-900 dark:text-amber-200': t.variant === 'warning',
            'border-slate-200/90 dark:border-slate-800 text-slate-700 dark:text-slate-200': t.variant === 'default'
          }"
        >
          <!-- 左侧精致图标 -->
          <div class="shrink-0 flex items-center justify-center">
            <svg v-if="t.variant === 'success'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-emerald-600 dark:text-emerald-400">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <svg v-else-if="t.variant === 'destructive' || t.variant === 'error'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-red-600 dark:text-red-400">
              <circle cx="12" cy="12" r="10"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <svg v-else-if="t.variant === 'warning'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-amber-600 dark:text-amber-400">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-slate-600 dark:text-slate-400">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="16" x2="12" y2="12"/>
              <line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
          </div>

          <!-- 消息文本 -->
          <div class="flex-1 flex flex-col justify-center">
            <span v-if="t.title" class="font-bold text-xs leading-snug mb-0.5">{{ cleanMessage(t.title) }}</span>
            <span class="leading-relaxed text-xs">{{ cleanMessage(t.description) }}</span>
          </div>

          <!-- 右侧关闭 ✕ -->
          <button
            type="button"
            class="shrink-0 p-1 ml-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors rounded-full leading-none flex items-center justify-center"
            @click="removeToast(t.id)"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </transition-group>
    </div>
  </Teleport>
</template>

<style scoped>
.shadcn-toast-right-enter-active,
.shadcn-toast-right-leave-active {
  transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}
.shadcn-toast-right-enter-from {
  opacity: 0;
  transform: translateX(30px) scale(0.95);
}
.shadcn-toast-right-leave-to {
  opacity: 0;
  transform: translateX(20px) scale(0.95);
}
</style>
