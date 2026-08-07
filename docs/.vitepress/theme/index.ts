import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import SurfaceChooser from './components/SurfaceChooser.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('SurfaceChooser', SurfaceChooser)
  },
} satisfies Theme
