import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: 'cash', component: () => import('./CashPage.vue'), meta: { perm: 'cash.view_cashmovement' } },
  {
    path: 'directories/cash-registers',
    component: DirectoryPage,
    props: {
      title: 'Кассы', endpoint: 'cash/registers/', permission: 'cash.cashregister',
      fields: [{ name: 'kind', label: 'Вид', type: 'choice', options: [{ id: 'cash', name: 'Наличные' }, { id: 'cashless', name: 'Безнал (терминал, перевод)' }] }],
    },
    meta: { perm: 'cash.view_cashregister' },
  },
]
