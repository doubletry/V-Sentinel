<template>
  <div class="video-wall">
    <!-- Left panel: source list -->
    <div class="left-panel">
      <SourceList />
    </div>
    <!-- Right panel: video grid -->
    <div class="right-panel">
      <VideoGrid />
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useSourceStore } from '../stores/source.js'
import SourceList from '../components/SourceList.vue'
import VideoGrid from '../components/VideoGrid.vue'

const store = useSourceStore()

onMounted(async () => {
  await store.fetchSources()
  await store.syncProcessorStatus()
})
</script>

<style scoped>
.video-wall {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.left-panel {
  width: 260px;
  flex-shrink: 0;
  overflow: hidden;
}

.right-panel {
  flex: 1;
  overflow: hidden;
}
</style>
