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
  {
    path: 'directories/counterparties',
    component: DirectoryPage,
    props: {
      title: 'Контрагенты', endpoint: 'core/counterparties/', permission: 'core.counterparty',
      fields: [
        { name: 'inn', label: 'ИНН', type: 'text' }, { name: 'phone', label: 'Телефон', type: 'text' },
        { name: 'email', label: 'Email', type: 'text' }, { name: 'contact', label: 'Контактное лицо', type: 'text' },
      ],
    },
    meta: { perm: 'core.view_counterparty' },
  },
  { path: 'roles', component: () => import('./RolesPage.vue'), meta: { perm: 'auth.view_group' } },
]
