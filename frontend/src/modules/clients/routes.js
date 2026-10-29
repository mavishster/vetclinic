import DirectoryPage from '@/components/DirectoryPage.vue'

// Справочники модуля «Клиенты и питомцы» — общий экран DirectoryPage с параметрами.
export default [
  {
    path: 'directories/species',
    component: DirectoryPage,
    props: { title: 'Виды животных', endpoint: 'clients/species/', permission: 'clients.species' },
    meta: { perm: 'clients.view_species' },
  },
  {
    path: 'directories/breeds',
    component: DirectoryPage,
    props: {
      title: 'Породы',
      endpoint: 'clients/breeds/',
      permission: 'clients.breed',
      fields: [{ name: 'species', label: 'Вид', endpoint: 'clients/species/' }],
    },
    meta: { perm: 'clients.view_breed' },
  },
]
