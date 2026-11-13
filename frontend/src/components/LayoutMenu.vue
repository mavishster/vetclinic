<template>
  <!-- Настройка блоков экрана: что показывать, где и в каком порядке. У каждого своё. -->
  <q-btn flat round icon="dashboard_customize" :color="color">
    <q-tooltip>Настроить блоки</q-tooltip>
    <q-menu style="min-width: 300px">
      <q-list dense>
        <q-item-label header>Блоки на экране</q-item-label>
        <q-item v-for="block in layout.state.blocks" :key="block.name">
          <q-item-section avatar>
            <q-checkbox :model-value="block.visible" @update:model-value="layout.toggle(block)" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ block.title }}</q-item-label>
            <q-item-label caption>{{ block.column === 'left' ? 'слева' : 'справа' }}</q-item-label>
          </q-item-section>
          <q-item-section side class="row no-wrap">
            <div class="row no-wrap">
              <q-btn flat dense round size="sm" icon="arrow_upward" :disable="!block.visible" @click="layout.move(block, -1)" />
              <q-btn flat dense round size="sm" icon="arrow_downward" :disable="!block.visible" @click="layout.move(block, 1)" />
              <q-btn flat dense round size="sm" :icon="block.column === 'left' ? 'arrow_forward' : 'arrow_back'"
                :disable="!block.visible" @click="layout.moveToColumn(block, block.column === 'left' ? 'right' : 'left')">
                <q-tooltip>{{ block.column === 'left' ? 'Перенести вправо' : 'Перенести влево' }}</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
        <q-separator spaced />
        <q-item-label header class="q-pt-none">Готовые расклады</q-item-label>
        <q-item v-for="(preset, name) in presets" :key="name" clickable @click="layout.applyPreset(name)">
          <q-item-section>
            <q-item-label>{{ preset.title }}</q-item-label>
            <q-item-label caption>{{ preset.hint }}</q-item-label>
          </q-item-section>
          <q-item-section v-if="layout.state.preset === name" side><q-icon name="check" color="positive" /></q-item-section>
        </q-item>
        <q-separator spaced />
        <q-item clickable @click="layout.reset()">
          <q-item-section avatar><q-icon name="restart_alt" /></q-item-section>
          <q-item-section>Вернуть как было</q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<script setup>
defineProps({
  layout: { type: Object, required: true },
  presets: { type: Object, default: () => ({}) },
  color: { type: String, default: '' },
})
</script>
