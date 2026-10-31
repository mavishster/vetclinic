<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="col">
        <div class="text-subtitle1">Счета</div>
        <div v-if="balance !== null" class="text-caption" :class="balance < 0 ? 'text-negative text-weight-medium' : 'text-grey-7'">
          Баланс: {{ money(balance) }}{{ balance < 0 ? ' — долг' : balance > 0 ? ' — аванс' : '' }}
        </div>
      </div>
      <q-btn v-if="can('cash.add_payment') && balance < 0" flat dense color="positive" icon="payments" label="Оплатить долг" @click="payOpen = true" />
      <q-btn v-if="can('cash.add_payment')" flat dense color="primary" icon="savings" label="Аванс" @click="advanceOpen = true" />
      <q-btn v-if="can('cash.add_cashoperation') && balance > 0" flat dense color="warning" icon="undo" label="Вернуть аванс" @click="returnOpen = true" />
      <q-btn v-if="can('billing.add_invoice')" flat dense color="primary" icon="add" label="Новый счёт"
        :to="{ path: '/invoices/new', query: { client: client.id, client_name: client.full_name } }" />
    </q-card-section>
    <q-list separator dense>
      <q-item v-for="i in invoices" :key="i.id" clickable :to="`/invoices/${i.id}`">
        <q-item-section side class="text-weight-medium">{{ new Date(i.date).toLocaleDateString('ru-RU') }}</q-item-section>
        <q-item-section>№ {{ i.number }}{{ i.pet_name ? ` · ${i.pet_name}` : '' }}</q-item-section>
        <q-item-section side>{{ money(i.total) }}</q-item-section>
        <q-item-section side><q-badge :color="PAY[i.payment_status].color" :label="PAY[i.payment_status].label" /></q-item-section>
      </q-item>
      <q-item v-if="!invoices.length"><q-item-section class="text-grey-7">Счетов пока нет</q-item-section></q-item>
    </q-list>
    <PaymentDialog v-model="payOpen" :client-id="client.id" :client-name="client.full_name" @paid="load" />
    <PaymentDialog v-model="advanceOpen" advance-only :client-id="client.id" :client-name="client.full_name" @paid="load" />
    <AdvanceReturnDialog v-model="returnOpen" :client-id="client.id" :client-name="client.full_name" @done="load" />
  </q-card>
</template>

<script setup>
// Счета и баланс клиента — блок модуля «Счета» в карточке клиента.
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
// Оплата и аванс — модуль «Касса».
import AdvanceReturnDialog from '@/modules/cash/AdvanceReturnDialog.vue'
import PaymentDialog from '@/modules/cash/PaymentDialog.vue'

const props = defineProps({ client: { type: Object, required: true } })
const invoices = ref([])
const balance = ref(null)
const payOpen = ref(false)
const advanceOpen = ref(false)
const returnOpen = ref(false)
const PAY = {
  paid: { label: 'оплачен', color: 'positive' },
  partial: { label: 'частично', color: 'warning' },
  debt: { label: 'долг', color: 'negative' },
  draft: { label: 'черновик', color: 'grey-6' },
}

async function load() {
  const [list, credit] = await Promise.all([
    apiGet(`billing/invoices/?client=${props.client.id}&page_size=20`),
    apiGet(`billing/invoices/credit/?client=${props.client.id}`),
  ])
  invoices.value = list.data?.results ?? []
  balance.value = Number(credit.data?.balance ?? 0)
}

onMounted(load)
</script>
