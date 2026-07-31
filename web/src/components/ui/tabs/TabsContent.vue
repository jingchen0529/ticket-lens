<script setup>
import { TabsContent, useForwardProps } from 'radix-vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  value: { type: String, required: true },
  forceMount: { type: Boolean, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
  class: { type: [String, Object, Array], required: false, default: '' },
})

const forwarded = useForwardProps(props)
</script>

<template>
  <TabsContent
    v-bind="forwarded"
    :class="
      cn(
        'mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        props.class,
      )
    "
  >
    <slot />
  </TabsContent>
</template>
