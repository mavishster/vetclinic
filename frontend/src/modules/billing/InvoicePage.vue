<template>
  <q-page padding>
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner size="40px" color="primary" /></div>
    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" @click="$router.back()" />
        <h1 class="text-h5 q-my-none">{{ form.is_quick ? 'Быстрый счёт' : 'Счёт' }}{{ form.number ? ` № ${form.number}` : '' }}</h1>
        <q-badge v-if="form.id" :color="PAY[form.payment_status]?.color || 'grey-6'" :label="PAY[form.payment_status]?.label || 'черновик'" />
        <span v-if="executed && form.payment_status === 'partial'" class="text-caption">оплачено {{ money(form.paid_amount) }}</span>
        <q-space />
        <q-btn v-if="form.id" flat icon="print" label="Печать" @click="print" />
        <template v-if="!executed && canEdit">
          <q-btn v-if="form.id && can('billing.delete_invoice')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
          <q-btn outline color="primary" icon="save" label="Сохранить" :loading="busy === 'save'" @click="save()" />
          <q-btn v-if="!form.is_quick" outline color="positive" icon="schedule" label="В долг" :loading="busy === 'execute'" @click="execute()">
            <q-tooltip>Выполнить без оплаты: товар спишется, сумма встанет долгом на баланс клиента</q-tooltip>
          </q-btn>
          <q-btn v-if="can('cash.add_payment')" color="positive" unelevated icon="payments" label="Оплатить" :loading="busy === 'pay'"
            @click="execute(true)" />
        </template>
        <q-btn v-if="executed && Number(form.unpaid) > 0 && can('cash.add_payment')" color="positive" unelevated icon="payments"
          label="Оплатить" @click="payOpen = true" />
        <q-btn v-if="executed && can('billing.rollback_invoice')" outline color="warning" icon="undo" label="Откатить в черновик" :loading="busy === 'rollback'" @click="rollback" />
      </div>

      <div class="row q-col-gutter-sm q-mb-sm">
        <div class="col-12 col-md-4">
          <ClientSelect v-if="!form.is_quick && (!form.client || (!executed && !form.id))" v-model="form.client" label="Клиент *"
            @update:model-value="loadPets" />
          <div v-else class="q-pt-sm">
            <router-link :to="`/clients/${form.client}`" class="text-h6 text-primary" style="text-decoration: none">{{ form.client_name }}</router-link>
            <div v-if="balance !== null" class="text-caption" :class="balance < 0 ? 'text-negative' : 'text-grey-7'">
              Баланс: {{ money(balance) }}{{ balance < 0 ? ' (долг)' : balance > 0 ? ' (аванс)' : '' }}
            </div>
          </div>
        </div>
        <q-select v-model="form.pet" :options="pets" option-value="id" option-label="label" emit-value map-options outlined dense clearable
          label="Питомец" class="col-6 col-md-2" :readonly="executed && !canEdit" @update:model-value="(v) => executed && details({ pet: v })" />
        <q-select v-model="form.doctor" :options="performers" option-value="id" option-label="name" emit-value map-options outlined dense
          clearable label="Врач" class="col-6 col-md-2" :readonly="executed && !canEdit" hint="По умолчанию — исполнитель строк"
          @update:model-value="(v) => executed && details({ doctor: v })" />
        <!-- Скидка на все товары / на все услуги: у них разные лимиты; ставится, где укладывается в предел -->
        <template v-if="!executed">
          <q-input v-model="kindPercent.goods" type="number" step="1" min="0" max="100" outlined dense class="col-6 col-md-2"
            :label="`На все товары, % (до ${Number(clinic.max_discount_goods)})`" hint="Enter — применить" @keyup.enter="applyToKind('goods')">
            <template #append><q-btn flat dense round icon="done_all" :disable="kindPercent.goods === ''" @click="applyToKind('goods')"><q-tooltip>Применить ко всем товарам</q-tooltip></q-btn></template>
          </q-input>
          <q-input v-model="kindPercent.service" type="number" step="1" min="0" max="100" outlined dense class="col-6 col-md-2"
            :label="`На все услуги, % (до ${Number(clinic.max_discount_services)})`"
            :hint="Number(form.client_discount) ? `в карточке клиента: ${Number(form.client_discount)} %` : 'Enter — применить'"
            @keyup.enter="applyToKind('service')">
            <template #append><q-btn flat dense round icon="done_all" :disable="kindPercent.service === ''" @click="applyToKind('service')"><q-tooltip>Применить ко всем услугам</q-tooltip></q-btn></template>
          </q-input>
        </template>
        <q-input v-model="form.discount_amount" type="number" step="1" min="0" outlined dense clearable :label="`Скидка суммой, ${currency()}`" class="col-6 col-md-2"
          :readonly="executed" hint="Делится между строками без своей скидки" />
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
          <tr>
            <th class="text-left">Позиция</th><th>Кол-во</th><th>Цена</th>
            <th>Скидка, %<q-tooltip>Товары — не больше {{ Number(clinic.max_discount_goods) }} %, услуги — не больше {{ Number(clinic.max_discount_services) }} %, и цена со скидкой не ниже себестоимости</q-tooltip></th>
            <th v-if="showCost">Себестоимость<q-tooltip>Видна только сотрудникам с правом «Видеть себестоимость»; в счёт и чек не печатается</q-tooltip></th>
            <th>Сумма</th><th class="text-left">Исполнитель</th><th />
          </tr>
        </thead>
        <tbody>
          <template v-for="(line, i) in form.lines" :key="i">
            <tr>
              <td>
                <div class="text-weight-medium">{{ line.name }}</div>
                <div class="text-caption text-grey-7">{{ line.unit_name }}<span v-if="line.stock !== undefined && line.stock !== null"> · на складе {{ line.stock_text || Number(line.stock) }}</span></div>
                <div v-for="(child, c) in line.children" :key="c" class="text-caption text-grey-7">— {{ child.name }} × {{ Number(child.quantity) }} = {{ money(child.amount) }}<span v-if="child.discount_percent"> (−{{ Number(child.discount_percent) }} %)</span></div>
              </td>
              <td style="width: 90px"><q-input v-model="line.quantity" type="number" step="any" min="0" dense borderless input-class="text-right" :readonly="executed" /></td>
              <td style="width: 140px">
                <q-input v-if="line.item_unit" v-model="line.price" type="number" step="0.01" min="0" dense borderless input-class="text-right"
                  :readonly="executed" :error="outOfBounds(line)" :hint="bounds(line)" />
                <div v-else class="text-right">{{ money(line.price) }}</div>
              </td>
              <td style="width: 120px">
                <q-badge v-if="isManual(line)" color="grey-6" label="своя цена"><q-tooltip>Цена изменена вручную — без скидки</q-tooltip></q-badge>
                <template v-else-if="line.item_unit">
                  <q-input v-model="line.discount_percent" type="number" step="1" min="0" dense borderless input-class="text-right" placeholder="—"
                    :readonly="executed" :error="!!discountError(line)" :error-message="discountError(line)" no-error-icon
                    :hint="line.max_discount ? `до ${Number(line.max_discount.percent)} %` : ''" />
                  <div v-if="Number(line.discount)" class="text-caption text-grey-7 text-right">−{{ money(line.discount) }}</div>
                </template>
                <!-- Комбинация: товарам состава и услугам — каждым свои проценты -->
                <template v-else>
                  <q-input v-model="line.goods_discount" type="number" step="1" min="0" dense borderless input-class="text-right" placeholder="—"
                    prefix="товары" :readonly="executed" />
                  <q-input v-model="line.services_discount" type="number" step="1" min="0" dense borderless input-class="text-right" placeholder="—"
                    prefix="услуги" :readonly="executed" />
                  <div v-if="Number(line.discount)" class="text-caption text-grey-7 text-right">−{{ money(line.discount) }}</div>
                </template>
              </td>
              <td v-if="showCost" class="text-right text-grey-8">
                <template v-if="line.unit_cost">{{ money(line.unit_cost) }}<q-tooltip v-if="line.cost_source">{{ line.cost_source }}</q-tooltip></template>
                <span v-else-if="line.item_unit" class="text-caption">не задана</span>
              </td>
              <td class="text-right text-weight-medium">{{ money(lineAmount(line)) }}</td>
              <td style="min-width: 150px">
                <q-select v-model="line.performer" :options="performers" option-value="id" option-label="name" emit-value map-options dense
                  borderless clearable :readonly="executed && !canEdit" placeholder="—"
                  @update:model-value="(v) => executed && details({ performers: { [line.id]: v } })" />
              </td>
              <td class="text-right"><q-btn v-if="!executed" flat round dense size="sm" icon="close" @click="form.lines.splice(i, 1)" /></td>
            </tr>
          </template>
          <tr v-if="!form.lines.length"><td :colspan="showCost ? 8 : 7" class="text-grey-7">Добавьте позиции поиском или сканером</td></tr>
        </tbody>
      </q-markup-table>

      <div class="row q-mt-md">
        <q-input v-model="form.comment" label="Примечание (видят только сотрудники)" outlined dense autogrow class="col-12 col-md-6" :readonly="executed" />
        <q-space />
        <div class="text-right">
          <div>Сумма: {{ money(form.subtotal) }}</div>
          <div v-if="Number(form.discount_total)">Скидка: −{{ money(form.discount_total) }}</div>
          <div class="text-h6">К оплате: {{ money(form.total) }}</div>
          <div v-if="executed && Number(form.paid_amount)">Оплачено: {{ money(form.paid_amount) }}</div>
          <div v-if="executed && Number(form.unpaid)" class="text-negative">Долг по счёту: {{ money(form.unpaid) }}</div>
          <div v-if="dirty && !executed" class="text-caption text-warning">Итоги со скидкой пересчитаются при сохранении</div>
        </div>
      </div>
      <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
      <div v-if="executed && canEdit" class="text-caption text-grey-7 q-mt-sm">
        Врача, питомца и исполнителей в выполненном счёте можно поменять без отката — изменение запишется в журнал.
      </div>
      <PaymentDialog v-model="payOpen" :client-id="form.client" :client-name="form.client_name" :invoice-ids="[form.id]"
        :guest="!!form.is_quick" @paid="reload" />
    </template>
  </q-page>
