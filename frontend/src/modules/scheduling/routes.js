import DirectoryPage from '@/components/DirectoryPage.vue'

const KINDS = [
  { id: 'general', name: 'Приём' },
  { id: 'vaccination', name: 'Вакцинация' },
  { id: 'analysis', name: 'Взятие анализа' },
  { id: 'call', name: 'Звонок' },
  { id: 'task', name: 'Задача' },
]

export default [
  { path: 'calendar', component: () => import('./CalendarPage.vue'), meta: { perm: 'scheduling.view_appointment' } },
  { path: 'appointments/today', component: () => import('./TodayPage.vue'), meta: { perm: 'scheduling.view_appointment' } },
  {
    path: 'directories/visit-purposes',
    component: DirectoryPage,
    props: {
      title: 'Цели обращения',
      endpoint: 'scheduling/purposes/',
      permission: 'scheduling.visitpurpose',
      fields: [
        { name: 'kind', label: 'Вид', type: 'choice', options: KINDS },
        { name: 'duration_minutes', label: 'Длительность, мин', type: 'number' },
        { name: 'color', label: 'Цвет', type: 'color' },
        { name: 'show_in_portal', label: 'В личном кабинете клиента', type: 'checkbox' },
      ],
    },
    meta: { perm: 'scheduling.view_visitpurpose' },
  },
]
