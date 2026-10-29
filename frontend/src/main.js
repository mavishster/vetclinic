import { createApp } from 'vue'
import { Quasar, Dark, Dialog, Notify } from 'quasar'
import quasarLang from 'quasar/lang/ru'
import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
import './css/app.css'

import App from './App.vue'
import router from './router'

createApp(App)
  .use(Quasar, {
    plugins: { Dark, Dialog, Notify },
    lang: quasarLang,
    config: { dark: 'auto' }, // светлая или тёмная тема — как в системе пользователя
  })
  .use(router)
  .mount('#app')