</template>

<script setup>
// Счёт: строки услуг, товаров и комбинаций; цена в границах мин./макс.; исполнитель в строке;
// скидка на весь счёт. «Оплатить» — выполнить и сразу принять оплату; «В долг» — без оплаты.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import { currency, money } from '@/modules/catalog/money'
import ClientSelect from '@/modules/clients/ClientSelect.vue'
// Окно оплаты — модуль «Касса».
import PaymentDialog from '@/modules/cash/PaymentDialog.vue'

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
const payOpen = ref(false)
const PAY = {
  paid: { label: 'оплачен', color: 'positive' },
  partial: { label: 'оплачен частично', color: 'warning' },
  debt: { label: 'долг', color: 'negative' },
  draft: { label: 'черновик', color: 'grey-6' },
}
const balance = computed(() => (form.value.client_balance === undefined ? null : Number(form.value.client_balance)))

const lineAmount = (line) => {
  if (!dirty.value && line.amount !== undefined) return Number(line.amount)
  const gross = (Number(line.price) || 0) * (Number(line.quantity) || 0)
  return isManual(line) ? gross : gross * (1 - (Number(line.discount_percent) || 0) / 100)
}

// --- Скидки: лимит по типу позиции и не ниже себестоимости (сервер проверяет то же) ---
const showCost = can('catalog.view_cost')
// Остаток в подборе — склада этого счёта (по умолчанию сервер берёт оперативный).
const warehouseParam = () => (form.value.warehouse ? `&warehouse=${form.value.warehouse}` : '')
const clinic = ref({ max_discount_goods: 5, max_discount_services: 10 })
const kindPercent = ref({ goods: '', service: '' })
const isManual = (line) => line.item_unit && line.list_price !== null && line.list_price !== undefined && Number(line.price) !== Number(line.list_price)

