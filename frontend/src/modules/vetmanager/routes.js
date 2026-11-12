export default [
  {
    path: 'vetmanager-tidy',
    component: () => import('./TidyPage.vue'),
    meta: { perm: 'vetmanager.run_import' },
  },
  {
    path: 'vetmanager-import',
    component: () => import('./ImportPage.vue'),
    meta: { perm: 'vetmanager.run_import' },
  },
]
