<script setup>
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], default: '' }
})
</script>

<template>
  <p :class="cn('text-xs font-medium text-destructive', props.class)">
    <slot />
  </p>
</template>
