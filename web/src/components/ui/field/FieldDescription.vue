<script setup>
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], default: '' }
})
</script>

<template>
  <p :class="cn('text-[11px] text-muted-foreground', props.class)">
    <slot />
  </p>
</template>
