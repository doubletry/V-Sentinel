import { createRouter, createWebHistory } from 'vue-router'

const VideoWall = () => import('../views/VideoWall.vue')
const Messages = () => import('../views/Messages.vue')
const VehicleEvents = () => import('../views/VehicleEvents.vue')
const ProcessingLogs = () => import('../views/ProcessingLogs.vue')
const Settings = () => import('../views/Settings.vue')

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
    path: '/vehicle-events',
    name: 'VehicleEvents',
    component: VehicleEvents,
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
