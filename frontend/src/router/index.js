import { createRouter, createWebHistory } from 'vue-router'
import VideoWall from '../views/VideoWall.vue'
import Messages from '../views/Messages.vue'

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
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
