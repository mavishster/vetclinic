import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: '', component: () => import('./HomePage.vue') },
  { path: 'profile', component: () => import('./ProfilePage.vue') },
  {
    path: 'directories/file-categories',
    component: DirectoryPage,
    props: { title: 'Категории файлов', endpoint: 'core/file-categories/', permission: 'core.filecategory' },
    meta: { perm: 'core.view_filecategory' },
  },
  { path: 'roles', component: () => import('./RolesPage.vue'), meta: { perm: 'auth.view_group' } },
]
