<template>
  <div class="md" v-html="html" />
</template>

<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({ content: { type: [String, Number], default: '' } })
const html = computed(() => renderMarkdown(props.content))
</script>
