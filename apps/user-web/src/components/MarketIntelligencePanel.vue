<template>
  <CardPanel title="近期商品热榜" desc="按关键词定时采集已登录闲鱼账号可见的商品；首次采集建立基线，第二次起显示近 7 天增量。" style="margin-top:16px">
    <div class="toolbar" style="flex-wrap:wrap">
      <select v-model="accountId" class="input" aria-label="采集账号">
        <option value="">选择闲鱼账号</option>
        <option v-for="account in accounts" :key="account.id" :value="String(account.id)">{{ account.nickname || account.name || account.id }}</option>
      </select>
      <input v-model.trim="keyword" class="input" maxlength="50" placeholder="监控关键词" aria-label="监控关键词">
      <select v-model.number="intervalMinutes" class="input" aria-label="采集间隔">
        <option :value="30">每 30 分钟</option><option :value="60">每小时</option><option :value="120">每 2 小时</option><option :value="360">每 6 小时</option>
      </select>
      <AppButton type="primary" :disabled="busy || !accountId || !keyword" @click="createWatch">添加监控</AppButton>
    </div>
    <div class="toolbar" style="margin-top:12px;flex-wrap:wrap">
      <select v-model="selectedWatchId" class="input" aria-label="监控任务" @change="refreshTrends">
        <option value="">选择监控任务</option>
        <option v-for="watch in watches" :key="watch.id" :value="String(watch.id)">{{ watch.keyword }} · 账号 {{ watch.accountId }}</option>
      </select>
      <AppButton :disabled="busy || !selectedWatchId" @click="collectNow">立即采集</AppButton>
      <AppButton :disabled="busy || !selectedWatchId" @click="refreshTrends">刷新热榜</AppButton>
      <span class="subtle">{{ selectedWatch?.lastError ? `上次失败：${selectedWatch.lastError}` : selectedWatch?.lastRunAt ? `上次采集：${selectedWatch.lastRunAt}` : '' }}</span>
    </div>
    <p v-if="message" class="subtle" style="margin-top:10px">{{ message }}</p>
    <div v-if="trends.length" style="margin-top:14px;max-height:360px;overflow:auto">
      <div v-for="item in trends" :key="item.itemId" class="market-row">
        <div style="min-width:0;flex:1">
          <a :href="item.link" target="_blank" rel="noopener noreferrer">{{ item.title || item.itemId }}</a>
          <div class="subtle">¥{{ item.price ?? '未知' }} · 浏览 +{{ item.viewDelta ?? '未知' }} · 想要 +{{ item.wantDelta ?? '未知' }} · 已售 +{{ item.soldDelta ?? '未知' }} · {{ item.sampleCount }} 次采样</div>
        </div>
        <b>{{ item.heatScore ?? '待积累' }}</b>
        <button class="app-btn" @click="showComparison(item)">比价</button>
      </div>
    </div>
    <p v-else-if="selectedWatchId" class="subtle" style="margin-top:12px">暂无快照。首次采集只建立基线，后续采集才会产生近期热度。</p>
    <div v-if="selectedItem" style="border-top:1px solid #e5e7eb;margin-top:14px;padding-top:12px">
      <b>{{ selectedItem.title }} · 跨平台比价</b>
      <p class="subtle">拼多多、1688 自动报价接口尚未授权。下面可录入真实同款报价测试比价流程；人工报价会明确标记来源。</p>
      <div class="toolbar" style="flex-wrap:wrap">
        <select v-model="quote.platform" class="input"><option value="pdd">拼多多</option><option value="1688">1688</option></select>
        <input v-model.trim="quote.sourceUrl" class="input" placeholder="商品 HTTPS 链接">
        <input v-model.trim="quote.modelEvidence" class="input" placeholder="同款型号 / 规格证据">
        <input v-model.number="quote.price" type="number" min="0" step="0.01" class="input" placeholder="单价">
        <input v-model.number="quote.shipping" type="number" min="0" step="0.01" class="input" placeholder="运费">
        <input v-model.number="quote.minimumQuantity" type="number" min="1" class="input" placeholder="起订量">
        <AppButton :disabled="busy" @click="saveQuote">保存报价</AppButton>
      </div>
      <div v-for="(offer, index) in comparisons" :key="index" class="market-row">
        <span>{{ offer.platform === 'pdd' ? '拼多多' : '1688' }} · 人工录入 · {{ offer.modelEvidence }} · 起订 {{ offer.comparison?.minimumQuantity || '—' }} 件</span>
        <b>单件价差 {{ offer.comparison?.difference ?? '不可比' }}</b>
        <a :href="offer.sourceUrl" target="_blank" rel="noopener noreferrer">核对来源</a>
      </div>
    </div>
  </CardPanel>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import CardPanel from './CardPanel.vue'
