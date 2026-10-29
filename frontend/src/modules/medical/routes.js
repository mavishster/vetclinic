import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: 'medical', component: () => import('./VisitsPage.vue'), meta: { perm: 'medical.view_visit' } },
  { path: 'visits/:id', component: () => import('./VisitPage.vue'), props: true, meta: { perm: 'medical.view_visit' } },
  {
    path: 'directories/diagnoses',
    component: DirectoryPage,
    props: {
      title: 'Диагнозы', endpoint: 'medical/diagnoses/', permission: 'medical.diagnosis',
      fields: [{ name: 'code', label: 'Код', type: 'text' }],
    },
    meta: { perm: 'medical.view_diagnosis' },
  },
  {
    path: 'directories/visit-results',
    component: DirectoryPage,
    props: { title: 'Результаты посещения', endpoint: 'medical/results/', permission: 'medical.visitresult' },
    meta: { perm: 'medical.view_visitresult' },
  },
]
