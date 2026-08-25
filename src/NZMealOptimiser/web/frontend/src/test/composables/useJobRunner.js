import { computed, reactive, ref } from 'vue';

const POLL_MS = 700;

function clockNow() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function formatElapsed(seconds) {
  const sec = Math.max(0, seconds || 0);
  if (sec < 60) return `${sec.toFixed(1)}s`;
  return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;
}

// Live job state shared by both dashboards: POST /optimise/jobs + cursor-based
// GET /optimise/{id} polling, plus the boot-time console feed.
export function useJobRunner() {
  const job = reactive({ id: null, status: 'idle', phase: '', companies: [], events: [], total_tasks: 0, done_tasks: 0, products_found: 0, error_detail: '', elapsed: 0 });
  const result = ref(null);
  const loading = ref(false);
  const error = ref('');
  const feed = ref([]);
  let feedSeq = 0;
  let cursor = -1;
  let pollTimer = null;
  let tickTimer = null;
  let pollRun = 0;

  function logLine(kind, co, text) {
    feed.value.push({ key: `feed-${++feedSeq}`, boot: true, time: clockNow(), kind, co, text });
  }

  const jobVisible = computed(() => job.status !== 'idle');
  const jobRunning = computed(() => job.status === 'queued' || job.status === 'running');
  const overallPct = computed(() => (job.total_tasks ? Math.round((job.done_tasks / job.total_tasks) * 100) : 0));
  const elapsedDisplay = computed(() => formatElapsed(job.elapsed));
  const terminalTitle = computed(() => (job.events.length ? `${job.events.length} events` : 'standby'));
  const consoleLines = computed(() => [...feed.value, ...job.events.map((event) => ({ ...event, key: `ev-${event.i}` }))]);

  function stopTimers() {
    clearTimeout(pollTimer);
    clearInterval(tickTimer);
    tickTimer = null;
  }

  function reset() {
    stopTimers();
    result.value = null;
    Object.assign(job, { id: null, status: 'idle', phase: '', companies: [], events: [], total_tasks: 0, done_tasks: 0, products_found: 0, error_detail: '', elapsed: 0 });
    cursor = -1;
  }

  async function start(payload) {
    error.value = '';
    result.value = null;
    stopTimers();
    Object.assign(job, { id: null, status: 'queued', phase: 'Queuing…', companies: [], events: [], total_tasks: 0, done_tasks: 0, products_found: 0, error_detail: '', elapsed: 0 });
    cursor = -1;
    loading.value = true;
    const run = ++pollRun;
    try {
      const response = await fetch('/optimise/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not start the optimisation');
      job.id = data.job_id;
      tickTimer = setInterval(() => { if (jobRunning.value) job.elapsed += 0.25; }, 250);
      poll(run);
    } catch (err) {
      error.value = err.message;
      loading.value = false;
      job.status = 'idle';
    }
  }

  async function poll(run) {
    if (!job.id || run !== pollRun) return;
    try {
      const response = await fetch(`/optimise/${job.id}?events_since=${cursor}`);
      if (!response.ok) throw new Error(`Poll failed (${response.status})`);
      applySnapshot(await response.json());
      if (job.status === 'complete' || job.status === 'error') { finishJob(); return; }
    } catch { /* transient network hiccup — keep polling */ }
    if (run === pollRun) pollTimer = setTimeout(() => poll(run), POLL_MS);
  }

  function applySnapshot(d) {
    job.status = d.status;
    job.phase = d.phase;
    job.total_tasks = d.total_tasks;
    job.done_tasks = d.done_tasks;
    job.products_found = d.products_found;
    job.elapsed = Math.max(job.elapsed, d.elapsed_seconds || 0);
    if (d.companies.length) job.companies = d.companies;
    if (d.events && d.events.length) { job.events.push(...d.events); cursor = d.next_cursor; }
    if (d.status === 'error') job.error_detail = d.error_detail || '';
    if (d.result) result.value = d.result;
  }

  function finishJob() {
    stopTimers();
    loading.value = false;
    if (job.status === 'error') error.value = job.error_detail || 'The optimisation failed';
  }

  return { job, result, loading, error, feed, logLine, start, reset, stopTimers, jobVisible, jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines };
}
