export default [
  {
    path: 'vetmanager-import',
    component: () => import('./ImportPage.vue'),
    meta: { perm: 'vetmanager.run_import' },
  },
]
