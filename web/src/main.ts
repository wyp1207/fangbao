import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
// 一期 UI 全用自写组件 + CSS 变量（styles/tokens.css），没有依赖任何组件库，
// 所以不装 Arco、也不引它 400KB 的全量样式。真要换组件库时再装，走按需引入。
import './styles/tokens.css'

createApp(App).use(createPinia()).use(router).mount('#app')
