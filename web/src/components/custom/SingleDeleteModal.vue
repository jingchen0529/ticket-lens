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
  targetRow: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['update:open', 'confirm'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})

function handleConfirm() {
  emit('confirm')
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="max-w-lg p-7">
      <DialogHeader class="space-y-2">
        <DialogTitle class="flex items-center gap-2 text-xl font-bold text-destructive">
          <div class="w-8 h-8 rounded-full bg-red-100 dark:bg-red-950 flex items-center justify-center shrink-0">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </div>
          <span>确认删除该条演出记录？</span>
        </DialogTitle>
        <DialogDescription class="pt-2 text-sm leading-relaxed text-foreground">
          您即将彻底删除演出项目：
          <div class="mt-2 p-3 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 font-semibold text-red-900 dark:text-red-200">
            {{ targetRow?.title }}
          </div>
          <p class="mt-2 text-xs text-muted-foreground">
            ⚠️ 此删除操作属于二次确认保护，删除后该记录将直接从列表移除。
          </p>
        </DialogDescription>
      </DialogHeader>

      <DialogFooter class="mt-6 pt-3 border-t flex items-center justify-end gap-3">
        <Button variant="outline" @click="isOpen = false">取消</Button>
        <Button variant="destructive" class="px-6 font-semibold" @click="handleConfirm">
          确认删除
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
