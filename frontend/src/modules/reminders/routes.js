export default [
  { path: 'reminders', component: () => import('./RemindersPage.vue'), meta: { perm: 'reminders.view_reminder' } },
]
