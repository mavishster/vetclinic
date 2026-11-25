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
import vetmanagerRoutes from './modules/vetmanager/routes'
import inpatientRoutes from './modules/inpatient/routes'
import laboratoryRoutes from './modules/laboratory/routes'
import billingRoutes from './modules/billing/routes'
import { can, loadMe, session } from './session'

// Каждый модуль приносит свои маршруты из src/modules/<модуль>/routes.js
// (PROJECT_PLAN, 4.3, правило 7). Новый модуль — одна строка здесь.
const moduleRoutes = [...coreRoutes, ...clientsRoutes, ...catalogRoutes, ...staffRoutes, ...schedulingRoutes, ...medicalRoutes, ...inventoryRoutes, ...billingRoutes, ...cashRoutes, ...reportsRoutes, ...remindersRoutes,
      ...vetmanagerRoutes, ...inpatientRoutes, ...laboratoryRoutes]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      component: () => import('./modules/core/LoginPage.vue'),
      meta: { public: true },
    },
    // Экран подписи для планшета у стойки — на весь экран, без меню.
    { path: '/signing', component: () => import('./modules/signing/SigningScreen.vue'), meta: { perm: 'clients.sign_on_station' } },
    // Экран очереди для телевизора в холле — тоже на весь экран, без меню.
    { path: '/queue', component: () => import('./modules/scheduling/QueueScreen.vue'), meta: { perm: ['scheduling.queue_screen', 'scheduling.view_appointment'] } },
    { path: '/', component: MainLayout, children: moduleRoutes },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// Без входа — на страницу входа; без права — на главную.
router.beforeEach(async (to) => {
  if (!session.loaded) await loadMe()
  if (to.meta.public) return true
  if (!session.user) return { path: '/login', query: { next: to.fullPath } }
  // Учётная запись устройства (планшет подписи, экран очереди) видит только свой экран.
  const device = deviceScreen()
  if (device && to.path !== device) return device
  if (to.meta.perm && !can(to.meta.perm)) return '/'
  return true
})

// Право устройства → его единственный экран.
const DEVICE_SCREENS = { 'clients.sign_on_station': '/signing', 'scheduling.queue_screen': '/queue' }

function deviceScreen() {
  const perms = session.user?.permissions || []
  // Только право устройства и ничего больше — это устройство, а не сотрудник.
  if (session.user?.is_superuser || perms.length !== 1) return null
  return DEVICE_SCREENS[perms[0]] ?? null
}

export default router
