<script setup>
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  detailRow: {
    type: Object,
    default: null
  },
  cleanPosterUrl: {
    type: Function,
    required: true
  },
  formatShowTime: {
    type: Function,
    required: true
  },
  parsePriceChips: {
    type: Function,
    required: true
  },
  statusBadgeClass: {
    type: Function,
    required: true
  }
})

const emit = defineEmits(['update:open', 'openPreview', 'openExternalUrl'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})

function handlePreview(url, title) {
  emit('openPreview', url, title)
}

function handleExternal(url) {
  emit('openExternalUrl', url)
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="max-w-4xl p-6 md:p-8 max-h-[92vh] overflow-y-auto bg-white dark:bg-slate-950">
      <DialogHeader class="sr-only">
        <DialogTitle>演出详情页</DialogTitle>
      </DialogHeader>

      <div v-if="detailRow" class="space-y-6">
        <!-- 上半部分：大麦官方两列布局 (左海报 + 右售票面板) -->
        <div class="flex flex-col md:flex-row gap-6 items-start">
          <!-- 左侧：立式高清海报 (固定 260px) -->
          <div class="w-full md:w-[260px] shrink-0 flex flex-col items-center">
            <div class="rounded-lg overflow-hidden border shadow-sm w-full bg-slate-100 dark:bg-slate-800 relative group">
              <img
                v-if="cleanPosterUrl(detailRow.poster_url)"
                :src="cleanPosterUrl(detailRow.poster_url)"
                :alt="detailRow.title"
                class="w-full h-[360px] object-cover hover:scale-105 transition-transform duration-300 cursor-pointer"
                @click="handlePreview(detailRow.poster_url, detailRow.title)"
              />
              <div v-else class="h-[360px] flex flex-col items-center justify-center text-slate-400 gap-2">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
                <span>暂无海报</span>
              </div>
            </div>
            <a
              v-if="detailRow.url"
              :href="detailRow.url"
              target="_blank"
              class="mt-3 text-xs text-blue-600 hover:text-blue-700 hover:underline flex items-center gap-1 font-medium"
              @click.prevent="handleExternal(detailRow.url)"
            >
              <span>前往原始售票页面</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          </div>

          <!-- 右侧：大麦网标准排版 -->
          <div class="flex-1 space-y-4 text-slate-800 dark:text-slate-200">
            <!-- 1. 标题与总票代 Badge -->
            <div class="space-y-1.5">
              <div class="flex items-start gap-2">
                <span
                  v-if="detailRow.perf_state"
                  class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold border shrink-0 mt-1 shadow-2xs"
                  :class="statusBadgeClass(detailRow.perf_state)"
                >
                  <span
                    class="w-1.5 h-1.5 rounded-full shrink-0"
                    :class="{
                      'bg-blue-600': detailRow.perf_state === '未演出' || detailRow.perf_state === 'upcoming',
                      'bg-emerald-600 animate-pulse': detailRow.perf_state === '演出中' || detailRow.perf_state === 'ongoing',
                      'bg-slate-500': detailRow.perf_state === '已演出' || detailRow.perf_state === 'done',
                      'bg-red-600': detailRow.perf_state === '取消' || detailRow.perf_state === 'cancelled'
                    }"
                  ></span>
                  <span>{{ detailRow.perf_state }}</span>
                </span>
                <h2 class="text-xl md:text-2xl font-bold leading-snug text-slate-900 dark:text-white">
                  【{{ detailRow.city }}】{{ detailRow.norm_title || detailRow.title }}
                </h2>
              </div>
              <div v-if="detailRow.title && detailRow.title !== detailRow.norm_title" class="text-xs text-slate-400 pl-1">
                原名称：{{ detailRow.title }}
              </div>
            </div>

            <!-- 2. 时间与场馆 -->
            <div class="space-y-2 pt-2 text-sm">
              <div class="flex items-center gap-2">
                <span class="text-slate-500 w-12 shrink-0">时间：</span>
                <span class="font-semibold text-slate-900 dark:text-slate-100">
                  {{ formatShowTime(detailRow.start_time) }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-slate-500 w-12 shrink-0">场馆：</span>
                <span class="font-medium text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                  {{ detailRow.city }} | {{ detailRow.norm_venue || detailRow.venue_name || '剧场' }}
                  <span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 text-xs">📍</span>
                </span>
              </div>
              <div class="text-[11px] text-slate-400 flex items-center gap-1 pt-0.5">
                <span class="inline-block w-3.5 h-3.5 rounded-full bg-slate-300 text-white text-[10px] text-center leading-3">i</span>
                <span>场次时间均为演出当地时间</span>
              </div>
            </div>

            <!-- 3. 场次 -->
            <div class="space-y-2 pt-2">
              <div class="flex items-center gap-2">
                <span class="text-sm text-slate-500 w-12 shrink-0">场次</span>
                <div class="flex flex-wrap gap-2">
                  <div class="inline-flex items-center px-3 py-1.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 text-xs font-medium border border-slate-200 dark:border-slate-700">
                    <span>{{ formatShowTime(detailRow.start_time) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 4. 票档 -->
            <div class="space-y-2 pt-2">
              <div class="flex items-start gap-2">
                <span class="text-sm text-slate-500 w-12 shrink-0 pt-1.5">票档</span>
                <div class="flex flex-wrap gap-2.5 flex-1">
                  <template v-for="(chip, index) in parsePriceChips(detailRow.price)" :key="index">
                    <div
                      v-if="chip.raw"
                      class="px-4 py-2 rounded-lg bg-slate-100/90 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200/80 font-mono text-xs shadow-2xs"
                    >
                      {{ chip.text }}
                    </div>
                    <div
                      v-else
                      class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium bg-slate-50 dark:bg-slate-800/80 text-slate-800 dark:text-slate-200 border transition-all shadow-2xs"
                      :class="chip.isPrimary
                        ? 'border-pink-500 text-pink-600 bg-white dark:bg-slate-900 font-semibold ring-1 ring-pink-500/20'
                        : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'"
                    >
                      <span>{{ chip.text }}</span>
                      <span
                        v-if="chip.tag && chip.tagType === 'soldout'"
                        class="text-[10px] text-slate-500 bg-slate-100 border border-slate-300 dark:bg-slate-800 dark:border-slate-600 px-1.5 py-0.2 rounded-full font-normal"
                      >
                        {{ chip.tag }}
                      </span>
                      <span
                        v-if="chip.tag && chip.tagType === 'hui'"
                        class="w-4 h-4 rounded-full bg-pink-50 text-pink-600 border border-pink-300 text-[10px] inline-flex items-center justify-center font-bold"
                      >
                        {{ chip.tag }}
                      </span>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 下半部分：项目全量属性卡片档案 -->
        <div class="mt-6 border-t pt-4 space-y-3">
          <div class="text-xs font-bold text-slate-500 flex items-center justify-between">
            <span>演出项目详细档案参数 (Full Meta Details)</span>
            <span class="font-mono text-slate-400">ID: {{ detailRow.id }}</span>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-4 gap-3 bg-slate-50 dark:bg-slate-900/60 p-4 rounded-xl text-xs border border-slate-100 dark:border-slate-800">
            <div><span class="text-slate-400">演出大类：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.category || '未分类' }}</span></div>
            <div><span class="text-slate-400">二级分类：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.subcategory || '-' }}</span></div>
            <div><span class="text-slate-400">演出团体：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.troupe || '-' }}</span></div>
            <div><span class="text-slate-400">团体城市：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.group_city || '-' }}</span></div>
            <div><span class="text-slate-400">主办单位：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.organizer || '-' }}</span></div>
            <div><span class="text-slate-400">主办城市：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.organizer_city || '-' }}</span></div>
            <div><span class="text-slate-400">主要演员：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.performers || '-' }}</span></div>
            <div><span class="text-slate-400">院团属性：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.troupe_attr || '-' }}</span></div>
            <div><span class="text-slate-400">港澳台属性：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.hk_mo_tw || '-' }}</span></div>
            <div><span class="text-slate-400">总场次数：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.session_count || 1 }} 场</span></div>
            <div><span class="text-slate-400">节假日：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.holiday || '无' }}</span></div>
            <div><span class="text-slate-400">数据序号：</span><span class="font-medium text-slate-800 dark:text-slate-200">{{ detailRow.seq }}</span></div>
          </div>
        </div>
      </div>

      <DialogFooter class="mt-4 pt-3 border-t flex items-center justify-between">
        <span class="text-xs text-slate-400">数据源：大麦网 / 猫眼演出数据库</span>
        <DialogClose as-child>
          <Button variant="outline" class="px-6">关闭窗口</Button>
        </DialogClose>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
