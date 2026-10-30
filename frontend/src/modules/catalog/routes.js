import DirectoryPage from '@/components/DirectoryPage.vue'

// Вид профилактики у группы: товары группы предлагаются в медкарте для этой процедуры.
export const PREVENTION_KINDS = [
  { id: '', name: '—' },
  { id: 'vaccination', name: 'Вакцинация' },
  { id: 'deworming', name: 'Дегельминтизация' },
  { id: 'ectoparasites', name: 'Обработка от эктопаразитов' },
  { id: 'sterilization', name: 'Стерилизация / кастрация' },
  { id: 'chipping', name: 'Чипирование' },
]

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
        { name: 'prevention_kind', label: 'Профилактика', type: 'choice', options: PREVENTION_KINDS },
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
