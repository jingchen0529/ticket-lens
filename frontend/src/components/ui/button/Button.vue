<script setup>
import { Primitive } from 'radix-vue'
import { cn } from '@/lib/utils'
import { buttonVariants } from '.'

const props = defineProps({
  variant: { type: String, required: false, default: 'default' },
  size: { type: String, required: false, default: 'default' },
  class: { type: [String, Object, Array], required: false, default: '' },
  asChild: { type: Boolean, required: false, default: false },
  as: { type: String, required: false, default: 'button' },
})
</script>

<template>
  <Primitive
    v-bind="$attrs"
    :as="as"
    :as-child="asChild"
    :class="cn(buttonVariants({ variant, size }), props.class)"
  >
    <slot />
  </Primitive>
</template>
