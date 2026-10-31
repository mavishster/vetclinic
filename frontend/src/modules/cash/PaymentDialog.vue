<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 560px; max-width: 96vw">
      <q-card-section class="row items-center">
        <div class="text-h6 col">{{ advanceOnly ? 'Внесение аванса' : 'Оплата' }}</div>
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section class="q-pt-none">
        <div class="text-subtitle2">{{ clientName }}</div>
        <div v-if="!guest" class="text-caption" :class="Number(money_.balance) < 0 ? 'text-negative' : 'text-grey-7'">
          Баланс: {{ money(money_.balance) }}{{ Number(money_.credit) > 0 ? ` · аванс к зачёту ${money(money_.credit)}` : '' }}
        </div>
      </q-card-section>

      <q-card-section v-if="!advanceOnly" class="q-pt-none">
        <div class="text-subtitle2 q-mb-xs">Что оплачиваем</div>
        <q-list bordered separator dense class="rounded-borders">
          <q-item v-for="inv in invoices" :key="inv.id" tag="label">
            <q-item-section side><q-checkbox v-model="selected" :val="inv.id" dense /></q-item-section>
            <q-item-section>№ {{ inv.number }} от {{ new Date(inv.date).toLocaleDateString('ru-RU') }}</q-item-section>
            <q-item-section side>{{ money(inv.unpaid) }}</q-item-section>
          </q-item>
          <q-item v-if="!invoices.length"><q-item-section class="text-grey-7">Неоплаченных счетов нет</q-item-section></q-item>
        </q-list>
        <div class="row q-mt-sm text-subtitle1">
          <div class="col">К оплате{{ Number(money_.credit) > 0 ? ' (за вычетом аванса)' : '' }}:</div>
          <b>{{ money(due) }}</b>
        </div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <q-btn-toggle v-model="method" no-caps unelevated spread toggle-color="primary" class="q-mb-sm"
          :options="[{ label: 'Наличные', value: 'cash' }, { label: 'Карта', value: 'card' }, { label: 'Смешанная', value: 'mixed' }]" />
        <div class="row q-col-gutter-sm">
          <template v-if="method !== 'card'">
            <q-input v-model="cashReceived" type="number" step="0.01" min="0" outlined dense autofocus label="Получено наличными"
              class="col-6" />
            <q-select v-model="cashRegister" :options="registers.filter((r) => r.kind === 'cash')" option-value="id"
              option-label="name" emit-value map-options outlined dense label="Касса" class="col-6" />
          </template>
          <template v-if="method !== 'cash'">
            <q-input v-model="cardAmount" type="number" step="0.01" min="0" outlined dense label="Безналом" class="col-6" />
            <q-select v-model="cardRegister" :options="registers.filter((r) => r.kind === 'cashless')" option-value="id"
              option-label="name" emit-value map-options outlined dense label="Терминал" class="col-6" />
          </template>
        </div>
        <div v-if="!advanceOnly" class="q-mt-sm">
          <div v-if="change > 0" class="row items-center">
            <div class="text-h6 col">Сдача: {{ money(change) }}</div>
            <q-checkbox v-if="!guest" v-model="changeToBalance" label="Оставить на балансе (аванс)" dense />
          </div>
          <div v-else-if="short > 0" :class="guest ? 'text-negative' : 'text-warning'">
            Не хватает {{ money(short) }}{{ guest ? ' — быстрый счёт оплачивается полностью' : ' — останется долгом' }}.
          </div>
        </div>
        <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn flat label="Отмена" v-close-popup />
        <q-btn color="positive" unelevated icon="payments" :label="advanceOnly ? 'Внести' : 'Принять оплату'"
          :loading="busy" :disable="paidNow <= 0" @click="pay" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Окно оплаты: счета клиента галочками, наличные (со сдачей), карта или смешанная.
