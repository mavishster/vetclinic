// Меню. Пункт виден, если у пользователя есть право perm.
// Пункт без маршрута — модуль в разработке, с номером этапа из docs/PROJECT_PLAN.md (раздел 8).
export default [
  {
    items: [{ title: 'Главная', icon: 'home', to: '/' }],
  },
  {
    title: 'Работа',
    items: [
      { title: 'Клиенты', icon: 'people', to: '/clients', perm: 'clients.view_client' },
      { title: 'Питомцы', icon: 'pets', to: '/pets', perm: 'clients.view_pet' },
      { title: 'Календарь', icon: 'event', stage: 3 },
      { title: 'Медкарта', icon: 'medical_information', stage: 3 },
      { title: 'Счета', icon: 'receipt_long', stage: 3 },
      { title: 'Касса', icon: 'point_of_sale', stage: 3 },
      { title: 'Склад', icon: 'inventory_2', stage: 3 },
      { title: 'Товары и услуги', icon: 'sell', stage: 2 },
      { title: 'Стационар', icon: 'bed', stage: 6 },
      { title: 'Лаборатория', icon: 'biotech', stage: 6 },
      { title: 'Отчёты', icon: 'bar_chart', stage: 6 },
    ],
  },
  {
    title: 'Справочники',
    items: [
      { title: 'Виды животных', icon: 'category', to: '/directories/species', perm: 'clients.view_species' },
      { title: 'Породы', icon: 'list', to: '/directories/breeds', perm: 'clients.view_breed' },
      { title: 'Окрасы', icon: 'palette', to: '/directories/colors', perm: 'clients.view_color' },
      { title: 'Города', icon: 'location_city', to: '/directories/cities', perm: 'clients.view_city' },
      { title: 'Улицы', icon: 'signpost', to: '/directories/streets', perm: 'clients.view_street' },
      { title: 'Типы клиентов', icon: 'label', to: '/directories/client-types', perm: 'clients.view_clienttype' },
      { title: 'Категории файлов', icon: 'folder', to: '/directories/file-categories', perm: 'core.view_filecategory' },
      { title: 'Как нашли клинику', icon: 'campaign', to: '/directories/client-sources', perm: 'clients.view_clientsource' },
    ],
  },
  {
    title: 'Администрирование',
    items: [
      { title: 'Роли и права', icon: 'admin_panel_settings', to: '/roles', perm: 'auth.view_group' },
      { title: 'Сотрудники', icon: 'badge', stage: 2 },
    ],
  },
]
