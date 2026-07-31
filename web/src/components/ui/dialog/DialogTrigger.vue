<script setup>
import { DialogTrigger } from 'radix-vue'

const props = defineProps({
  asChild: { type: Boolean, required: false },
  as: { type: String, required: false },
})
</script>

<template>
  <DialogTrigger v-bind="props">
    <slot />
  </DialogTrigger>
</template>
