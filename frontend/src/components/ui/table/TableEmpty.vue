<script setup>
import TableCell from './TableCell.vue'
import TableRow from './TableRow.vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: [String, Object, Array], required: false, default: '' },
  colspan: { type: Number, required: false, default: 1 },
})
</script>

<template>
  <TableRow>
    <TableCell
      :class="
        cn(
          'p-8 text-center align-middle text-sm text-muted-foreground whitespace-nowrap',
          props.class,
        )
      "
      :colspan="colspan"
    >
      <slot />
    </TableCell>
  </TableRow>
</template>
