<template>
  <!-- Свёрнутый блок — полоска с названием: место на экране освобождается, но видно,
       что блок есть и его можно развернуть. Развёрнутый показывается как есть. -->
  <q-card v-if="collapsed" flat bordered class="cursor-pointer" @click="$emit('expand')">
    <q-card-section class="row items-center q-py-sm text-grey-7">
      <q-icon name="unfold_more" class="q-mr-sm" />
      <span>{{ title }}</span>
    </q-card-section>
  </q-card>
  <slot v-else />
</template>

<script setup>
defineProps({ title: { type: String, required: true }, collapsed: Boolean })
defineEmits(['expand'])
</script>
