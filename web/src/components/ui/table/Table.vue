<script setup>
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], required: false, default: '' },
  wrapperClass: { type: [String, Object, Array], required: false, default: '' },
})
</script>

<template>
  <div :class="cn('relative w-full overflow-auto', props.wrapperClass)">
    <table :class="cn('w-full caption-bottom text-sm', props.class)">
      <slot />
    </table>
  </div>
</template>
