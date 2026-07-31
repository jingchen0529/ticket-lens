<script setup>
import { PaginationList } from 'radix-vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], required: false, default: '' },
})
</script>

<template>
  <PaginationList
    v-slot="slotProps"
    :class="cn('flex items-center gap-1', props.class)"
  >
    <slot v-bind="slotProps" />
  </PaginationList>
</template>
