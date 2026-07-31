<script setup>
import { PaginationEllipsis, useForwardProps } from 'radix-vue'
import { MoreHorizontal } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = defineProps({
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
  class: { type: [String, Object, Array], required: false, default: '' },
})

const forwarded = useForwardProps(props)
</script>

<template>
  <PaginationEllipsis
    v-bind="forwarded"
    :class="cn('flex h-8 w-8 items-center justify-center', props.class)"
  >
    <slot>
      <MoreHorizontal class="h-4 w-4" />
    </slot>
  </PaginationEllipsis>
</template>
