<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="col">
        <div class="text-subtitle1">Счета</div>
        <div v-if="balance !== null" class="text-caption" :class="balance < 0 ? 'text-negative text-weight-medium' : 'text-grey-7'">
          Баланс: {{ money(balance) }}{{ balance < 0 ? ' — долг' : balance > 0 ? ' — аванс' : '' }}
        </div>
      </div>
      <q-btn v-if="can('billing.add_invoice')" flat dense color="primary" icon="add" label="Новый счёт"
        :to="{ path: '/invoices/new', query: { client: client.id, client_name: client.full_name } }" />
    </q-card-section>
    <q-list separator dense>
      <q-item v-for="i in invoices" :key="i.id" clickable :to="`/invoices/${i.id}`">
        <q-item-section side class="text-weight-medium">{{ new Date(i.date).toLocaleDateString('ru-RU') }}</q-item-section>
        <q-item-section>№ {{ i.number }}{{ i.pet_name ? ` · ${i.pet_name}` : '' }}</q-item-section>
        <q-item-section side>{{ money(i.total) }}</q-item-section>
        <q-item-section side><q-badge :color="i.status === 'executed' ? 'positive' : 'grey-6'" :label="i.status_label" /></q-item-section>
      </q-item>
      <q-item v-if="!invoices.length"><q-item-section class="text-grey-7">Счетов пока нет</q-item-section></q-item>
    </q-list>
  </q-card>
</template>

<script setup>
// Счета и баланс клиента — блок модуля «Счета» в карточке клиента.
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'

const props = defineProps({ client: { type: Object, required: true } })
const invoices = ref([])
const balance = ref(null)

onMounted(async () => {
  const { data } = await apiGet(`billing/invoices/?client=${props.client.id}&page_size=20`)
  invoices.value = data?.results ?? []
  balance.value = invoices.value.length ? Number(invoices.value[0].client_balance) : 0
})
</script>
