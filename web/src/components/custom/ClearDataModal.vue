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
  },
  clearing: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:open', 'clear'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})

function handleClear(scope) {
  emit('clear', scope)
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="max-w-2xl p-7">
      <DialogHeader class="space-y-3">
        <DialogTitle class="flex items-center gap-2.5 text-xl font-bold text-destructive">
          <div class="w-9 h-9 rounded-full bg-red-100 dark:bg-red-950 flex items-center justify-center text-destructive shrink-0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </div>
          <span>批量清除数据确认</span>
        </DialogTitle>
        <DialogDescription class="space-y-3 pt-2 text-sm leading-relaxed">
          <div>
            <template v-if="selectedCount > 0">
              您当前勾选了 <strong class="text-pink-600 font-bold text-base">{{ selectedCount }}</strong> 条记录，符合筛选条件的记录共 <strong class="text-blue-600 font-bold text-base">{{ total }}</strong> 条。请选择要清除的数据范围：
            </template>
            <template v-else>
              符合当前筛选条件的演出数据共 <strong class="text-blue-600 font-bold text-base">{{ total }}</strong> 条。请选择要清除的数据范围：
            </template>
          </div>
          <div class="p-3 bg-red-50 dark:bg-red-950/40 rounded-lg border border-red-200 dark:border-red-900 text-destructive text-xs font-medium">
            ⚠️ 清除操作会直接连带删除对应的数据库原始记录，此操作不可撤销！清除后需重新在「数据采集」页获取数据。
          </div>
        </DialogDescription>
      </DialogHeader>

      <DialogFooter class="flex items-center justify-between sm:justify-between mt-6 pt-4 border-t">
        <Button variant="outline" size="default" class="px-5" @click="isOpen = false">取消</Button>
        <div class="flex items-center gap-3">
          <Button
            v-if="selectedCount > 0"
            variant="destructive"
            size="default"
            class="px-5 font-semibold"
            :disabled="clearing"
            @click="handleClear('selected')"
          >
            清除勾选 {{ selectedCount }} 条
          </Button>
          <Button
            variant="outline"
            size="default"
            class="border-destructive/40 text-destructive hover:bg-destructive/10 px-5 font-semibold"
            :disabled="clearing"
            @click="handleClear('filtered')"
          >
            清除筛选 {{ total }} 条
          </Button>
          <Button
            variant="destructive"
            size="default"
            class="px-5 font-semibold"
            :disabled="clearing"
            @click="handleClear('all')"
          >
            清除全部
          </Button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
