<script setup>
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
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
  columns: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:open', 'save'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})

const visibleColumns = computed(() => props.columns.filter(c => c.visible))
const totalColumns = computed(() => props.columns.length)

function selectAllColumns() {
  props.columns.forEach(c => (c.visible = true))
}

function invertColumns() {
  props.columns.forEach(c => (c.visible = !c.visible))
}

function resetDefaultColumns() {
  props.columns.forEach(c => (c.visible = true))
}

function handleClose() {
  isOpen.value = false
}

function handleSave() {
  emit('save')
  isOpen.value = false
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="max-w-2xl">
      <DialogHeader>
        <DialogTitle class="flex items-center justify-between pr-4">
          <span class="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.5">
              <path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7m0-18H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7m0-18v18" />
            </svg>
            列显示与隐藏设置
          </span>
          <Badge variant="secondary">显示 {{ visibleColumns.length }} / {{ totalColumns }} 列</Badge>
        </DialogTitle>
        <DialogDescription>
          💡 勾选决定表格是否展示该数据列。修改后可保存个人配置。
        </DialogDescription>
      </DialogHeader>

      <!-- 快捷操作栏 -->
      <div class="flex items-center justify-between py-2 border-y bg-muted/40 px-3 rounded-md">
        <div class="flex items-center gap-2">
          <Button variant="outline" size="sm" class="h-7 text-xs" @click="selectAllColumns">全选所有字段</Button>
          <Button variant="outline" size="sm" class="h-7 text-xs" @click="invertColumns">反选</Button>
          <Button variant="ghost" size="sm" class="h-7 text-xs" @click="resetDefaultColumns">重置默认</Button>
        </div>
      </div>

      <!-- 2列卡片网格 -->
      <div class="max-h-[350px] overflow-y-auto pr-1">
        <div class="grid grid-cols-2 gap-2">
          <label
            v-for="col in columns"
            :key="col.key"
            class="flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer hover:bg-accent transition-colors"
            :class="{ 'border-primary bg-primary/5': col.visible }"
          >
            <Checkbox :checked="col.visible" @update:checked="(v) => (col.visible = v)" />
            <span class="font-medium text-foreground">{{ col.title }}</span>
            <span class="text-muted-foreground text-[11px]">({{ col.key }})</span>
          </label>
        </div>
      </div>

      <DialogFooter class="flex items-center justify-between sm:justify-between">
        <span class="text-xs text-muted-foreground">
          已有 {{ visibleColumns.length }} 个字段生效
        </span>
        <div class="flex items-center gap-2">
          <Button variant="outline" size="sm" @click="handleClose">关闭</Button>
          <Button variant="default" size="sm" class="bg-pink-600 hover:bg-pink-700 text-white" @click="handleSave">保存配置</Button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
