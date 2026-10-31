export default [
  { path: 'invoices', component: () => import('./InvoicesPage.vue'), meta: { perm: 'billing.view_invoice' } },
  { path: 'invoices/:id', component: () => import('./InvoicePage.vue'), props: true, meta: { perm: 'billing.view_invoice' } },
  { path: 'reports/performers', component: () => import('./PerformersReport.vue'), meta: { perm: 'billing.view_invoice' } },
]
