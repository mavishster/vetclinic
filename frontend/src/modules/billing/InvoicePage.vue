<template>
  <q-page padding>
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner size="40px" color="primary" /></div>
    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" @click="$router.back()" />
        <h1 class="text-h5 q-my-none">Счёт{{ form.number ? ` № ${form.number}` : '' }}</h1>
        <q-badge v-if="form.id" :color="executed ? 'positive' : 'grey-6'" :label="executed ? 'выполнен' : 'черновик'" />
        <q-space />
        <q-btn v-if="form.id" flat icon="print" label="Печать" @click="print" />
        <template v-if="!executed && canEdit">
          <q-btn v-if="form.id && can('billing.delete_invoice')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
          <q-btn outline color="primary" icon="save" label="Сохранить" :loading="busy === 'save'" @click="save()" />
          <q-btn color="positive" unelevated icon="task_alt" label="Выполнить (в долг)" :loading="busy === 'execute'" @click="execute">
            <q-tooltip>Товар спишется со склада, сумма встанет долгом на баланс клиента. Оплата — вместе с кассой.</q-tooltip>
          </q-btn>
        </template>
        <q-btn v-if="executed && canEdit" outline color="warning" icon="undo" label="Откатить в черновик" :loading="busy === 'rollback'" @click="rollback" />
      </div>

      <div class="row q-col-gutter-sm q-mb-sm">
        <div class="col-12 col-md-4">
          <ClientSelect v-if="!form.client || (!executed && !form.id)" v-model="form.client" label="Клиент *" @update:model-value="loadPets" />
          <div v-else class="q-pt-sm">
            <router-link :to="`/clients/${form.client}`" class="text-h6 text-primary" style="text-decoration: none">{{ form.client_name }}</router-link>
            <div v-if="balance !== null" class="text-caption" :class="balance < 0 ? 'text-negative' : 'text-grey-7'">
              Баланс: {{ money(balance) }}{{ balance < 0 ? ' (долг)' : balance > 0 ? ' (аванс)' : '' }}
            </div>
          </div>
        </div>
        <q-select v-model="form.pet" :options="pets" option-value="id" option-label="label" emit-value map-options outlined dense clearable
          label="Питомец" class="col-6 col-md-2" :readonly="executed" />
        <q-select v-model="form.doctor" :options="performers" option-value="id" option-label="name" emit-value map-options outlined dense
          clearable label="Врач" class="col-6 col-md-2" :readonly="executed" hint="По умолчанию — исполнитель строк" />
        <q-input v-model="form.discount_percent" type="number" step="0.5" min="0" max="100" outlined dense clearable label="Скидка, %"
          class="col-6 col-md-2" :readonly="executed" :disable="!!form.discount_amount"
          :hint="!form.discount_percent && !form.discount_amount && Number(form.client_discount) ? `из карточки: ${Number(form.client_discount)} %` : ''" />
        <q-input v-model="form.discount_amount" type="number" step="1" min="0" outlined dense clearable label="Скидка, ₽" class="col-6 col-md-2"
          :readonly="executed" :disable="!!form.discount_percent" />
      </div>

      <div v-if="!executed" class="row q-col-gutter-sm items-center q-mb-sm">
        <q-input v-model="barcode" outlined dense class="col-12 col-sm-3" placeholder="Сканер: штрихкод + Enter" @keydown.enter.prevent="scan">
          <template #prepend><q-icon name="qr_code_scanner" /></template>
        </q-input>
        <q-select v-model="picked" :options="found" option-value="key" option-label="label" emit-value use-input input-debounce="300"
          outlined dense class="col-12 col-sm-9" label="Добавить услугу, товар или комбинацию" @filter="search" @update:model-value="addFromSearch" />
      </div>

      <q-markup-table flat bordered dense wrap-cells>
        <thead>
          <tr><th class="text-left">Позиция</th><th>Кол-во</th><th>Цена</th><th>Скидка</th><th>Сумма</th><th class="text-left">Исполнитель</th><th /></tr>
        </thead>
        <tbody>
          <template v-for="(line, i) in form.lines" :key="i">
            <tr>
              <td>
                <div class="text-weight-medium">{{ line.name }}</div>
                <div class="text-caption text-grey-7">{{ line.unit_name }}<span v-if="line.stock !== undefined && line.stock !== null"> · на складе {{ Number(line.stock) }}</span></div>
                <div v-for="(child, c) in line.children" :key="c" class="text-caption text-grey-7">— {{ child.name }} × {{ Number(child.quantity) }} = {{ money(child.amount) }}</div>
              </td>
              <td style="width: 90px"><q-input v-model="line.quantity" type="number" step="0.001" min="0" dense borderless input-class="text-right" :readonly="executed" /></td>
              <td style="width: 140px">
                <q-input v-if="line.item_unit" v-model="line.price" type="number" step="0.01" min="0" dense borderless input-class="text-right"
                  :readonly="executed" :error="outOfBounds(line)" :hint="bounds(line)" />
                <div v-else class="text-right">{{ money(line.price) }}</div>
              </td>
              <td class="text-right text-grey-8">{{ Number(line.discount) ? money(line.discount) : '' }}<q-badge v-if="line.manual" color="grey-6" label="своя цена" class="q-ml-xs"><q-tooltip>Цена изменена вручную — скидка счёта не применяется</q-tooltip></q-badge></td>
              <td class="text-right text-weight-medium">{{ money(lineAmount(line)) }}</td>
              <td style="min-width: 150px">
                <q-select v-model="line.performer" :options="performers" option-value="id" option-label="name" emit-value map-options dense
                  borderless clearable :readonly="executed" placeholder="—" />
              </td>
              <td class="text-right"><q-btn v-if="!executed" flat round dense size="sm" icon="close" @click="form.lines.splice(i, 1)" /></td>
            </tr>
          </template>
          <tr v-if="!form.lines.length"><td colspan="7" class="text-grey-7">Добавьте позиции поиском или сканером</td></tr>
        </tbody>
      </q-markup-table>

      <div class="row q-mt-md">
        <q-input v-model="form.comment" label="Примечание (видят только сотрудники)" outlined dense autogrow class="col-12 col-md-6" :readonly="executed" />
        <q-space />
        <div class="text-right">
          <div>Сумма: {{ money(form.subtotal) }}</div>
          <div v-if="Number(form.discount_total)">Скидка: −{{ money(form.discount_total) }}</div>
          <div class="text-h6">К оплате: {{ money(form.total) }}</div>
          <div v-if="dirty && !executed" class="text-caption text-warning">Итоги со скидкой пересчитаются при сохранении</div>
        </div>
      </div>
      <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
    </template>
  </q-page>
