import DirectoryPage from '@/components/DirectoryPage.vue'

// Справочник — общий экран DirectoryPage с параметрами (DRY).
const directory = (path, title, permission, fields = []) => ({
  path: `directories/${path}`,
  component: DirectoryPage,
  props: { title, endpoint: `clients/${path}/`, permission: `clients.${permission}`, fields },
  meta: { perm: `clients.view_${permission}` },
})

export default [
  directory('signing-stations', 'Планшеты подписи', 'signingstation', [
    { name: 'user', label: 'Учётная запись планшета', endpoint: 'core/users/',
      hint: 'Отдельный пользователь с ролью «Планшет подписи» — создайте его в «Сотрудниках»' },
  ]),
  { path: 'clients', component: () => import('./ClientsPage.vue'), meta: { perm: 'clients.view_client' } },
  { path: 'clients/:id', component: () => import('./ClientPage.vue'), props: true, meta: { perm: 'clients.view_client' } },
  { path: 'pets', component: () => import('./PetsPage.vue'), meta: { perm: 'clients.view_pet' } },
  { path: 'pets/:id', component: () => import('./PetPage.vue'), props: true, meta: { perm: 'clients.view_pet' } },
  directory('species', 'Виды животных', 'species'),
  directory('breeds', 'Породы', 'breed', [{ name: 'species', label: 'Вид', endpoint: 'clients/species/' }]),
  directory('colors', 'Окрасы', 'color'),
  directory('cities', 'Города', 'city'),
  directory('streets', 'Улицы', 'street', [{ name: 'city', label: 'Город', endpoint: 'clients/cities/' }]),
  directory('client-types', 'Типы клиентов', 'clienttype'),
  directory('client-sources', 'Как нашли клинику', 'clientsource'),
]