import AppButton from './AppButton.vue'
import { addMarketQuote, addMarketWatch, collectMarketWatch, listMarketComparisons, listMarketTrends, listMarketWatches } from '../api/market.js'

defineProps({ accounts: { type: Array, default: () => [] } })
const accountId = ref('')
const keyword = ref('')
const intervalMinutes = ref(120)
const watches = ref([])
const selectedWatchId = ref('')
const trends = ref([])
const selectedItem = ref(null)
const comparisons = ref([])
const busy = ref(false)
const message = ref('')
const quote = reactive({ platform: 'pdd', sourceUrl: '', modelEvidence: '', price: null, shipping: 0, minimumQuantity: 1 })
const selectedWatch = computed(() => watches.value.find(w => String(w.id) === selectedWatchId.value))

async function refreshWatches() {
  const response = await listMarketWatches()
  watches.value = Array.isArray(response?.data) ? response.data : []
}
async function createWatch() {
  busy.value = true
  try {
    const response = await addMarketWatch({ accountId: Number(accountId.value), keyword: keyword.value, intervalMinutes: intervalMinutes.value, searchMode: 'auto' })
    await refreshWatches()
    selectedWatchId.value = String(response?.data?.id || '')
    message.value = '监控已建立，后台会按间隔采集；也可点击“立即采集”。'
    await refreshTrends()
  } catch (error) { message.value = error.message || '添加监控失败' } finally { busy.value = false }
}
async function collectNow() {
  busy.value = true
  try {
    const response = await collectMarketWatch(selectedWatchId.value)
    message.value = `本次保存 ${response?.data?.saved ?? 0} 条商品快照。`
    await refreshWatches()
    await refreshTrends()
  } catch (error) { message.value = error.message || '采集失败' } finally { busy.value = false }
}
async function refreshTrends() {
  if (!selectedWatchId.value) { trends.value = []; return }
  try { trends.value = (await listMarketTrends(selectedWatchId.value))?.data?.items || [] }
  catch (error) { message.value = error.message || '热榜查询失败' }
}
async function showComparison(item) {
  selectedItem.value = item
  try { comparisons.value = (await listMarketComparisons(item.itemId))?.data?.offers || [] }
  catch (error) { message.value = error.message || '比价查询失败' }
}
async function saveQuote() {
  if (!selectedItem.value) return
  busy.value = true
  try {
    await addMarketQuote({ itemId: selectedItem.value.itemId, ...quote })
    await showComparison(selectedItem.value)
    message.value = '报价已保存；请核对来源、规格和起订量。'
  } catch (error) { message.value = error.message || '报价保存失败' } finally { busy.value = false }
}
onMounted(() => refreshWatches().catch(error => { message.value = error.message || '监控列表加载失败' }))
</script>

<style scoped>
.market-row { display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #e5e7eb }
.market-row a { color:#0d6bff;overflow:hidden;text-overflow:ellipsis }
.market-row b { white-space:nowrap }
@media (max-width:800px) { .market-row { flex-wrap:wrap } }
</style>