function discountError(line) {
  const value = line.discount_percent
  if (value === null || value === undefined || value === '' || !line.item_unit || !line.max_discount) return ''
  const max = Number(line.max_discount.percent)
  if (Number(value) < 0) return 'Не меньше 0'
  if (Number(value) <= max) return ''
  return line.max_discount.reason === 'cost' ? `Не больше ${max} % — ниже себестоимости` : `Не больше ${max} %`
}

// «Скидка на все товары» / «на все услуги»: ставим, где укладывается в предел; остальные — список.
function applyToKind(kind) {
  const raw = kindPercent.value[kind]
  const percent = raw === '' ? null : Number(raw)
  const skipped = []
  for (const line of form.value.lines) {
    if (isManual(line)) continue
    if (!line.item_unit) {
      // комбинация: процент — товарам или услугам состава (каждой позиции в её пределах)
      line[kind === 'goods' ? 'goods_discount' : 'services_discount'] = percent
      continue
    }
    if (line.kind !== kind) continue
    const max = line.max_discount ? Number(line.max_discount.percent) : 100
    if (percent === null || percent <= max) line.discount_percent = percent
    else {
      line.discount_percent = null
      skipped.push(`${line.name} — не больше ${max} %${line.max_discount?.reason === 'cost' ? ' (себестоимость)' : ''}`)
    }
  }
  if (skipped.length) {
    $q.dialog({ title: `Скидка ${percent} % применена не ко всем ${kind === 'goods' ? 'товарам' : 'услугам'}`,
      message: `Без скидки остались:<br>• ${skipped.join('<br>• ')}`, html: true, ok: { label: 'Понятно', color: 'primary', flat: true } })
  }
}
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
  if (!executed.value && form.value.client_discount === undefined) {
    // Скидка из карточки клиента — подставляется в новые строки (в пределах лимитов).
    apiGet(`clients/clients/${clientId}/`).then(({ ok, data }) => { if (ok) form.value.client_discount = data.discount_percent })
  }
  const { data } = await apiGet(`clients/pets/?owner=${clientId}&status=active&page_size=100`)
  pets.value = (data?.results ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.species_name})` }))
  if (!form.value.pet && pets.value.length === 1) form.value.pet = pets.value[0].id
}

function addLine(option) {
  form.value.lines.push({
    item_unit: option.item_unit, item: option.item, name: option.name, unit_name: option.unit, quantity: '1',
    price: option.price, list_price: option.price, price_min: option.price_min, price_max: option.price_max,
    stock: option.stock, stock_text: option.stock_text, performer: form.value.doctor || null, children: [],
    max_discount: option.max_discount ? { percent: option.max_discount, reason: option.max_reason } : null,
    unit_cost: option.unit_cost ?? null, cost_source: option.cost_source || '', kind: option.kind,
    discount_percent: option.item_unit ? defaultDiscount(option) : null,
    // комбинация: скидка из карточки клиента — товарам и услугам состава в пределах лимитов
    goods_discount: option.item_unit ? undefined : clientWithin(Number(clinic.value.max_discount_goods)),
    services_discount: option.item_unit ? undefined : clientWithin(Number(clinic.value.max_discount_services)),
  })
}

function clientWithin(max) {
  const client = Number(form.value.client_discount) || 0
  return client && client <= max ? client : null
}

// Скидка из карточки клиента — если укладывается в предел этой позиции.
function defaultDiscount(option) {
  const client = Number(form.value.client_discount) || 0
  if (!client || !option.item_unit) return client || null
  return option.max_discount && client > Number(option.max_discount) ? null : client
}

async function scan() {
  const code = barcode.value.trim()
  barcode.value = ''
  if (!code) return
  const { data } = await apiGet(`billing/invoices/lookup/?barcode=${encodeURIComponent(code)}${warehouseParam()}`)
  if (!data?.length) return $q.notify({ type: 'warning', message: `Позиция со штрихкодом ${code} не найдена` })
  const same = form.value.lines.find((l) => l.item_unit === data[0].item_unit)
  if (same) same.quantity = String(Number(same.quantity) + 1)
  else addLine(data[0])
}

async function search(text, update, abort) {
  if (text.trim().length < 2) return update(() => (found.value = []))
  const { ok, data } = await apiGet(`billing/invoices/lookup/?search=${encodeURIComponent(text)}${warehouseParam()}`)
  if (!ok) return abort()
  update(() => (found.value = data.map((o) => ({
    ...o, key: o.item_unit || o.item,
    label: `${o.name} — ${o.unit} · ${o.price ? money(o.price) : 'цена по закупке'}${o.stock !== null ? ` · на складе ${o.stock_text || Number(o.stock)}` : ''}`,
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
    discount_amount: form.value.discount_amount === '' ? null : form.value.discount_amount ?? null,
    comment: form.value.comment || '', appointment: form.value.appointment || null, visit: form.value.visit || null,
    is_quick: !!form.value.is_quick,
    input_lines: form.value.lines.map((l) => (l.item_unit
      ? { item_unit: l.item_unit, quantity: l.quantity, price: Number(l.price) === Number(l.list_price) ? null : l.price, performer: l.performer || null,
          discount_percent: l.discount_percent === '' || l.discount_percent === undefined ? null : l.discount_percent }
      : { item: l.item, quantity: l.quantity, performer: l.performer || null,
          goods_discount: l.goods_discount === '' || l.goods_discount === undefined ? null : l.goods_discount,
          services_discount: l.services_discount === '' || l.services_discount === undefined ? null : l.services_discount })),
  }
}

function commonChildDiscount(children) {
  const values = [...new Set(children.map((c) => c.discount_percent).filter((v) => v !== null))]
  return values.length === 1 ? values[0] : null
}

// Строки с сервера: заголовки комбинаций со своим составом; строки состава — внутри заголовка.
function applyInvoice(data) {
  const children = data.lines.filter((l) => l.parent)
  form.value = {
    ...data,
    lines: data.lines.filter((l) => !l.parent).map((l) => ({
      ...l, manual: l.manual_price, list_price: l.manual_price ? l.list_price : l.price,
      // У заголовка комбинации — скидки товарам и услугам состава (общие для каждой группы).
      goods_discount: l.item_unit ? undefined : commonChildDiscount(children.filter((c) => c.parent === l.id && c.kind === 'goods')),
      services_discount: l.item_unit ? undefined : commonChildDiscount(children.filter((c) => c.parent === l.id && c.kind === 'service')),
      children: children.filter((c) => c.parent === l.id).map((c) => ({ name: c.name, quantity: c.quantity, amount: c.amount, discount_percent: c.discount_percent })),
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

async function execute(andPay = false) {
  busy.value = andPay ? 'pay' : 'execute'
  if (!(await save(true))) return (busy.value = '')
  const { ok, data } = await apiPost(`billing/invoices/${form.value.id}/execute/`)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось выполнить')
  applyInvoice(data)
  // Новый счёт получает свой адрес — экран пересоздаётся, поэтому окно оплаты
  // откроется уже на нём (по метке ?pay=1).
  if (props.id === 'new') return router.replace({ path: `/invoices/${data.id}`, query: andPay && Number(data.unpaid) > 0 ? { pay: '1' } : {} })
  if (andPay && Number(data.unpaid) > 0) payOpen.value = true
  else $q.notify({ type: 'positive', message: Number(data.unpaid) ? 'Счёт выполнен — сумма встала долгом' : 'Счёт выполнен и оплачен авансом клиента' })
}

async function reload() {
  const { ok, data } = await apiGet(`billing/invoices/${form.value.id}/`)
  if (ok) applyInvoice(data)
}

// Выполненный счёт: врач, питомец, исполнители меняются без отката.
async function details(changes) {
  const { ok, data } = await apiPatch(`billing/invoices/${form.value.id}/details/`, changes)
  if (!ok) {
    $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] || 'Не удалось сохранить' })
    return reload()
  }
  applyInvoice(data)
  $q.notify({ type: 'positive', message: 'Изменение сохранено' })
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

watch(() => [form.value.lines, form.value.discount_amount], () => { if (!loading.value) dirty.value = true }, { deep: true })

onMounted(async () => {
  performers.value = (await apiGet('billing/invoices/performers/')).data ?? []
  apiGet('core/clinic/').then(({ ok, data }) => { if (ok) clinic.value = data })
  if (props.id === 'new') {
    form.value = { client: route.query.client || null, client_name: route.query.client_name || '', pet: route.query.pet || null,
      doctor: null, discount_amount: null, comment: '', lines: [], subtotal: 0, discount_total: 0, total: 0 }
    if (route.query.quick === '1') {
      // Быстрый счёт: клиент — служебный «Гость», оплата сразу.
      const guest = (await apiGet('billing/invoices/guest/')).data
      Object.assign(form.value, { client: guest.id, client_name: guest.name, is_quick: true })
    }
    if (form.value.client) await loadPets(form.value.client)
  } else {
    const { ok, data } = await apiGet(`billing/invoices/${props.id}/`)
    if (ok) applyInvoice(data)
    if (ok && route.query.pay === '1' && Number(data.unpaid) > 0) payOpen.value = true
  }
  loading.value = false
})
</script>
