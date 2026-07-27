<script setup>
import { PaginationLast, useForwardProps } from 'radix-vue'
import { ChevronsRight } from 'lucide-vue-next'
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
  <PaginationLast
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
      <ChevronsRight class="h-4 w-4" />
    </slot>
  </PaginationLast>
</template>
