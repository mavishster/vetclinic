<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Роли и права</h1>
      <q-btn v-if="can('auth.add_group')" color="primary" icon="add" label="Новая роль" unelevated
        @click="openEditor()" />
    </div>
    <p class="text-grey-8">
      Роль — набор прав для группы сотрудников: врач, регистратор, кассир… Права назначаются
      на раздел целиком. Сотрудник может состоять в нескольких ролях — права складываются.
    </p>

    <q-list bordered separator class="rounded-borders">
      <q-item v-for="role in roles" :key="role.id" clickable @click="openEditor(role)">
        <q-item-section avatar><q-icon name="group" color="primary" /></q-item-section>
        <q-item-section>
          <q-item-label>{{ role.name }}</q-item-label>
          <q-item-label caption>{{ summary(role) }}</q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-badge color="grey-6" :label="`${role.users.length} сотр.`" />
        </q-item-section>
      </q-item>
      <q-item v-if="!roles.length && !loading">
        <q-item-section class="text-grey-7">Ролей пока нет — создайте первую.</q-item-section>
      </q-item>
    </q-list>

    <q-dialog v-model="editorOpen" :maximized="$q.screen.xs">
      <q-card style="width: 760px; max-width: 95vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ editing.id ? 'Роль' : 'Новая роль' }}</q-card-section>

          <q-card-section class="q-gutter-md">
            <q-input v-model="editing.name" label="Название роли" outlined autofocus :readonly="!canEdit"
              :error="!!errors.name" :error-message="errors.name" />

            <div class="text-subtitle2">Права по разделам</div>
            <q-markup-table flat bordered dense wrap-cells>
              <thead>
                <tr>
                  <th class="text-left">Раздел</th>
                  <th v-for="action in matrix.actions" :key="action.code" class="text-center">
                    {{ action.title }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="module in matrix.modules" :key="module.code">
                  <td>{{ module.title }}</td>
                  <td v-for="action in matrix.actions" :key="action.code" class="text-center">
                    <q-checkbox :model-value="hasAction(module.code, action.code)" :disable="!canEdit"
                      @update:model-value="(value) => setAction(module.code, action.code, value)" />
                  </td>
                </tr>
              </tbody>
            </q-markup-table>
            <div class="text-caption text-grey-7">
              Редактирование и удаление включают просмотр: без него нельзя изменить то, чего не видишь.
            </div>

            <q-select v-model="editing.users" :options="userOptions" option-value="id" option-label="label"
              emit-value map-options multiple use-chips outlined use-input input-debounce="0"
              label="Сотрудники в роли" :readonly="!canEdit" @filter="filterUsers" />
            <div v-if="errors.modules" class="text-negative">{{ errors.modules }}</div>
          </q-card-section>

          <q-card-actions align="right">
            <q-btn v-if="editing.id && can('auth.delete_group')" flat color="negative" label="Удалить роль"
              class="q-mr-auto" @click="remove" />
            <q-btn flat label="Закрыть" v-close-popup />
            <q-btn v-if="canEdit" type="submit" color="primary" label="Сохранить" unelevated :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const $q = useQuasar()
const roles = ref([])
const loading = ref(false)
const matrix = ref({ modules: [], actions: [] })
const users = ref([])
const userOptions = ref([])

async function load() {
  loading.value = true
  const [rolesResult, matrixResult, usersResult] = await Promise.all([
    apiGet('core/roles/'),
    apiGet('core/roles/matrix/'),
    can('core.view_user') ? apiGet('core/users/') : Promise.resolve({ ok: true, data: [] }),
  ])
  roles.value = rolesResult.ok ? rolesResult.data : []
  if (matrixResult.ok) matrix.value = matrixResult.data
  users.value = (usersResult.data ?? []).map((u) => ({ id: u.id, label: u.full_name || u.username }))
  userOptions.value = users.value
  loading.value = false
}

const titleOf = (code) => matrix.value.modules.find((m) => m.code === code)?.title ?? code
function summary(role) {
  const granted = Object.entries(role.modules).filter(([, actions]) => actions.length)
  return granted.length ? granted.map(([code]) => titleOf(code)).join(', ') : 'Нет прав'
}

const editorOpen = ref(false)
const editing = ref({ name: '', users: [], modules: {} })
const errors = ref({})
const saving = ref(false)
const canEdit = computed(() => can(editing.value.id ? 'auth.change_group' : 'auth.add_group'))

function openEditor(role = null) {
  errors.value = {}
  const modules = Object.fromEntries(matrix.value.modules.map((m) => [m.code, [...(role?.modules[m.code] ?? [])]]))
  editing.value = role ? { ...role, users: [...role.users], modules } : { name: '', users: [], modules }
  editorOpen.value = true
}

const hasAction = (module, action) => editing.value.modules[module]?.includes(action)

// Права зависят друг от друга: изменение и удаление невозможны без просмотра.
function setAction(module, action, value) {
  const actions = new Set(editing.value.modules[module])
  if (value) {
    actions.add(action)
    if (action !== 'view') actions.add('view')
  } else {
    actions.delete(action)
    if (action === 'view') actions.clear()
  }
  editing.value.modules[module] = [...actions]
}

function filterUsers(text, update) {
  update(() => {
    const needle = text.toLowerCase()
    userOptions.value = users.value.filter((u) => u.label.toLowerCase().includes(needle))
  })
}

async function save() {
  saving.value = true
  const body = { name: editing.value.name, modules: editing.value.modules }
  if (can('core.view_user')) body.users = editing.value.users
  const { ok, data } = editing.value.id
    ? await apiPatch(`core/roles/${editing.value.id}/`, body)
    : await apiPost('core/roles/', body)
  saving.value = false
  if (!ok) {
    errors.value = fieldErrors(data)
    return
  }
  editorOpen.value = false
  $q.notify({ type: 'positive', message: 'Роль сохранена' })
  load()
}

function remove() {
  $q.dialog({
    title: 'Удалить роль?',
    message: `Сотрудники роли «${editing.value.name}» потеряют её права.`,
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
    persistent: true,
  }).onOk(async () => {
    const { ok } = await apiDelete(`core/roles/${editing.value.id}/`)
    editorOpen.value = false
    if (ok) load()
    else $q.notify({ type: 'negative', message: 'Не удалось удалить роль' })
  })
}

onMounted(load)
</script>
