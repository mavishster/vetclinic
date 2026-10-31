<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 420px; max-width: 95vw">
      <q-form @submit="submit">
        <q-card-section class="text-h6">Возврат аванса</q-card-section>
        <q-card-section class="q-pt-none q-gutter-y-sm">
          <div class="text-subtitle2">{{ clientName }} · аванс {{ money(Math.max(Number(balance), 0)) }}</div>
          <q-input v-model="amount" type="number" step="0.01" min="0" outlined dense autofocus label="Сумма к возврату"
            hint="Можно вернуть часть аванса" />
          <q-select v-model="register" :options="registers" option-value="id" option-label="name" emit-value map-options
            outlined dense label="Из кассы наличных" />
          <q-input v-model="pin" type="password" inputmode="numeric" maxlength="6" outlined dense label="Ваш ПИН-код"
            hint="Возврат денег подтверждается ПИН-кодом" />
          <div v-if="error" class="text-negative">{{ error }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn type="submit" color="warning" unelevated label="Вернуть" :loading="busy" :disable="!amount || !pin" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Возврат аванса клиенту наличными — с подтверждением ПИН-кодом.
import { ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { money } from '@/modules/catalog/money'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  clientId: { type: String, default: null },
  clientName: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'done'])
const $q = useQuasar()
const amount = ref('')
const pin = ref('')
const register = ref(null)
const registers = ref([])
const balance = ref(0)
const error = ref('')
const busy = ref(false)

watch(() => props.modelValue, async (open) => {
  if (!open) return
  error.value = ''
  pin.value = ''
  const [regs, credit] = await Promise.all([apiGet('cash/registers/?active=true'), apiGet(`billing/invoices/credit/?client=${props.clientId}`)])
  registers.value = (regs.data ?? []).filter((r) => r.kind === 'cash')
  register.value = registers.value[0]?.id ?? null
  balance.value = credit.data?.balance ?? 0
  amount.value = String(Math.max(Number(balance.value), 0) || '')
}, { immediate: true }) // окно может быть открыто сразу при появлении (оплата нового счёта)

async function submit() {
  error.value = ''
  busy.value = true
  const { ok, data } = await apiPost('cash/operations/', {
    kind: 'advance_return', register: register.value, client: props.clientId, amount: amount.value, pin: pin.value,
  })
  busy.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось вернуть аванс')
  $q.notify({ type: 'positive', message: `Возвращено ${money(data.amount)}` })
  emit('update:modelValue', false)
  emit('done')
}
</script>
