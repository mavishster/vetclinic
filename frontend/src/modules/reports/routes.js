export default [
  { path: 'reports', component: () => import('./ReportsPage.vue'), meta: { perm: 'core.view_reportsaccess' } },
]