</template>

<script setup>
// Счёт: строки услуг, товаров и комбинаций; цена в границах мин./макс.; исполнитель в строке;
// скидка на весь счёт. «Выполнить» списывает товар со склада и ставит сумму долгом клиенту.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
import ClientSelect from '@/modules/clients/ClientSelect.vue'

const props = defineProps({ id: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const $q = useQuasar()
const canEdit = can('billing.change_invoice') || can('billing.add_invoice')
const loading = ref(true)
const busy = ref('')
const error = ref('')
const dirty = ref(false)
const form = ref({ lines: [] })
const pets = ref([])
const performers = ref([])
const barcode = ref('')
const found = ref([])
const picked = ref(null)
const executed = computed(() => form.value.status === 'executed')
const balance = computed(() => (form.value.client_balance === undefined ? null : Number(form.value.client_balance)))

const lineAmount = (line) => (dirty.value || line.amount === undefined ? (Number(line.price) || 0) * (Number(line.quantity) || 0) : Number(line.amount))
function bounds(line) {
  const low = line.price_min !== null && line.price_min !== undefined ? Number(line.price_min) : null
  const high = line.price_max !== null && line.price_max !== undefined ? Number(line.price_max) : null
  if (low === null && high === null) return ''
  return [low !== null ? `от ${low}` : '', high !== null ? `до ${high}` : ''].filter(Boolean).join(' ')
}
function outOfBounds(line) {
  const price = Number(line.price)
  if (line.list_price !== null && line.list_price !== undefined && price === Number(line.list_price)) return false
  return (line.price_min != null && price < Number(line.price_min)) || (line.price_max != null && price > Number(line.price_max))
}

async function loadPets(clientId) {
  if (!clientId) return (pets.value = [])
  const { data } = await apiGet(`clients/pets/?owner=${clientId}&status=active&page_size=100`)
  pets.value = (data?.results ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.species_name})` }))
  if (!form.value.pet && pets.value.length === 1) form.value.pet = pets.value[0].id
}

function addLine(option) {
  form.value.lines.push({
    item_unit: option.item_unit, item: option.item, name: option.name, unit_name: option.unit, quantity: '1',
    price: option.price, list_price: option.price, price_min: option.price_min, price_max: option.price_max,
    stock: option.stock, performer: form.value.doctor || null, children: [],
  })
}

async function scan() {
  const code = barcode.value.trim()
  barcode.value = ''
  if (!code) return
  const { data } = await apiGet(`billing/invoices/lookup/?barcode=${encodeURIComponent(code)}`)
  if (!data?.length) return $q.notify({ type: 'warning', message: `Позиция со штрихкодом ${code} не найдена` })
  const same = form.value.lines.find((l) => l.item_unit === data[0].item_unit)
  if (same) same.quantity = String(Number(same.quantity) + 1)
  else addLine(data[0])
}

async function search(text, update, abort) {
  if (text.trim().length < 2) return update(() => (found.value = []))
  const { ok, data } = await apiGet(`billing/invoices/lookup/?search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => (found.value = data.map((o) => ({
    ...o, key: o.item_unit || o.item,
    label: `${o.name} — ${o.unit} · ${o.price ? money(o.price) : 'цена по закупке'}${o.stock !== null ? ` · на складе ${Number(o.stock)}` : ''}`,
  }))))
}

