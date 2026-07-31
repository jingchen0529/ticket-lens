<script setup>
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], default: '' }
})
</script>

<template>
  <Label :class="cn('text-xs font-semibold text-foreground leading-none', props.class)">
    <slot />
  </Label>
</template>
