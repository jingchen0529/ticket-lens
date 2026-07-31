<script setup>
import { PaginationPrev, useForwardProps } from 'radix-vue'
import { ChevronLeft } from 'lucide-vue-next'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const props = defineProps({
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
  class: { type: [String, Object, Array], required: false, default: '' },
})

const forwarded = useForwardProps(props)
</script>

<template>
  <PaginationPrev
    v-bind="forwarded"
    :class="
      cn(
        buttonVariants({ variant: 'outline', size: 'icon' }),
        'h-8 w-8',
        props.class,
      )
    "
  >
    <slot>
      <ChevronLeft class="h-4 w-4" />
    </slot>
  </PaginationPrev>
</template>
