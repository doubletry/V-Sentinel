import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElAvatar from 'element-plus/es/components/avatar/index'
import ElBadge from 'element-plus/es/components/badge/index'
import ElButton, { ElButtonGroup } from 'element-plus/es/components/button/index'
import ElConfigProvider from 'element-plus/es/components/config-provider/index'
import ElContainer, { ElHeader, ElMain } from 'element-plus/es/components/container/index'
import ElDialog from 'element-plus/es/components/dialog/index'
import ElForm, { ElFormItem } from 'element-plus/es/components/form/index'
import ElIcon from 'element-plus/es/components/icon/index'
import ElInput from 'element-plus/es/components/input/index'
import ElLoading from 'element-plus/es/components/loading/index'
import ElMenu, { ElMenuItem } from 'element-plus/es/components/menu/index'
import ElPagination from 'element-plus/es/components/pagination/index'
import ElPopconfirm from 'element-plus/es/components/popconfirm/index'
import ElScrollbar from 'element-plus/es/components/scrollbar/index'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index'
import ElSwitch from 'element-plus/es/components/switch/index'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index'
import ElTag from 'element-plus/es/components/tag/index'
import ElUpload from 'element-plus/es/components/upload/index'
import {
  Bell,
  Check,
  ChatRound,
  CircleClose,
  Close,
  Crop,
  Delete,
  Document,
  Download,
  Edit,
  EditPen,
  Monitor,
  Plus,
  Setting,
  Upload,
  VideoCamera,
  View,
} from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import { i18n } from './i18n/index.js'
import router from './router/index.js'
import config from './config.js'

const app = createApp(App)

// Register only the Element Plus components used by the current UI.
const elementPlusComponents = [
  ElAvatar,
  ElBadge,
  ElButton,
  ElButtonGroup,
  ElConfigProvider,
  ElContainer,
  ElDialog,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElPopconfirm,
  ElScrollbar,
  ElSelect,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  ElUpload,
]

elementPlusComponents.forEach((component) => {
  app.component(component.name, component)
})

app.use(ElLoading)

// Register only the icons used by the current UI to avoid pulling the full icon set.
const elementPlusIcons = [
  ['Bell', Bell],
  ['Check', Check],
  ['ChatRound', ChatRound],
  ['CircleClose', CircleClose],
  ['Close', Close],
  ['Crop', Crop],
  ['Delete', Delete],
  ['Document', Document],
  ['Download', Download],
  ['Edit', Edit],
  ['EditPen', EditPen],
  ['Monitor', Monitor],
  ['Plus', Plus],
  ['Setting', Setting],
  ['Upload', Upload],
  ['VideoCamera', VideoCamera],
  ['View', View],
]

elementPlusIcons.forEach(([name, component]) => {
  app.component(name, component)
})

app.use(createPinia())
app.use(router)
app.use(i18n)

// Make config available globally
app.config.globalProperties.$config = config

// Set document title
document.title = config.siteName

app.mount('#app')
