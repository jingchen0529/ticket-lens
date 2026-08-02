<script setup>
import { SelectValue } from 'radix-vue'

const props = defineProps({
  placeholder: { type: String, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
})
</script>

<template>
  <SelectValue v-bind="props" class="truncate" />
</template>
