<script setup>
import {
  CalendarCell,
  CalendarCellTrigger,
  CalendarGrid,
  CalendarGridBody,
  CalendarGridHead,
  CalendarGridRow,
  CalendarHeadCell,
  CalendarHeader,
  CalendarHeading,
  CalendarNext,
  CalendarPrev,
  CalendarRoot,
} from 'radix-vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: Object, required: false },
  defaultValue: { type: Object, required: false },
  placeholder: { type: Object, required: false },
  locale: { type: String, default: 'zh-CN' },
  // 必须是 0：radix 在 zh-CN locale（基准周一）上再叠加该偏移，传 1 会从星期二开始
  weekStartsOn: { type: Number, default: 0 },
  fixedWeeks: { type: Boolean, default: true },
  initialFocus: { type: Boolean, default: true },
  preventDeselect: { type: Boolean, default: false },
  class: { type: [String, Object, Array], default: '' },
})

const emit = defineEmits(['update:modelValue', 'update:placeholder'])
</script>

<template>
  <CalendarRoot
    v-bind="$attrs"
    :model-value="modelValue"
    :default-value="defaultValue"
    :placeholder="placeholder"
    :locale="locale"
    :week-starts-on="weekStartsOn"
    :fixed-weeks="fixedWeeks"
    :initial-focus="initialFocus"
    :prevent-deselect="preventDeselect"
    :class="cn('p-3', props.class)"
    @update:model-value="emit('update:modelValue', $event)"
    @update:placeholder="emit('update:placeholder', $event)"
  >
    <template #default="{ grid, weekDays }">
      <CalendarHeader class="relative flex w-full items-center justify-between pb-3">
        <CalendarPrev class="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 transition-colors hover:bg-slate-100 disabled:opacity-40">
          <ChevronLeft class="h-4 w-4" />
        </CalendarPrev>
        <CalendarHeading class="text-sm font-semibold text-slate-800" />
        <CalendarNext class="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 transition-colors hover:bg-slate-100 disabled:opacity-40">
          <ChevronRight class="h-4 w-4" />
        </CalendarNext>
      </CalendarHeader>

      <CalendarGrid v-for="month in grid" :key="month.value.toString()" class="w-full border-collapse">
        <CalendarGridHead>
          <CalendarGridRow class="flex">
            <CalendarHeadCell
              v-for="day in weekDays"
              :key="day"
              class="w-9 rounded-md text-center text-[11px] font-normal text-slate-400"
            >
              {{ day }}
            </CalendarHeadCell>
          </CalendarGridRow>
        </CalendarGridHead>
        <CalendarGridBody>
          <CalendarGridRow v-for="(week, weekIndex) in month.rows" :key="weekIndex" class="mt-1 flex w-full">
            <CalendarCell v-for="day in week" :key="day.toString()" :date="day" class="relative h-9 w-9 p-0 text-center text-sm">
              <CalendarCellTrigger
                :day="day"
                :month="month.value"
                class="inline-flex h-9 w-9 items-center justify-center rounded-md text-xs font-medium text-slate-700 outline-none transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-[var(--primary)]/30 data-[selected]:bg-[var(--primary)] data-[selected]:text-white data-[today]:border data-[today]:border-[var(--primary)] data-[outside-view]:text-slate-300 data-[outside-view]:opacity-60 data-[disabled]:pointer-events-none data-[disabled]:opacity-40"
              />
            </CalendarCell>
          </CalendarGridRow>
        </CalendarGridBody>
      </CalendarGrid>
    </template>
  </CalendarRoot>
</template>
