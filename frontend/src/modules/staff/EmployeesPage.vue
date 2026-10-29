<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Сотрудники</h1>
      <q-checkbox v-model="showInactive" label="Показать уволенных" dense @update:model-value="load" />
      <q-btn v-if="can('staff.add_employee')" color="primary" unelevated icon="person_add" label="Новый сотрудник"
        @click="open()" />
    </div>

    <q-table :rows="rows" :columns="columns" row-key="id" flat bordered :loading="loading"
      :pagination="{ rowsPerPage: 50 }" no-data-label="Сотрудников нет" rows-per-page-label="Строк на странице"
      @row-click="(e, row) => open(row)">
      <template #body-cell-full_name="props">
        <q-td :props="props" :class="{ 'text-grey-6': !props.row.is_active }">
          <q-icon name="circle" :style="{ color: props.row.color }" size="12px" class="q-mr-sm" />
          <span class="text-weight-medium">{{ props.row.full_name || props.row.username }}</span>
          <q-badge v-if="!props.row.is_active" color="grey-6" label="уволен" class="q-ml-sm" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="editorOpen" :maximized="$q.screen.lt.sm">
      <q-card style="width: 640px; max-width: 96vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ form.id ? form.full_name : 'Новый сотрудник' }}</q-card-section>
          <q-card-section class="q-pt-none">
            <div class="row q-col-gutter-sm">
              <q-input v-model="form.last_name" label="Фамилия *" outlined dense autofocus class="col-12 col-sm-4" />
              <q-input v-model="form.first_name" label="Имя" outlined dense class="col-6 col-sm-4" />
              <q-input v-model="form.middle_name" label="Отчество" outlined dense class="col-6 col-sm-4" />
              <q-select v-model="form.position" :options="positions" option-value="id" option-label="name" emit-value
                map-options outlined dense clearable label="Должность" class="col-12 col-sm-6" />
              <q-input v-model="form.phone" label="Телефон" outlined dense class="col-12 col-sm-6" />
              <q-input v-model="form.email" label="Email" type="email" outlined dense class="col-12 col-sm-6" />
              <q-input v-model="form.color" label="Цвет в графике" type="color" outlined dense stack-label class="col-6 col-sm-3" />
              <div class="col-6 col-sm-3 flex items-center">
                <q-checkbox v-model="form.in_schedule" label="В графике" dense />
              </div>
            </div>
            <div class="text-subtitle2 text-grey-8 q-mt-md">Вход в систему</div>
            <div class="row q-col-gutter-sm">
              <q-input v-model="form.username" label="Логин *" outlined dense autocomplete="off" class="col-12 col-sm-6" />
              <q-input v-model="form.password" :label="form.id ? 'Новый пароль (если меняете)' : 'Пароль *'"
                type="password" outlined dense autocomplete="new-password" class="col-12 col-sm-6"
                hint="Не короче 8 символов, не только цифры" />
            </div>
            <q-select v-if="canManageRoles" v-model="form.roles" :options="roles" option-value="id" option-label="name"
              emit-value map-options multiple use-chips outlined dense label="Роли" class="q-mt-sm" />
            <div v-else-if="form.id" class="text-caption text-grey-7 q-mt-sm">
              Роли назначает тот, у кого есть право «Роли и права».
            </div>
            <q-checkbox v-if="form.id" v-model="form.is_active" label="Работает (снимите галочку при увольнении)"
              dense class="q-mt-sm" />
            <div v-for="error in errors" :key="error" class="text-negative q-mt-sm">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn v-if="canSave" type="submit" color="primary" unelevated label="Сохранить" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const $q = useQuasar()
const rows = ref([])
const loading = ref(false)
const showInactive = ref(false)
const positions = ref([])
const roles = ref([])
const editorOpen = ref(false)
const form = ref({})
const errors = ref([])
const saving = ref(false)
const canManageRoles = can('auth.change_group')
const canSave = computed(() => can(form.value.id ? 'staff.change_employee' : 'staff.add_employee'))

const roleNames = (row) => row.roles.map((id) => roles.value.find((r) => r.id === id)?.name).filter(Boolean).join(', ')
const columns = [
  { name: 'full_name', label: 'Сотрудник', field: 'full_name', align: 'left' },
  { name: 'position', label: 'Должность', field: 'position_name', align: 'left' },
  { name: 'phone', label: 'Телефон', field: 'phone', align: 'left' },
  { name: 'username', label: 'Логин', field: 'username', align: 'left' },
  { name: 'roles', label: 'Роли', field: roleNames, align: 'left' },
]

async function load() {
  loading.value = true
  const { ok, data } = await apiGet(`staff/employees/${showInactive.value ? '' : '?active=true'}`)
  rows.value = ok ? data : []
  loading.value = false
}

function open(row = null) {
  errors.value = []
  form.value = row
    ? { ...row, password: '', roles: [...row.roles] }
    : { last_name: '', first_name: '', middle_name: '', username: '', password: '', email: '', phone: '',
        position: null, color: '#24566a', in_schedule: true, roles: [], is_active: true }
  editorOpen.value = true
}

async function save() {
  errors.value = []
  const body = { ...form.value }
  if (!body.password) delete body.password
  if (!canManageRoles) delete body.roles
  for (const key of ['id', 'user_id', 'full_name', 'position_name']) delete body[key]
  saving.value = true
  const { ok, data } = form.value.id
    ? await apiPatch(`staff/employees/${form.value.id}/`, body)
    : await apiPost('staff/employees/', body)
  saving.value = false
  if (!ok) {
    errors.value = Object.values(fieldErrors(data))
    return
  }
  editorOpen.value = false
  $q.notify({ type: 'positive', message: 'Сотрудник сохранён' })
  load()
}

onMounted(async () => {
  const [p, r] = await Promise.all([
    apiGet('staff/positions/?active=true'),
    can('auth.view_group') ? apiGet('core/roles/') : Promise.resolve({ data: [] }),
  ])
  positions.value = p.data ?? []
  roles.value = r.data ?? []
  load()
})
</script>
