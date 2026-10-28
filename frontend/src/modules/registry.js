// Список модулей для меню. Модуль без маршрута показывается как «в разработке»
// с номером этапа из docs/PROJECT_PLAN.md (раздел 8).
export default [
  { title: 'Главная', icon: 'home', to: '/' },
  { title: 'Клиенты и питомцы', icon: 'pets', stage: 2 },
  { title: 'Календарь', icon: 'event', stage: 3 },
  { title: 'Медкарта', icon: 'medical_information', stage: 3 },
  { title: 'Счета', icon: 'receipt_long', stage: 3 },
  { title: 'Касса', icon: 'point_of_sale', stage: 3 },
  { title: 'Склад', icon: 'inventory_2', stage: 3 },
  { title: 'Товары и услуги', icon: 'sell', stage: 2 },
  { title: 'Сотрудники', icon: 'badge', stage: 2 },
  { title: 'Стационар', icon: 'bed', stage: 6 },
  { title: 'Лаборатория', icon: 'biotech', stage: 6 },
  { title: 'Отчёты', icon: 'bar_chart', stage: 6 },
]
