import { reactive } from 'vue'

export interface ToastItem {
  id: number
  text: string
  tone: 'info' | 'ok' | 'warn' | 'danger'
  ttl: number
}

const state = reactive<{ items: ToastItem[] }>({ items: [] })
let seq = 0

export function useToast() {
  return {
    items: state.items,
    push(text: string, tone: ToastItem['tone'] = 'info', ttl = 2600) {
      const id = ++seq
      state.items.push({ id, text, tone, ttl })
      window.setTimeout(() => {
        const i = state.items.findIndex((t) => t.id === id)
        if (i >= 0) state.items.splice(i, 1)
      }, ttl)
    },
  }
}

/** 组件外也能直接调用 */
export function toast(text: string, tone: ToastItem['tone'] = 'info', ttl = 2600) {
  useToast().push(text, tone, ttl)
}
