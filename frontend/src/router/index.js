import { createRouter, createWebHistory } from 'vue-router'
import VideoWall from '../views/VideoWall.vue'
import Messages from '../views/Messages.vue'
import ProcessingLogs from '../views/ProcessingLogs.vue'
import Settings from '../views/Settings.vue'

const routes = [
  {
    path: '/',
    name: 'VideoWall',
    component: VideoWall,
  },
  {
    path: '/messages',
    name: 'Messages',
    component: Messages,
  },
  {
    path: '/processing-logs',
    name: 'ProcessingLogs',
    component: ProcessingLogs,
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
