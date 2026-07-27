<script setup>
import { computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  imageUrl: {
    type: String,
    default: ''
  },
  title: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:open'])

const isOpen = computed({
  get: () => props.open,
  set: (val) => emit('update:open', val)
})
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="max-w-lg p-5 flex flex-col items-center justify-center">
      <DialogHeader class="w-full text-center">
        <DialogTitle v-if="title" class="text-base font-semibold">{{ title }}</DialogTitle>
      </DialogHeader>
      <div class="mt-2 rounded-lg overflow-hidden border max-h-[75vh]">
        <img :src="imageUrl" :alt="title" class="object-contain max-h-[70vh] w-auto" />
      </div>
    </DialogContent>
  </Dialog>
</template>