function addFromSearch(key) {
  const option = found.value.find((o) => o.key === key)
  if (option) addLine(option)
  picked.value = null
}

function body() {
  return {
    client: form.value.client, pet: form.value.pet || null, doctor: form.value.doctor || null,
    discount_percent: form.value.discount_percent === '' ? null : form.value.discount_percent ?? null,
    discount_amount: form.value.discount_amount === '' ? null : form.value.discount_amount ?? null,
    comment: form.value.comment || '', appointment: form.value.appointment || null, visit: form.value.visit || null,
    input_lines: form.value.lines.map((l) => (l.item_unit
      ? { item_unit: l.item_unit, quantity: l.quantity, price: Number(l.price) === Number(l.list_price) ? null : l.price, performer: l.performer || null }
      : { item: l.item, quantity: l.quantity, performer: l.performer || null })),
  }
}

// Строки с сервера: заголовки комбинаций со своим составом; строки состава — внутри заголовка.
function applyInvoice(data) {
  const children = data.lines.filter((l) => l.parent)
  form.value = {
    ...data,
    lines: data.lines.filter((l) => !l.parent).map((l) => ({
      ...l, manual: l.manual_price, list_price: l.manual_price ? l.list_price : l.price,
      children: children.filter((c) => c.parent === l.id).map((c) => ({ name: c.name, quantity: c.quantity, amount: c.amount })),
    })),
  }
  // Замена формы сама вызовет наблюдатель изменений — сбрасываем «есть изменения» после него.
  nextTick(() => (dirty.value = false))
  loadPets(data.client)
}

async function save(silent = false) {
  error.value = ''
  if (!form.value.client) return (error.value = 'Выберите клиента'), false
  busy.value = busy.value || 'save'
  const { ok, data } = form.value.id ? await apiPatch(`billing/invoices/${form.value.id}/`, body()) : await apiPost('billing/invoices/', body())
  if (busy.value === 'save') busy.value = ''
  if (!ok) {
    error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить'
    return false
  }
  applyInvoice(data)
  if (!silent) $q.notify({ type: 'positive', message: 'Счёт сохранён' })
  return true
}

async function execute() {
  busy.value = 'execute'
  if (!(await save(true))) return (busy.value = '')
  const { ok, data } = await apiPost(`billing/invoices/${form.value.id}/execute/`)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось выполнить')
  applyInvoice(data)
  if (props.id === 'new') router.replace(`/invoices/${data.id}`)
  $q.notify({ type: 'positive', message: 'Счёт выполнен' })
}

async function rollback() {
  busy.value = 'rollback'
  const { ok, data } = await apiPost(`billing/invoices/${form.value.id}/rollback/`)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось откатить')
  applyInvoice(data)
  $q.notify({ type: 'positive', message: 'Счёт снова черновик: товар вернулся на склад, долг снят' })
}

function remove() {
  $q.dialog({ title: 'Удалить черновик счёта?', cancel: { label: 'Отмена', flat: true }, ok: { label: 'Удалить', color: 'negative', unelevated: true } })
    .onOk(async () => {
      const { ok } = await apiDelete(`billing/invoices/${form.value.id}/`)
      if (ok) router.push('/invoices')
    })
}

async function print() {
  if (!executed.value && !(await save(true))) return
  window.open(`/api/billing/invoices/${form.value.id}/print/`, '_blank')
}

watch(() => [form.value.lines, form.value.discount_percent, form.value.discount_amount], () => { if (!loading.value) dirty.value = true }, { deep: true })

onMounted(async () => {
  performers.value = (await apiGet('billing/invoices/performers/')).data ?? []
  if (props.id === 'new') {
    form.value = { client: route.query.client || null, client_name: route.query.client_name || '', pet: route.query.pet || null,
      doctor: null, discount_percent: null, discount_amount: null, comment: '', lines: [], subtotal: 0, discount_total: 0, total: 0 }
    if (form.value.client) await loadPets(form.value.client)
  } else {
    const { ok, data } = await apiGet(`billing/invoices/${props.id}/`)
    if (ok) applyInvoice(data)
  }
  loading.value = false
})
</script>
