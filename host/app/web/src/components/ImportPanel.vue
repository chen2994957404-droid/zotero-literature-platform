<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['open'])
const text = ref('')
const msg = ref('')
const error = ref('')
const have = ref([])
const st = ref(null)
const sending = ref(false)
let timer = null

// 贴进来的文字里大概有几个 DOI（只是给人看个数，真正认 DOI 在后台）
const nGuess = computed(() => new Set((text.value.match(/10\.\d{4,9}\/[^\s"'<>，。；、）]+/g) || []).map((s) => s.toLowerCase())).size)

// 结果码 → 给人看的状态（why 是后台给的中文原因）
const CODE = {
  OK: ['✓', '已收进库', 'ok'],
  PARSE_PENDING: ['…', '正文到手，还在解析', 'wait'],
  CAPTCHA_REQUIRED: ['!', '撞上人机验证：去主力机上「取全文用的浏览器」点一下，再点下面的「重试」', 'warn'],
  NETWORK_ERROR: ['!', '网络或浏览器出了问题，可以重试', 'warn'],
  NOT_SUBSCRIBED: ['×', '学校没订这本', 'bad'],
  NOT_FOUND: ['×', '找不到这篇（DOI 可能写错了）', 'bad'],
  NO_PDF_LINK: ['×', '页面上找不到 PDF', 'bad'],
  NOT_PDF: ['×', '取回来的不是 PDF', 'bad'],
  PARSE_FAILED: ['×', '正文到手了，但解析失败', 'bad'],
}
const show = (r) => CODE[r.code] || [r.ok ? '✓' : '×', r.code || '', r.ok ? 'ok' : 'bad']
const retryable = computed(() => (st.value?.retryable || []))
const running = computed(() => st.value && !st.value.done && st.value.total > 0)

async function refresh() {
  try {
    st.value = await api.importStatus()
  } catch (e) {
    /* 刷新失败不打扰，下一轮再试 */
  }
  clearTimeout(timer)
  if (running.value || st.value?.upgrading) timer = setTimeout(refresh, 5000)
}

async function submit(body) {
  sending.value = true
  error.value = msg.value = ''
  try {
    const r = await api.importDois(body)
    have.value = r.have || []
    msg.value = r.text + (r.rejected?.length ? `；${r.rejected.length} 篇 DOI 无效：${r.rejected.map((x) => x.doi).join('、')}` : '')
    if (r.submitted?.length) text.value = ''
    refresh()
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    sending.value = false
  }
}

onMounted(refresh)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <section class="imp">
    <h2>导入文献</h2>
    <p class="muted small">
      贴 DOI 进来（一行一个，或者直接贴参考文献、doi.org 链接，平台自己挑出 DOI）。主力机上的「取全文用的浏览器」会用学校订阅去取正文和 SI，收进库并解析。
      <br />一次最多 25 篇，每篇之间隔 20 秒（太快会被出版商封掉整个学校的 IP），一篇大约一分钟。
    </p>
    <textarea v-model="text" rows="8" placeholder="10.1021/acs.macromol.5b01234&#10;https://doi.org/10.1002/adfm.202411821&#10;……"></textarea>
    <div class="row">
      <button class="primary" :disabled="sending || running || !text.trim()" @click="submit({ text })">
        {{ sending ? '提交中……' : '导入' }}<template v-if="nGuess && !sending">（{{ nGuess }} 篇）</template>
      </button>
      <span v-if="running" class="muted small">上一批还在取，等它跑完再导入</span>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="small">{{ msg }}</p>

    <template v-if="have.length">
      <h3>库里已经有的（不再取）</h3>
      <ul class="list">
        <li v-for="h in have" :key="h.doi"><span class="mark ok">✓</span><a href="#" @click.prevent="emit('open', h.id)">{{ h.doi }}</a></li>
      </ul>
    </template>

    <template v-if="st && st.total">
      <h3>
        最近一批：{{ st.finished }}/{{ st.total }} 篇
        <span class="muted small">{{ running ? '还在取……' : st.upgrading ? '取完了，后台还在补解析' : '完成' }}</span>
      </h3>
      <p v-if="running && st.current" class="muted small">
        正在处理 {{ st.current.doi }}<template v-if="st.current.for_s">（{{ st.current.for_s }} 秒）</template>
      </p>
      <p v-if="st.stalled" class="error small">{{ st.stalled_hint }}</p>
      <ul class="list">
        <li v-for="r in st.results" :key="r.doi">
          <span class="mark" :class="show(r)[2]">{{ show(r)[0] }}</span>
          <a v-if="r.id && r.ok" href="#" @click.prevent="emit('open', r.id)">{{ r.doi }}</a>
          <span v-else>{{ r.doi }}</span>
          <span class="muted small">{{ show(r)[1] }}<template v-if="r.ok && r.si"> · 有 SI</template></span>
          <div v-if="!r.ok && r.why" class="muted small why">{{ r.why }}</div>
        </li>
      </ul>
      <button v-if="!running && retryable.length" :disabled="sending" @click="submit({ dois: retryable })">重试没取到的 {{ retryable.length }} 篇</button>
    </template>
  </section>
</template>

<style scoped>
.imp { max-width: 820px; margin: 0 auto; padding: 16px 20px 40px; }
h2 { font-size: 18px; margin: 4px 0 8px; }
h3 { font-size: 14px; margin: 22px 0 8px; }
textarea { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--text); font: 13px/1.5 ui-monospace, Consolas, monospace; resize: vertical; }
.row { display: flex; gap: 12px; align-items: center; margin-top: 10px; }
button { padding: 7px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--text); cursor: pointer; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button:disabled { opacity: .5; cursor: default; }
.list { list-style: none; margin: 0 0 12px; padding: 0; }
.list li { padding: 6px 0; border-bottom: 1px solid var(--line); display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; word-break: break-all; }
.list a { color: var(--accent); }
.why { flex-basis: 100%; padding-left: 26px; }
.mark { display: inline-block; width: 16px; text-align: center; font-weight: 700; }
.mark.ok { color: var(--ok); }
.mark.wait { color: var(--muted); }
.mark.warn { color: var(--warn); }
.mark.bad { color: #c0392b; }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.error { color: #c0392b; }
</style>
