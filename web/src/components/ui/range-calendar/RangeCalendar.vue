<script setup>
import {
  RangeCalendarCell,
  RangeCalendarCellTrigger,
  RangeCalendarGrid,
  RangeCalendarGridBody,
  RangeCalendarGridHead,
  RangeCalendarGridRow,
  RangeCalendarHeadCell,
  RangeCalendarNext,
  RangeCalendarPrev,
  RangeCalendarRoot,
} from 'radix-vue'
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-vue-next'
import { cn } from '@/lib/utils'

defineOptions({ inheritAttrs: false })

// 区间日历：双月并排，每个月自成一块（独立月份标题 + 独立星期表头 + 竖线分隔），
// 翻页按钮按参考稿分置两端——首月管「上一年 / 上一月」，末月管「下一月 / 下一年」。
//
// weekStartsOn 必须是 0：radix 在 zh-CN locale（基准周一）上再叠加该偏移，
// 传 1 会让一周从星期二开始。
const props = defineProps({
  modelValue: { type: Object, required: false },
  defaultValue: { type: Object, required: false },
  placeholder: { type: Object, required: false },
  locale: { type: String, default: 'zh-CN' },
  weekStartsOn: { type: Number, default: 0 },
  fixedWeeks: { type: Boolean, default: true },
  initialFocus: { type: Boolean, default: true },
  numberOfMonths: { type: Number, default: 2 },
  // 逐月翻页：点一次左右两块各前进一个月，与参考稿的双面板行为一致
  pagedNavigation: { type: Boolean, default: false },
  maxValue: { type: Object, required: false },
  minValue: { type: Object, required: false },
  class: { type: [String, Object, Array], default: '' },
})

const emit = defineEmits(['update:modelValue', 'update:placeholder'])

function monthLabel(value) {
  return `${value.year}年${value.month}月`
}

const NAV_BUTTON_CLASS =
  'inline-flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:pointer-events-none disabled:opacity-30'
</script>

<template>
  <RangeCalendarRoot
    v-bind="$attrs"
    :model-value="modelValue"
    :default-value="defaultValue"
    :placeholder="placeholder"
    :locale="locale"
    :week-starts-on="weekStartsOn"
    :fixed-weeks="fixedWeeks"
    :initial-focus="initialFocus"
    :number-of-months="numberOfMonths"
    :paged-navigation="pagedNavigation"
    :max-value="maxValue"
    :min-value="minValue"
    :class="cn('flex divide-x divide-slate-100', props.class)"
    @update:model-value="emit('update:modelValue', $event)"
    @update:placeholder="emit('update:placeholder', $event)"
  >
    <template #default="{ grid, weekDays }">
      <div
        v-for="(month, monthIndex) in grid"
        :key="month.value.toString()"
        class="px-3 py-2.5"
      >
        <!-- 月份标题行：两端留等宽占位，标题才能真正居中 -->
        <div class="flex h-7 items-center justify-between">
          <div class="flex w-14 shrink-0 items-center gap-0.5">
            <template v-if="monthIndex === 0">
              <RangeCalendarPrev
                :prev-page="(date) => date.subtract({ years: 1 })"
                :class="NAV_BUTTON_CLASS"
                aria-label="上一年"
              >
                <ChevronsLeft class="h-3.5 w-3.5" />
              </RangeCalendarPrev>
              <RangeCalendarPrev :class="NAV_BUTTON_CLASS" aria-label="上一月">
                <ChevronLeft class="h-3.5 w-3.5" />
              </RangeCalendarPrev>
            </template>
          </div>

          <span class="text-sm font-semibold text-slate-800">
            {{ monthLabel(month.value) }}
          </span>

          <div class="flex w-14 shrink-0 items-center justify-end gap-0.5">
            <template v-if="monthIndex === grid.length - 1">
              <RangeCalendarNext :class="NAV_BUTTON_CLASS" aria-label="下一月">
                <ChevronRight class="h-3.5 w-3.5" />
              </RangeCalendarNext>
              <RangeCalendarNext
                :next-page="(date) => date.add({ years: 1 })"
                :class="NAV_BUTTON_CLASS"
                aria-label="下一年"
              >
                <ChevronsRight class="h-3.5 w-3.5" />
              </RangeCalendarNext>
            </template>
          </div>
        </div>

        <RangeCalendarGrid class="mt-1.5 border-collapse">
          <RangeCalendarGridHead>
            <RangeCalendarGridRow class="flex border-b border-slate-100 pb-1.5">
              <RangeCalendarHeadCell
                v-for="day in weekDays"
                :key="day"
                class="w-9 rounded-md text-center text-[11px] font-normal text-slate-400"
              >
                {{ day }}
              </RangeCalendarHeadCell>
            </RangeCalendarGridRow>
          </RangeCalendarGridHead>
          <RangeCalendarGridBody>
            <RangeCalendarGridRow
              v-for="(week, weekIndex) in month.rows"
              :key="weekIndex"
              class="mt-1 flex w-full"
            >
              <RangeCalendarCell
                v-for="day in week"
                :key="day.toString()"
                :date="day"
                class="relative h-9 w-9 p-0 text-center text-sm"
              >
                <!-- 端点用 ! 强制覆盖区间内的浅色底，避免 Tailwind 同级 variant 生成顺序不确定。
                     浅底走 --primary-light 而非 primary/10：Tailwind 3 无法给任意 CSS 变量加透明度。 -->
                <RangeCalendarCellTrigger
                  :day="day"
                  :month="month.value"
                  class="inline-flex h-9 w-9 items-center justify-center rounded-md text-xs font-medium text-slate-700 outline-none transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-[var(--primary-border)] data-[highlighted]:bg-[var(--primary-light)] data-[highlighted]:text-[var(--primary)] data-[selected]:bg-[var(--primary-light)] data-[selected]:text-[var(--primary)] data-[selection-end]:!bg-[var(--primary)] data-[selection-end]:!text-white data-[selection-start]:!bg-[var(--primary)] data-[selection-start]:!text-white data-[today]:border data-[today]:border-[var(--primary)] data-[outside-view]:text-slate-300 data-[outside-view]:opacity-60 data-[disabled]:pointer-events-none data-[disabled]:opacity-40"
                />
              </RangeCalendarCell>
            </RangeCalendarGridRow>
          </RangeCalendarGridBody>
        </RangeCalendarGrid>
      </div>
    </template>
  </RangeCalendarRoot>
</template>
