<template>
  <q-page padding class="home">
    <h1 class="text-h5 q-mt-none q-mb-md">Здравствуйте, {{ firstName }}!</h1>
    <q-banner v-if="backup" rounded class="q-mb-md" :class="backup.ok ? 'row-highlight-positive' : 'row-highlight-negative'">
      <template #avatar><q-icon :name="backup.ok ? 'cloud_done' : 'warning'" :color="backup.ok ? 'positive' : 'negative'" /></template>
      <div class="text-weight-medium">Резервные копии{{ backup.ok ? ' в порядке' : ' — нужно внимание' }}</div>
      <div v-if="backup.backup?.ok" class="text-caption">
        Последняя копия: {{ fmt(backup.backup.at) }}<template v-if="backup.restore_check?.ok"> · восстановление проверено {{ fmt(backup.restore_check.at) }}
        ({{ backup.restore_check.clients }} клиентов, {{ backup.restore_check.visits }} записей медкарты)</template>
      </div>
      <div v-for="p in backup.problems" :key="p" class="text-caption text-negative">{{ p }}</div>
    </q-banner>

    <q-card v-if="unassignedLab" flat bordered class="q-mb-md cursor-pointer" @click="$router.push('/laboratory')">
      <q-card-section class="row items-center no-wrap">
        <q-icon name="biotech" color="warning" size="36px" class="q-mr-md" />
        <div><div class="text-h5">{{ unassignedLab }}</div><div class="text-caption text-grey-7">анализов без медкарты — привяжите в «Лаборатории»</div></div>
      </q-card-section>
    </q-card>
    <q-card v-if="toCall" flat bordered class="q-mb-md cursor-pointer" @click="$router.push('/reminders')">
      <q-card-section class="row items-center no-wrap">
        <q-icon name="notifications_active" color="primary" size="36px" class="q-mr-md" />
        <div><div class="text-h5">{{ toCall }}</div><div class="text-caption text-grey-7">к обзвону — напоминания клиентам</div></div>
      </q-card-section>
    </q-card>
    <q-card v-if="departmentAlerts.length" flat bordered class="q-mb-md">
      <q-card-section class="q-pb-xs text-subtitle1"><q-icon name="domain" color="warning" class="q-mr-sm" />Отделения</q-card-section>
      <q-list dense>
        <q-item v-for="a in departmentAlerts" :key="a.department + a.kind" clickable
          @click="$router.push({ path: '/inventory/departments', query: { department: a.department } })">
          <q-item-section avatar><q-icon :name="a.level === 'negative' ? 'error' : 'warning'" :color="a.level === 'negative' ? 'negative' : 'warning'" /></q-item-section>
          <q-item-section><b>{{ a.department_name }}</b> {{ a.message }}</q-item-section>
        </q-item>
      </q-list>
    </q-card>
    <div v-if="stock" class="row q-col-gutter-md q-mb-lg">
      <div v-for="card in stockCards" :key="card.title" class="col-12 col-sm-6 col-md-3">
        <q-card flat bordered class="cursor-pointer" @click="$router.push(card.to)">
          <q-card-section class="row items-center no-wrap">
            <q-icon :name="card.icon" :color="card.count ? card.color : 'grey-5'" size="36px" class="q-mr-md" />
            <div>
              <div class="text-h5">{{ card.count }}</div>
              <div class="text-caption text-grey-7">{{ card.title }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <q-banner rounded :class="bannerClass">
      <template #avatar>
        <q-spinner v-if="state === 'loading'" size="24px" />
        <q-icon v-else :name="state === 'ok' ? 'check_circle' : 'error'" size="24px" />
      </template>
      {{ message }}
    </q-banner>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can, session } from '@/session'

const state = ref('loading') // loading | ok | error
const stock = ref(null)
const toCall = ref(0)
const unassignedLab = ref(0)
const departmentAlerts = ref([])
const backup = ref(null)
const fmt = (stamp) => new Date(stamp.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })

// Склад требует внимания: просрочка, сроки на исходе, ниже минимума.
const stockCards = computed(() => [
  { title: 'партий с истёкшим сроком', count: stock.value.expired, icon: 'dangerous', color: 'negative', to: '/inventory/stock?expiring=1' },
  { title: 'партий истекает за 90 дней', count: stock.value.expiring, icon: 'schedule', color: 'warning', to: '/inventory/stock?expiring=1' },
  { title: 'товаров ниже минимума', count: stock.value.low, icon: 'production_quantity_limits', color: 'primary', to: '/inventory/stock?tab=low' },
  { title: 'товаров в минусе — нужен приход', count: stock.value.negative, icon: 'remove_circle', color: 'negative', to: '/inventory/stock?tab=negative' },
  { title: 'нужно переместить на оперативный', count: stock.value.replenish, icon: 'move_down', color: 'warning', to: '/inventory/stock?tab=replenish' },
])
const firstName = computed(() => session.user?.full_name.split(' ')[1] || session.user?.username)

const message = computed(
  () =>
    ({
      loading: 'Проверяю связь с сервером…',
      ok: 'Сервер и база данных работают.',
      error: 'Нет связи с сервером или базой данных. Проверьте, что запущены все контейнеры: make up',
    })[state.value],
)

const bannerClass = computed(
  () =>
    ({
      loading: 'bg-grey-3 text-dark',
      ok: 'bg-positive text-white',
      error: 'bg-negative text-white',
    })[state.value],
)

onMounted(async () => {
  // Резервные копии видят те, кто настраивает систему.
  if (can('auth.change_group')) {
    apiGet('core/backup-status/').then(({ ok, data }) => { if (ok && data.configured) backup.value = data })
  }
  if (can('laboratory.view_labresult')) {
    apiGet('laboratory/results/unassigned-count/').then(({ ok, data }) => { if (ok) unassignedLab.value = data.count })
  }
  if (can('reminders.view_reminder')) {
    apiGet('reminders/reminders/count/').then(({ ok, data }) => { if (ok) toCall.value = data.to_call })
  }
  // Отделения: видят главный администратор (все) и ответственные (свои) — сервер решает сам.
  apiGet('inventory/department-stock/alerts/').then(({ ok, data }) => { if (ok) departmentAlerts.value = data })
  if (can('inventory.view_stockmovement')) {
    apiGet('inventory/stock/summary/').then(({ ok, data }) => { if (ok) stock.value = data })
  }
  const { ok, data } = await apiGet('core/health/')
  state.value = ok && data?.database ? 'ok' : 'error'
})
</script>

<style scoped>
.home {
  max-width: 720px;
}

</style>
