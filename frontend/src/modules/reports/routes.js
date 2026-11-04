export default [
  { path: 'reports', component: () => import('./ReportsPage.vue'), meta: { perm: ['billing.view_invoice', 'inventory.view_stockmovement'] } },
]
