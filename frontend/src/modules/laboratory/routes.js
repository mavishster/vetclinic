import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: 'laboratory', component: () => import('./LaboratoryPage.vue'), meta: { perm: 'laboratory.view_labresult' } },
  {
    path: 'directories/analytes',
    component: DirectoryPage,
    props: {
      title: 'Показатели анализов', endpoint: 'laboratory/analytes/', permission: 'laboratory.analyte',
      fields: [
        { name: 'code', label: 'Код прибора', type: 'text' },
        { name: 'unit', label: 'Единица', type: 'text' },
        { name: 'group', label: 'Группа', type: 'text' },
      ],
    },
    meta: { perm: 'laboratory.view_analyte' },
  },
]
