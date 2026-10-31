<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Роли и права</h1>
      <q-btn v-if="can('auth.add_group')" color="primary" icon="add" label="Новая роль" unelevated
        @click="openEditor()" />
    </div>
    <p class="text-grey-8">
      Роль — набор прав для группы сотрудников: врач, регистратор, кассир… Права задаются
      для каждого справочника отдельно или сразу для всего раздела. Сотрудник может состоять
      в нескольких ролях — права складываются.
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

            <div class="text-subtitle2">Права</div>
            <q-markup-table flat bordered dense wrap-cells>
              <thead>
                <tr>
                  <th class="text-left">Раздел и что в нём</th>
                  <th v-for="action in matrix.actions" :key="action.code" class="text-center">
                    {{ action.title }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <template v-for="module in matrix.modules" :key="module.code">
                  <tr class="module-row">
                    <td class="cursor-pointer" @click="toggleExpanded(module.code)">
                      <q-icon :name="expanded[module.code] ? 'expand_more' : 'chevron_right'" size="20px" />
                      <strong>{{ module.title }}</strong>
                      <span class="text-caption text-grey-7 q-ml-xs">· {{ module.entities.length }}</span>
                    </td>
                    <td v-for="action in matrix.actions" :key="action.code" class="text-center">
                      <q-checkbox :model-value="moduleState(module, action.code)" toggle-indeterminate
                        :disable="!canEdit" @update:model-value="() => toggleModule(module, action.code)">
                        <q-tooltip>Для всех справочников раздела</q-tooltip>
                      </q-checkbox>
                    </td>
                  </tr>
                  <template v-if="expanded[module.code]">
                    <template v-for="group in groupsOf(module)" :key="group.key">
                      <tr v-if="group.title" class="group-row">
                        <td class="group-cell">
                          <q-icon :name="group.icon" size="16px" class="q-mr-xs" />{{ group.title }}
                          <span class="text-caption text-grey-7"> · {{ group.entities.length }}</span>
                        </td>
                        <td v-for="action in matrix.actions" :key="action.code" class="text-center">
                          <q-checkbox :model-value="groupState(group.entities, action.code)" toggle-indeterminate size="sm"
                            :disable="!canEdit" @update:model-value="() => toggleGroup(group.entities, action.code)">
                            <q-tooltip>{{ group.tooltip }}</q-tooltip>
                          </q-checkbox>
                        </td>
                      </tr>
                      <tr v-for="entity in group.entities" :key="entity.code">
                        <td class="entity-cell">
                          <div>{{ entity.title }}</div>
                          <div v-if="entity.hint" class="text-caption text-grey-7 entity-hint">{{ entity.hint }}</div>
                        </td>
                        <td v-for="action in matrix.actions" :key="action.code" class="text-center">
                          <q-checkbox :model-value="hasAction(entity.code, action.code)" :disable="!canEdit"
                            @update:model-value="(value) => setAction(entity.code, action.code, value)" />
                        </td>
                      </tr>
                    </template>
                  </template>
                </template>
              </tbody>
            </q-markup-table>
            <div class="text-caption text-grey-7">
              Галочка в строке раздела ставит право сразу на всё в разделе. Внутри раздела — две группы:
              «Работа» (сами данные: клиенты, счета, медкарта…) и «Справочники» (списки для выбора: породы,
              города, единицы…) — у каждой группы своя общая галочка. Под названием строки — что именно
              разрешается. Редактирование и удаление включают просмотр.
            </div>

            <q-select v-model="editing.users" :options="userOptions" option-value="id" option-label="label"
              emit-value map-options multiple use-chips outlined use-input input-debounce="0"
              label="Сотрудники в роли" :readonly="!canEdit" @filter="filterUsers" />
            <div v-if="errors.access" class="text-negative">{{ errors.access }}</div>
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

// Краткое описание роли: разделы, к которым есть доступ (полностью или частично).
function summary(role) {
  const parts = []
  for (const module of matrix.value.modules) {
    const withAccess = module.entities.filter((e) => role.access[e.code]?.length).length
    if (withAccess === module.entities.length) parts.push(module.title)
    else if (withAccess) parts.push(`${module.title} (частично)`)
  }
  return parts.length ? parts.join(', ') : 'Нет прав'
}

const editorOpen = ref(false)
const editing = ref({ name: '', users: [], access: {} })
const expanded = ref({})
const errors = ref({})
const saving = ref(false)
const canEdit = computed(() => can(editing.value.id ? 'auth.change_group' : 'auth.add_group'))

const allEntities = () => matrix.value.modules.flatMap((m) => m.entities.map((e) => e.code))

function openEditor(role = null) {
  errors.value = {}
  const access = Object.fromEntries(allEntities().map((code) => [code, [...(role?.access[code] ?? [])]]))
  editing.value = role ? { ...role, users: [...role.users], access } : { name: '', users: [], access }
  // Разделы с частичными правами раскрыты сразу — чтобы было видно, что именно разрешено.
  expanded.value = Object.fromEntries(
    matrix.value.modules.map((m) => [m.code, matrix.value.actions.some((a) => moduleState(m, a.code) === null)]),
  )
  editorOpen.value = true
}

const toggleExpanded = (code) => (expanded.value[code] = !expanded.value[code])
const hasAction = (entity, action) => editing.value.access[entity]?.includes(action)

// Права зависят друг от друга: изменение и удаление невозможны без просмотра.
function setAction(entity, action, value) {
  const actions = new Set(editing.value.access[entity])
  if (value) {
    actions.add(action)
    if (action !== 'view') actions.add('view')
  } else {
    actions.delete(action)
    if (action === 'view') actions.clear()
  }
  editing.value.access[entity] = [...actions]
}

// Групповая галочка: всё — да, ничего — нет, часть — «частично» (null).
function groupState(entities, action) {
  const count = entities.filter((e) => hasAction(e.code, action)).length
  if (count === entities.length) return true
  return count === 0 ? false : null
}

function toggleGroup(entities, action) {
  const value = groupState(entities, action) !== true
  for (const entity of entities) setAction(entity.code, action, value)
}

const moduleState = (module, action) => groupState(module.entities, action)
const toggleModule = (module, action) => toggleGroup(module.entities, action)

// Внутри раздела: «Работа» (данные) и «Справочники». Если группа одна — без заголовка.
function groupsOf(module) {
  const data = module.entities.filter((e) => !e.is_directory)
  const dirs = module.entities.filter((e) => e.is_directory)
  const both = data.length && dirs.length
  return [
    { key: 'data', title: both ? 'Работа' : '', icon: 'work_outline', tooltip: 'Все рабочие данные раздела', entities: data },
    { key: 'dirs', title: both || dirs.length ? 'Справочники' : '', icon: 'list_alt', tooltip: 'Все справочники раздела', entities: dirs },
  ].filter((g) => g.entities.length)
}

function filterUsers(text, update) {
  update(() => {
    const needle = text.toLowerCase()
    userOptions.value = users.value.filter((u) => u.label.toLowerCase().includes(needle))
  })
}

async function save() {
  saving.value = true
  const body = { name: editing.value.name, access: editing.value.access }
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

<style scoped>
.module-row {
  background: rgba(127, 127, 127, 0.06);
}
.entity-cell {
  padding-left: 52px !important;
}
.entity-hint {
  line-height: 1.25;
  white-space: normal;
}
.group-row {
  background: rgba(127, 127, 127, 0.03);
}
.group-cell {
  padding-left: 32px !important;
  font-weight: 500;
  font-size: 13px;
}
</style>
