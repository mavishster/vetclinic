import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: 'medical', component: () => import('./VisitsPage.vue'), meta: { perm: 'medical.view_visit' } },
  { path: 'medical/prevention', component: () => import('./PreventionReportPage.vue'), meta: { perm: 'medical.view_prevention' } },
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
    path: 'directories/prevention-types',
    component: DirectoryPage,
    props: {
      title: 'Виды профилактики', endpoint: 'medical/prevention-types/', permission: 'medical.preventiontype',
      fields: [
        { name: 'kind', label: 'Поведение', type: 'choice', options: [
          { id: 'vaccination', name: 'Вакцинация' }, { id: 'deworming', name: 'Дегельминтизация' },
          { id: 'ectoparasites', name: 'Обработка от эктопаразитов' }, { id: 'sterilization', name: 'Стерилизация / кастрация' },
          { id: 'chipping', name: 'Чипирование' }, { id: 'other', name: 'Другое' },
        ] },
        { name: 'repeat_days', label: 'Повтор через, дней', type: 'number', hint: 'Пусто — процедура однократная' },
        { name: 'item_required', label: 'Препарат обязателен', type: 'checkbox' },
      ],
    },
    meta: { perm: 'medical.view_preventiontype' },
  },
  {
    path: 'directories/visit-results',
    component: DirectoryPage,
    props: { title: 'Результаты посещения', endpoint: 'medical/results/', permission: 'medical.visitresult' },
    meta: { perm: 'medical.view_visitresult' },
  },
]
