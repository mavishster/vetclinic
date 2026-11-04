import DirectoryPage from '@/components/DirectoryPage.vue'

export const DOC_KINDS = {
  receipt: { label: 'Приход', icon: 'move_to_inbox', color: 'positive' },
  write_off: { label: 'Расход', icon: 'outbox', color: 'negative' },
  transfer: { label: 'Перемещение', icon: 'swap_horiz', color: 'primary' },
  inventory: { label: 'Инвентаризация', icon: 'fact_check', color: 'warning' },
  return: { label: 'Возврат поставщику', icon: 'assignment_return', color: 'deep-orange' },
}

export default [
  { path: 'inventory/stock', component: () => import('./StockPage.vue'), meta: { perm: 'inventory.view_stockmovement' } },
  { path: 'inventory/documents', component: () => import('./DocumentsPage.vue'), meta: { perm: 'inventory.view_stockdocument' } },
  { path: 'inventory/transfer', component: () => import('./TransferPage.vue'), meta: { perm: 'inventory.add_stockdocument' } },
  { path: 'inventory/department-writeoff', component: () => import('./TransferPage.vue'), props: { department: true }, meta: { perm: 'inventory.add_stockdocument' } },
  {
    path: 'directories/departments',
    component: DirectoryPage,
    props: { title: 'Отделения', endpoint: 'inventory/departments/', permission: 'inventory.department',
      fields: [{ name: 'responsible', label: 'Ответственный', endpoint: 'core/users/' }] },
    meta: { perm: 'inventory.view_department' },
  },
  { path: 'inventory/documents/:id', component: () => import('./DocumentPage.vue'), props: true, meta: { perm: 'inventory.view_stockdocument' } },
  {
    path: 'directories/warehouses',
    component: DirectoryPage,
    props: {
      title: 'Склады', endpoint: 'inventory/warehouses/', permission: 'inventory.warehouse',
      fields: [
        { name: 'kind', label: 'Назначение', type: 'choice', options: [{ id: 'sale', name: 'Продажа (оперативный)' }, { id: 'storage', name: 'Хранение (основной)' }] },
        { name: 'access_roles', label: 'Видят роли', type: 'multi', endpoint: 'core/roles/', emptyText: 'все',
          hint: 'Пусто — склад видят все, у кого есть право на склад. Иначе — только эти роли' },
      ],
    },
    meta: { perm: 'inventory.view_warehouse' },
  },
  {
    path: 'directories/manufacturers',
    component: DirectoryPage,
    props: { title: 'Производители', endpoint: 'inventory/manufacturers/', permission: 'inventory.manufacturer' },
    meta: { perm: 'inventory.view_manufacturer' },
  },
]
