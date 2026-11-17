<template>
  <!-- На телефоне (QR у клетки) — крупный экран «у клетки»; на компьютере — полная страница. -->
  <CageScreen v-if="compact" :id="id" />
  <HospitalizationPage v-else :id="id" />
</template>

<script setup>
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute } from 'vue-router'
import CageScreen from './CageScreen.vue'
import HospitalizationPage from './HospitalizationPage.vue'

defineProps({ id: { type: String, required: true } })
const $q = useQuasar()
const route = useRoute()
// ?full=1 — открыть полную страницу и на телефоне; ?cage=1 — экран «у клетки» и на компьютере.
const compact = computed(() => (route.query.cage ? true : route.query.full ? false : $q.screen.lt.md))
</script>
