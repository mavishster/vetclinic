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
    path: 'directories/drug-groups',
    component: DirectoryPage,
    props: {
      title: 'Группы препаратов',
      endpoint: 'catalog/drug-groups/',
      permission: 'catalog.druggroup',
      hint: 'Группа по действию: противорвотное, анестетик, спазмолитик. По ней поиск предлагает препараты того же действия',
    },
    meta: { perm: 'catalog.view_druggroup' },
  },
  {
    path: 'directories/substances',
    component: DirectoryPage,
    props: {
      title: 'Действующие вещества',
      endpoint: 'catalog/substances/',
      permission: 'catalog.substance',
      hint: 'По веществу поиск находит аналоги препарата. У препарата их может быть несколько',
      fields: [
        { name: 'latin_name', label: 'Латинское название', type: 'text' },
        { name: 'synonyms', label: 'Другие названия', type: 'text', hint: 'Через запятую — по ним вещество тоже находится' },
        { name: 'group', label: 'Обычная группа', endpoint: 'catalog/drug-groups/', hint: 'Подставится препарату при выборе вещества' },
      ],
    },
    meta: { perm: 'catalog.view_substance' },
  },
  {
    path: 'directories/units',
    component: DirectoryPage,
    props: { title: 'Единицы измерения', endpoint: 'catalog/units/', permission: 'catalog.unit' },
    meta: { perm: 'catalog.view_unit' },
  },
]
