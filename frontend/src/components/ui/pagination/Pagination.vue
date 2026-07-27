<script setup>
import { PaginationRoot, useForwardPropsEmits } from 'radix-vue'

const props = defineProps({
  page: { type: Number, required: false },
  defaultPage: { type: Number, required: false },
  itemsPerPage: { type: Number, required: false, default: 10 },
  total: { type: Number, required: true },
  siblingCount: { type: Number, required: false, default: 1 },
  showEdges: { type: Boolean, required: false, default: false },
  disabled: { type: Boolean, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
})

const emits = defineEmits(['update:page'])
const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <PaginationRoot v-bind="forwarded">
    <slot />
  </PaginationRoot>
</template>
