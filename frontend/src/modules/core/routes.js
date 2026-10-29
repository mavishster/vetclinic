export default [
  { path: '', component: () => import('./HomePage.vue') },
  { path: 'profile', component: () => import('./ProfilePage.vue') },
  { path: 'roles', component: () => import('./RolesPage.vue'), meta: { perm: 'auth.view_group' } },
]
