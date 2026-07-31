<script setup>
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], default: '' }
})
</script>

<template>
  <div :class="cn('space-y-1.5', props.class)">
    <slot />
  </div>
</template>
