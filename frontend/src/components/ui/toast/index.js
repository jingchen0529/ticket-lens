import { ref, reactive } from 'vue'

const toasts = ref([])
let count = 0

export function toast(options) {
  const id = ++count
  let title = ''
  let description = ''
  let variant = 'default' // 'default' | 'success' | 'destructive' | 'warning'
  let duration = 3500

  if (typeof options === 'string') {
    description = options
  } else if (typeof options === 'object' && options !== null) {
    title = options.title || ''
    description = options.description || options.message || ''
    variant = options.variant || options.type || 'default'
    if (options.duration) duration = options.duration
  }

  const toastItem = reactive({
    id,
    title,
    description,
    variant,
    duration,
    visible: true
  })

  toasts.value.push(toastItem)

  if (duration > 0) {
    setTimeout(() => {
      removeToast(id)
    }, duration)
  }

  return id
}

toast.success = (msg, opts = {}) => toast({ description: msg, variant: 'success', ...opts })
toast.error = (msg, opts = {}) => toast({ description: msg, variant: 'destructive', ...opts })
toast.info = (msg, opts = {}) => toast({ description: msg, variant: 'default', ...opts })
toast.warn = (msg, opts = {}) => toast({ description: msg, variant: 'warning', ...opts })

export function removeToast(id) {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
}

export function useToastStore() {
  return { toasts, removeToast }
}
