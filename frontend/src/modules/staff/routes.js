import DirectoryPage from '@/components/DirectoryPage.vue'

export default [
  { path: 'staff/employees', component: () => import('./EmployeesPage.vue'), meta: { perm: 'staff.view_employee' } },
  { path: 'staff/schedule', component: () => import('./SchedulePage.vue'), meta: { perm: 'staff.view_workinterval' } },
  {
    path: 'directories/positions',
    component: DirectoryPage,
    props: { title: 'Должности', endpoint: 'staff/positions/', permission: 'staff.position' },
    meta: { perm: 'staff.view_position' },
  },
  {
    path: 'directories/interval-types',
    component: DirectoryPage,
    props: {
      title: 'Типы интервалов графика',
      endpoint: 'staff/interval-types/',
      permission: 'staff.intervaltype',
      fields: [
        { name: 'is_working', label: 'Рабочее время', type: 'checkbox' },
        { name: 'color', label: 'Цвет', type: 'color' },
      ],
    },
    meta: { perm: 'staff.view_intervaltype' },
  },
  {
    path: 'directories/interval-templates',
    component: DirectoryPage,
    props: {
      title: 'Шаблоны времени',
      endpoint: 'staff/templates/',
      permission: 'staff.intervaltemplate',
      fields: [
        { name: 'start_time', label: 'Начало', type: 'time' },
        { name: 'end_time', label: 'Конец', type: 'time', hint: 'Раньше начала — значит, на следующий день' },
        { name: 'interval_type', label: 'Тип', endpoint: 'staff/interval-types/' },
      ],
    },
    meta: { perm: 'staff.view_intervaltemplate' },
  },
]
