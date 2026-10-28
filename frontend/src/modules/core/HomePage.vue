<template>
  <q-page padding class="home">
    <h1 class="text-h5 q-mt-none q-mb-md">Система управления клиникой</h1>
    <p class="text-body1 q-mb-lg">
      Каркас проекта запущен. Модули появляются в меню по мере готовности.
    </p>

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

const state = ref('loading') // loading | ok | error

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
  const { ok, data } = await apiGet('core/health/')
  state.value = ok && data?.database ? 'ok' : 'error'
})
</script>

<style scoped>
.home {
  max-width: 720px;
}
</style>
