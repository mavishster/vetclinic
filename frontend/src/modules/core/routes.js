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
        { name: 'person_type', label: 'Лицо', type: 'choice', options: [{ id: 'legal', name: 'Юридическое' }, { id: 'individual', name: 'Физическое' }], column: false },
        { name: 'contact', label: 'Контактное лицо', type: 'text' },
        { name: 'phone', label: 'Телефон', type: 'text' },
        { name: 'city', label: 'Город', type: 'text', column: false },
        { name: 'address', label: 'Адрес', type: 'text', column: false },
        { name: 'email', label: 'Email', type: 'text', column: false },
        { name: 'inn', label: 'ИНН', type: 'text' },
        { name: 'kpp', label: 'КПП', type: 'text', column: false },
        { name: 'bik', label: 'БИК', type: 'text', column: false },
        { name: 'correspondent_account', label: 'Корр. счёт', type: 'text', column: false },
        { name: 'settlement_account', label: 'Расчётный счёт', type: 'text', column: false },
        { name: 'bank_name', label: 'Наименование банка', type: 'text', column: false },
        { name: 'note', label: 'Примечание', type: 'text', column: false },
        { name: 'for_receipts', default: true, label: 'Показывать в приходных накладных', type: 'checkbox', column: false },
        { name: 'for_write_offs', default: true, label: 'Показывать в расходных накладных', type: 'checkbox', column: false },
        { name: 'for_cash', default: true, label: 'Показывать в кассовых документах', type: 'checkbox', column: false },
      ],
    },
    meta: { perm: 'core.view_counterparty' },
  },
  { path: 'roles', component: () => import('./RolesPage.vue'), meta: { perm: 'auth.view_group' } },
  { path: 'print-templates', component: () => import('./PrintTemplatesPage.vue'), meta: { perm: 'core.view_printtemplate' } },
]
