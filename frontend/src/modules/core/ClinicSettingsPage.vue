<template>
  <q-page padding class="narrow-page">
    <h1 class="text-h5 q-mt-none">Настройки клиники</h1>
    <q-form @submit="save">
      <q-card flat bordered class="q-mb-md">
        <q-card-section class="text-subtitle1">Клиника</q-card-section>
        <q-card-section class="q-pt-none q-gutter-y-sm">
          <q-input v-model="form.name" outlined dense label="Название" hint="Печатается в счетах, выписках, документах на подпись" :readonly="!canEdit" />
          <q-input v-model="form.address" outlined dense label="Адрес" :readonly="!canEdit" />
          <q-input v-model="form.phone" outlined dense label="Телефон" :readonly="!canEdit" />
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1">Скидки в счёте</div>
          <div class="text-caption text-grey-7">
            Больше этих процентов скидку в строке счёта поставить нельзя. Кроме того, цена со скидкой не может быть ниже
            себестоимости — система не даст применить такую скидку.
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none row q-col-gutter-sm">
          <q-input v-model="form.max_discount_goods" type="number" step="0.5" min="0" max="100" outlined dense suffix="%"
            label="Максимальная скидка на товары" class="col-12 col-sm-6" :readonly="!canEdit" :error="!!errors.max_discount_goods"
            :error-message="errors.max_discount_goods" />
          <q-input v-model="form.max_discount_services" type="number" step="0.5" min="0" max="100" outlined dense suffix="%"
            label="Максимальная скидка на услуги" class="col-12 col-sm-6" :readonly="!canEdit" :error="!!errors.max_discount_services"
            :error-message="errors.max_discount_services" />
          <div class="col-12 text-caption text-grey-7">Комбинации — по составу: товары в них — по лимиту товаров, услуги — по лимиту услуг.</div>
        </q-card-section>
      </q-card>
      <q-btn v-if="canEdit" type="submit" color="primary" unelevated icon="save" label="Сохранить" :loading="saving" />
    </q-form>
  </q-page>
</template>

<script setup>
// Настройки клиники: реквизиты для печатных форм и предельные скидки в счёте.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, fieldErrors } from '@/api'
import { can } from '@/session'

const $q = useQuasar()
const canEdit = can('core.change_clinic')
const form = ref({})
const errors = ref({})
const saving = ref(false)

async function save() {
  errors.value = {}
  saving.value = true
  const { ok, data } = await apiPatch('core/clinic/', form.value)
  saving.value = false
  if (!ok) return (errors.value = fieldErrors(data))
  form.value = data
  $q.notify({ type: 'positive', message: 'Настройки сохранены' })
}

onMounted(async () => {
  form.value = (await apiGet('core/clinic/')).data ?? {}
})
</script>
