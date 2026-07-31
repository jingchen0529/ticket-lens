<script setup>
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
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
  selectedCount: {
    type: Number,
    default: 0
  },
  total: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['update:open', 'export'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})

function handleExport(scope) {
  emit('export', scope)
  isOpen.value = false
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="max-w-2xl p-7">
      <DialogHeader class="space-y-3">
        <DialogTitle class="flex items-center gap-2.5 text-xl font-bold">
          <div class="w-9 h-9 rounded-full bg-pink-100 dark:bg-pink-950 flex items-center justify-center text-pink-600 shrink-0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </div>
          <span>数据导出确认</span>
        </DialogTitle>
        <DialogDescription class="text-sm leading-relaxed pt-1">
          <template v-if="selectedCount > 0">
            您当前勾选了 <strong class="text-pink-600 font-bold text-base">{{ selectedCount }}</strong> 条记录，符合筛选条件的记录共 <strong class="text-blue-600 font-bold text-base">{{ total }}</strong> 条。请选择导出的范围：
          </template>
          <template v-else>
            符合当前筛选条件的演出数据共 <strong class="text-blue-600 font-bold text-base">{{ total }}</strong> 条，确认生成导出 Excel 文件吗？
          </template>
        </DialogDescription>
      </DialogHeader>

      <DialogFooter class="flex items-center justify-between sm:justify-between mt-6 pt-4 border-t">
        <Button variant="outline" size="default" class="px-5" @click="isOpen = false">取消</Button>
        <div class="flex items-center gap-3">
          <Button
            v-if="selectedCount > 0"
            variant="default"
            size="default"
            class="bg-pink-600 hover:bg-pink-700 text-white px-6 font-semibold shadow-md"
            @click="handleExport('selected')"
          >
            导出勾选的 {{ selectedCount }} 条
          </Button>
          <Button
            variant="outline"
            size="default"
            class="border-blue-300 text-blue-700 hover:bg-blue-50 px-6 font-semibold"
            @click="handleExport('all')"
          >
            导出全部 {{ total }} 条
          </Button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
