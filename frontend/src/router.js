import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from './layouts/MainLayout.vue'
import coreRoutes from './modules/core/routes'
import clientsRoutes from './modules/clients/routes'
import catalogRoutes from './modules/catalog/routes'
import staffRoutes from './modules/staff/routes'
import schedulingRoutes from './modules/scheduling/routes'
import medicalRoutes from './modules/medical/routes'
import inventoryRoutes from './modules/inventory/routes'
import cashRoutes from './modules/cash/routes'
import reportsRoutes from './modules/reports/routes'
import remindersRoutes from './modules/reminders/routes'
import inpatientRoutes from './modules/inpatient/routes'
import laboratoryRoutes from './modules/laboratory/routes'
import billingRoutes from './modules/billing/routes'
import { can, loadMe, session } from './session'

// Каждый модуль приносит свои маршруты из src/modules/<модуль>/routes.js
// (PROJECT_PLAN, 4.3, правило 7). Новый модуль — одна строка здесь.
const moduleRoutes = [...coreRoutes, ...clientsRoutes, ...catalogRoutes, ...staffRoutes, ...schedulingRoutes, ...medicalRoutes, ...inventoryRoutes, ...billingRoutes, ...cashRoutes, ...reportsRoutes, ...remindersRoutes, ...inpatientRoutes, ...laboratoryRoutes]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      component: () => import('./modules/core/LoginPage.vue'),
      meta: { public: true },
    },
    { path: '/', component: MainLayout, children: moduleRoutes },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// Без входа — на страницу входа; без права — на главную.
router.beforeEach(async (to) => {
  if (!session.loaded) await loadMe()
  if (to.meta.public) return true
  if (!session.user) return { path: '/login', query: { next: to.fullPath } }
  if (to.meta.perm && !can(to.meta.perm)) return '/'
  return true
})

export default router
