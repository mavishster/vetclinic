import DirectoryPage from '@/components/DirectoryPage.vue'

export const KINDS = [
  { id: 'goods', name: 'Товары' },
  { id: 'service', name: 'Услуги' },
]

export default [
  { path: 'catalog', component: () => import('./CatalogPage.vue'), meta: { perm: 'catalog.view_item' } },
  {
    path: 'directories/item-groups',
    component: DirectoryPage,
    props: {
      title: 'Группы товаров и услуг',
      endpoint: 'catalog/groups/',
      permission: 'catalog.itemgroup',
      fields: [
        { name: 'kind', label: 'Для чего', type: 'choice', options: KINDS },
        { name: 'markup_percent', label: 'Наценка, %', type: 'number', hint: 'Для товаров без своей наценки. Пусто — нет' },
        { name: 'show_in_vaccinations', label: 'Показывать в вакцинациях', type: 'checkbox' },
      ],
    },
    meta: { perm: 'catalog.view_itemgroup' },
  },
  {
    path: 'directories/units',
    component: DirectoryPage,
    props: { title: 'Единицы измерения', endpoint: 'catalog/units/', permission: 'catalog.unit' },
    meta: { perm: 'catalog.view_unit' },
  },
]