// Сдачу можно оставить на балансе — она станет авансом. Аванс зачитывается сам.
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { money } from '@/modules/catalog/money'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  clientId: { type: String, default: null },
  clientName: { type: String, default: '' },
  invoiceIds: { type: Array, default: () => [] }, // отмеченные заранее (из счёта)
  advanceOnly: { type: Boolean, default: false }, // внесение аванса без счетов
  guest: { type: Boolean, default: false }, // быстрый счёт: без долга и без аванса
})
const emit = defineEmits(['update:modelValue', 'paid'])
const $q = useQuasar()
const invoices = ref([])
const selected = ref([])
const registers = ref([])
const money_ = ref({ balance: 0, credit: 0 })
const method = ref('cash')
const cashReceived = ref('')
const cardAmount = ref('')
const cashRegister = ref(null)
const cardRegister = ref(null)
const changeToBalance = ref(false)
const error = ref('')
const busy = ref(false)
const n = (v) => Number(v) || 0

const due = computed(() => {
  const sum = invoices.value.filter((i) => selected.value.includes(i.id)).reduce((s, i) => s + n(i.unpaid), 0)
  return Math.max(sum - n(money_.value.credit), 0)
})
const cashPart = computed(() => (method.value === 'card' ? 0 : n(cashReceived.value)))
const cardPart = computed(() => (method.value === 'cash' ? 0 : n(cardAmount.value)))
const paidNow = computed(() => cashPart.value + cardPart.value)
const change = computed(() => Math.max(paidNow.value - due.value, 0))
const short = computed(() => Math.max(due.value - paidNow.value, 0))

watch(() => props.modelValue, async (open) => {
  if (!open) return
  error.value = ''
  changeToBalance.value = false
  const [regs, credit, unpaid] = await Promise.all([
    apiGet('cash/registers/?active=true'),
    apiGet(`billing/invoices/credit/?client=${props.clientId}`),
    props.advanceOnly ? Promise.resolve({ data: { results: [] } }) : apiGet(`billing/invoices/?client=${props.clientId}&unpaid=1&page_size=100`),
  ])
  registers.value = regs.data ?? []
  money_.value = credit.data ?? { balance: 0, credit: 0 }
  invoices.value = unpaid.data?.results ?? []
  // «Гость» общий для всех быстрых счетов — показываем только этот счёт.
  if (props.guest) invoices.value = invoices.value.filter((i) => props.invoiceIds.includes(i.id))
  selected.value = props.invoiceIds.length ? [...props.invoiceIds] : invoices.value.map((i) => i.id)
  cashRegister.value = registers.value.find((r) => r.kind === 'cash')?.id ?? null
  cardRegister.value = registers.value.find((r) => r.kind === 'cashless')?.id ?? null
  method.value = 'cash'
  cashReceived.value = props.advanceOnly ? '' : String(due.value)
  cardAmount.value = ''
}, { immediate: true }) // окно может быть открыто сразу при появлении (оплата нового счёта)

// Сменили способ оплаты — подставляем сумму к оплате туда, куда удобно.
watch(method, (value) => {
  if (props.advanceOnly) return
  if (value === 'card') cardAmount.value = String(due.value)
  if (value === 'cash') cashReceived.value = String(due.value)
  if (value === 'mixed') { cardAmount.value = ''; cashReceived.value = '' }
})

async function pay() {
  error.value = ''
  busy.value = true
  const { ok, data } = await apiPost('cash/payments/pay/', {
    client: props.clientId,
    invoice_ids: props.advanceOnly ? [] : selected.value,
    cash_register: cashPart.value ? cashRegister.value : null,
    card_register: cardPart.value ? cardRegister.value : null,
    cash_received: cashPart.value, card_amount: cardPart.value,
    change_to_balance: changeToBalance.value,
  })
  busy.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось принять оплату')
  $q.notify({ type: 'positive', message: Number(data.change_given) ? `Оплата принята. Сдача: ${money(data.change_given)}` : 'Оплата принята', timeout: 6000 })
  emit('update:modelValue', false)
  emit('paid', data)
}
</script>
