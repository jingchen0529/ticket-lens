<script setup>
import { computed, watch, reactive } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Field, FieldLabel } from '@/components/ui/field'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  editRowData: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['update:open', 'save'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})

// 安全值处理：防止对象/数组转化为 [object Object]
function safeStringify(val) {
  if (val === null || val === undefined) return ''
  if (typeof val === 'object') {
    try {
      return JSON.stringify(val)
    } catch {
      return String(val)
    }
  }
  return String(val)
}

function handleSave() {
  emit('save')
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <!-- 拓宽 Dialog 宽度为 max-w-4xl，充满开阔空间 -->
    <DialogContent class="max-w-4xl w-full max-h-[88vh] flex flex-col p-0 overflow-hidden rounded-2xl border shadow-2xl bg-white dark:bg-slate-950">
      
      <!-- 固定置顶 Header (不随内容滚动) -->
      <DialogHeader class="p-6 pb-4 border-b border-slate-100 dark:border-slate-800 shrink-0 bg-white dark:bg-slate-950">
        <DialogTitle class="text-lg font-bold flex items-center justify-between text-slate-900 dark:text-slate-100">
          <span class="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="color: var(--primary)">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
            全量演出数据编辑
          </span>
          <Badge variant="outline" class="font-mono text-xs">ID: {{ editRowData?.id }}</Badge>
        </DialogTitle>
        <DialogDescription class="text-xs text-slate-500 mt-1">
          与表格全量 36 个表头字段完全对齐，单行直列展开，修改后点击底部保存生效。
        </DialogDescription>
      </DialogHeader>

      <!-- 独立垂直滚动内容区 Body (全量 36 个表格表头字段，单列纯中文 Label + Input) -->
      <div class="flex-1 overflow-y-auto p-6 space-y-4 text-xs custom-table-scrollbar">
        
        <!-- 1. 原项目名称 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">原项目名称</FieldLabel>
          <Input v-model="editRowData.title" placeholder="输入原项目名称..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 2. 规范剧目名称 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="font-bold" style="color: var(--primary)">规范剧目名称</FieldLabel>
          <Input v-model="editRowData.norm_title" placeholder="输入规范剧目名称..." class="h-9 text-xs font-semibold border-[var(--primary)] text-slate-900 dark:text-slate-100 w-full" />
        </Field>

        <!-- 3. 城市 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">城市</FieldLabel>
          <Input v-model="editRowData.city" placeholder="输入城市..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 4. 所在区 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">所在区</FieldLabel>
          <Input v-model="editRowData.district" placeholder="输入所在行政区..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 5. 原始剧场 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">原始剧场</FieldLabel>
          <Input v-model="editRowData.venue_name" placeholder="输入原始剧场名称..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 6. 规范剧场 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="font-bold text-slate-700 dark:text-slate-300">规范剧场</FieldLabel>
          <Input v-model="editRowData.norm_venue" placeholder="输入规范剧场名称..." class="h-9 text-xs font-semibold w-full" />
        </Field>

        <!-- 7. 场馆综合体 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">场馆综合体</FieldLabel>
          <Input v-model="editRowData.venue_complex" placeholder="输入场馆综合体..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 8. 场馆座位数 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">场馆座位数</FieldLabel>
          <Input v-model="editRowData.venue_seats" placeholder="输入场馆座位数..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 9. 场馆类型（新标准） -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">场馆类型（新标准）</FieldLabel>
          <Input v-model="editRowData.venue_type" placeholder="输入场馆类型..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 10. 区号 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">区号</FieldLabel>
          <Input v-model="editRowData.area_code" placeholder="输入区号..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 11. 演艺集聚区 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演艺集聚区</FieldLabel>
          <Input v-model="editRowData.yanyi_cluster" placeholder="输入演艺集聚区..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 12. 演出时间 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="font-bold text-slate-700 dark:text-slate-300">演出时间</FieldLabel>
          <Input v-model="editRowData.start_time" placeholder="输入演出时间 YYYY-MM-DD HH:mm..." class="h-9 text-xs font-semibold w-full" />
        </Field>

        <!-- 13. 年份 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">年份</FieldLabel>
          <Input v-model="editRowData.year" placeholder="输入年份..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 14. 月份 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">月份</FieldLabel>
          <Input v-model="editRowData.month" placeholder="输入月份..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 15. 季度 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">季度</FieldLabel>
          <Input v-model="editRowData.quarter" placeholder="输入季度..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 16. 日 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">日</FieldLabel>
          <Input v-model="editRowData.day" placeholder="输入日..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 17. 星期 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">星期</FieldLabel>
          <Input v-model="editRowData.weekday" placeholder="输入星期..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 18. 节假日 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">节假日</FieldLabel>
          <Input v-model="editRowData.holiday" placeholder="输入节假日..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 19. 演出大类 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演出大类</FieldLabel>
          <Input v-model="editRowData.category" placeholder="输入演出大类..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 20. 演出二级分类 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演出二级分类</FieldLabel>
          <Input v-model="editRowData.subcategory" placeholder="输入演出二级分类..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 21. 演出三级分类 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演出三级分类</FieldLabel>
          <Input v-model="editRowData.sub_sub_category" placeholder="输入演出三级分类..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 22. 演艺之都分类 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演艺之都分类</FieldLabel>
          <Input v-model="editRowData.yanyi_capital_cat" placeholder="输入演艺之都分类..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 23. 类型顺序 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">类型顺序</FieldLabel>
          <Input v-model="editRowData.cat_order" placeholder="输入类型顺序..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 24. 演出团体 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演出团体</FieldLabel>
          <Input v-model="editRowData.troupe" placeholder="输入演出团体..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 25. 团体城市 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">团体城市</FieldLabel>
          <Input v-model="editRowData.group_city" placeholder="输入团体城市..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 26. 院团属性 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">院团属性</FieldLabel>
          <Input v-model="editRowData.troupe_attr" placeholder="输入院团属性..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 27. 港澳台 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">港澳台</FieldLabel>
          <Input v-model="editRowData.hk_mo_tw" placeholder="输入港澳台属性..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 28. 出品/主办方名称 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">出品/主办方名称</FieldLabel>
          <Input v-model="editRowData.organizer" placeholder="输入主办方名称..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 29. 主办方城市 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">主办方城市</FieldLabel>
          <Input v-model="editRowData.organizer_city" placeholder="输入主办方城市..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 30. 演员/演职人员 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">演员/演职人员</FieldLabel>
          <Input v-model="editRowData.performers" placeholder="输入主要演员/艺人..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 31. 最低票价 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">最低票价</FieldLabel>
          <Input v-model="editRowData.min_price" placeholder="输入最低票价..." class="h-9 text-xs font-mono w-full" />
        </Field>

        <!-- 32. 最高票价 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">最高票价</FieldLabel>
          <Input v-model="editRowData.max_price" placeholder="输入最高票价..." class="h-9 text-xs font-mono w-full" />
        </Field>

        <!-- 33. 票价档位 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">票价档位</FieldLabel>
          <Input 
            :model-value="typeof editRowData.price === 'object' ? JSON.stringify(editRowData.price) : editRowData.price" 
            @update:model-value="(v) => editRowData.price = v"
            placeholder="例如: 120, 280, 680" 
            class="h-9 text-xs font-mono w-full" 
          />
        </Field>

        <!-- 34. 场次统计 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">场次统计</FieldLabel>
          <Input v-model="editRowData.session_count" placeholder="输入场次数..." class="h-9 text-xs w-full" />
        </Field>

        <!-- 35. 项目详情链接 -->
        <Field class="space-y-1.5 w-full">
          <FieldLabel class="text-slate-600 dark:text-slate-400 font-semibold">项目详情链接</FieldLabel>
          <Input v-model="editRowData.url" placeholder="输入项目链接 URL..." class="h-9 text-xs font-mono w-full" />
        </Field>

      </div>

      <!-- 固定置底 Footer (永久固定吸底，不随内容滚动) -->
      <DialogFooter class="p-4 px-6 border-t border-slate-100 dark:border-slate-800 bg-slate-50/90 dark:bg-slate-900/90 shrink-0 flex items-center justify-between gap-4">
        <span class="text-xs text-slate-400">修改直接作用于当前条目数据</span>
        <div class="flex items-center gap-3">
          <Button variant="outline" class="h-9 text-xs px-5" @click="isOpen = false">
            取消
          </Button>
          <Button variant="default" class="btn-theme-primary h-9 text-xs px-7 font-bold shadow-sm" @click="handleSave">
            保存全量变更
          </Button>
        </div>
      </DialogFooter>

    </DialogContent>
  </Dialog>
</template>

<style scoped>
/* 结合主题色的通用主按钮类 */
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
</style>
