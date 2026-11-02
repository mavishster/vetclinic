import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: 'inpatient', component: () => import('./InpatientPage.vue'), meta: { perm: 'inpatient.view_hospitalization' } },
  { path: 'inpatient/:id', component: () => import('./HospitalizationPage.vue'), props: true, meta: { perm: 'inpatient.view_hospitalization' } },
  {
    path: 'directories/wards',
    component: DirectoryPage,
    props: {
      title: 'Палаты', endpoint: 'inpatient/wards/', permission: 'inpatient.ward',
      fields: [
        { name: 'kind', label: 'Тип', type: 'choice', options: [
          { id: 'general', name: 'Общая' }, { id: 'intensive', name: 'Интенсивная терапия' }, { id: 'infectious', name: 'Инфекционный бокс' },
        ] },
        { name: 'places', label: 'Мест', type: 'number' },
        { name: 'daily_item', label: 'Услуга «сутки стационара»', endpoint: 'catalog/items/?kind=service', hint: 'Нужна для счёта за стационар', column: false },
      ],
    },
    meta: { perm: 'inpatient.view_ward' },
  },
]
