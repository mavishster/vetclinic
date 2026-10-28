import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from './layouts/MainLayout.vue'
import coreRoutes from './modules/core/routes'

// Каждый модуль приносит свои маршруты из src/modules/<модуль>/routes.js
// (PROJECT_PLAN, 4.3, правило 7). Новый модуль — одна строка здесь.
const moduleRoutes = [...coreRoutes]

export default createRouter({
  history: createWebHistory(),
  routes: [{ path: '/', component: MainLayout, children: moduleRoutes }],
})
