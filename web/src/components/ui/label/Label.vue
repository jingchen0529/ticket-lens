<script setup>
import { Label, useForwardProps } from 'radix-vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  for: { type: String, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
  class: { type: [String, Object, Array], required: false, default: '' },
})

const forwarded = useForwardProps(props)
</script>

<template>
  <Label
    v-bind="forwarded"
    :class="
      cn(
        'text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
        props.class,
      )
    "
  >
    <slot />
  </Label>
</template>
