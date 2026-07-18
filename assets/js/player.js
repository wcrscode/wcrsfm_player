(() => {
  const STREAM_URL = 'https://archive.radio614.org:8001/wcrs_backup';
  const STATUS_URL = 'https://archive.radio614.org:8001/status-json.xsl';
  const POLL_MS    = 2 * 60 * 1000;

  const audio     = document.getElementById('audio');
  const toggle    = document.getElementById('toggle');
  const iconPlay  = document.getElementById('icon-play');
  const iconPause = document.getElementById('icon-pause');
  const nowEl     = document.getElementById('nowplaying');

  function setUI(playing) {
    iconPlay.style.display  = playing ? 'none' : '';
    iconPause.style.display = playing ? '' : 'none';
    toggle.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  }

  toggle.addEventListener('click', async () => {
    if (audio.paused) {
      audio.src = STREAM_URL + '?t=' + Date.now();
      toggle.disabled = true;
      try { await audio.play(); } catch (e) { console.error(e); }
      toggle.disabled = false;
    } else {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      setUI(false);
    }
  });

  audio.addEventListener('playing', () => setUI(true));
  audio.addEventListener('pause',   () => setUI(false));
  audio.addEventListener('ended',   () => setUI(false));
  audio.addEventListener('error',   () => { setUI(false); toggle.disabled = false; });

  async function refreshNowPlaying() {
    try {
      const r = await fetch(STATUS_URL, { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      let sources = data.icestats && data.icestats.source;
      if (!sources) return;
      if (!Array.isArray(sources)) sources = [sources];
      const mount = sources.find(s => (s.listenurl || '').endsWith('/wcrs_backup')) || sources[0];
      const title = mount.title || mount.yp_currently_playing || mount.server_name || '';
      nowEl.textContent = title || '—';
      nowEl.title = title;
    } catch (e) {
      console.warn('now playing fetch failed', e);
    }
  }
  refreshNowPlaying();
  setInterval(refreshNowPlaying, POLL_MS);

  // Same-origin links swap #content via fetch so the <audio> element survives.
  document.addEventListener('click', async (ev) => {
    const a = ev.target.closest('a[href]');
    if (!a) return;
    if (a.target && a.target !== '_self') return;
    if (a.hasAttribute('download')) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return;
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;

    // Same-page hash link — let the browser handle the anchor jump.
    if (url.pathname === location.pathname && url.hash) return;

    ev.preventDefault();
    await loadInto(url.href, true);
  });

  window.addEventListener('popstate', () => loadInto(location.href, false));

  // --- Mobile nav toggle ------------------------------------------------
  const header = document.getElementById('site-header');
  const navToggle = document.getElementById('nav-toggle');
  if (navToggle && header) {
    const setOpen = (open) => {
      header.classList.toggle('nav-open', open);
      navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    navToggle.addEventListener('click', () => {
      setOpen(navToggle.getAttribute('aria-expanded') !== 'true');
    });
    // Close on nav link click (covers both SPA-loaded and external links)
    document.querySelectorAll('.site-nav a').forEach(a => {
      a.addEventListener('click', () => setOpen(false));
    });
  }

  function updateNavHighlight() {
    const here = location.pathname.replace(/index\.html$/, '') || '/';
    document.querySelectorAll('.site-nav a').forEach(a => {
      const url = new URL(a.href, location.href).pathname;
      if (url === here) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
  }

  // --- Schedule (upcoming widget + tabbed full page) --------------------
  const DAY_NAMES  = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  // Returns the current {dayIdx, minutes} in America/New_York regardless of
  // where the viewer's browser thinks it is.
  function nowInEastern() {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(new Date());
    const wd = {Sun:0,Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6}[
      parts.find(p => p.type === 'weekday').value
    ];
    const hh = parseInt(parts.find(p => p.type === 'hour').value, 10) % 24;
    const mm = parseInt(parts.find(p => p.type === 'minute').value, 10);
    return { dayIdx: wd, minutes: hh * 60 + mm };
  }

  const today = () => DAY_NAMES[nowInEastern().dayIdx];

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    })[c]);
  }

  function renderUpcoming(root) {
    const nowListEl  = root.querySelector('[data-upcoming-now]');
    const nextListEl = root.querySelector('[data-upcoming-next]');
    const dataEl     = root.querySelector('[data-upcoming-data]');
    if (!dataEl || (!nowListEl && !nextListEl)) return;

    let data;
    try { data = JSON.parse(dataEl.textContent); }
    catch (e) { return; }

    const flat = [];
    for (let i = 0; i < 7; i++) {
      const shows = data[DAY_NAMES[i]] || [];
      for (const s of shows) {
        const [h, m] = (s.start || '00:00').split(':').map(Number);
        flat.push({ ...s, dayIdx: i, weekMinute: i * 1440 + h * 60 + m });
      }
    }
    if (!flat.length) return;
    flat.sort((a, b) => a.weekMinute - b.weekMinute);

    const now = nowInEastern();
    const nowWeekMinute = now.dayIdx * 1440 + now.minutes;

    // Find last show whose start <= now. If none (all start later this week),
    // wrap to the final show of the previous cycle.
    let currentIdx = -1;
    for (let i = 0; i < flat.length; i++) {
      if (flat[i].weekMinute <= nowWeekMinute) currentIdx = i;
      else break;
    }
    if (currentIdx < 0) currentIdx = flat.length - 1;

    const upcoming = [];
    for (let i = 0; i < 4 && i < flat.length; i++) {
      upcoming.push(flat[(currentIdx + i) % flat.length]);
    }

    const nameHtml = (s) => s.program_slug
      ? `<a href="/programs/${encodeURIComponent(s.program_slug)}/">${escapeHtml(s.name)}</a>`
      : escapeHtml(s.name);

    if (nowListEl && upcoming[0]) {
      nowListEl.innerHTML = `
        <div class="upcoming-item">
          <div class="upcoming-line"><span class="upcoming-name">${nameHtml(upcoming[0])}</span></div>
        </div>`;
    }

    if (nextListEl) {
      nextListEl.innerHTML = upcoming.slice(1).map(s => `
        <div class="upcoming-item" role="listitem">
          <div class="upcoming-line"><span class="upcoming-when">${s.start_display}</span> <span class="upcoming-sep">—</span> <span class="upcoming-name">${nameHtml(s)}</span></div>
        </div>`).join('');
    }
  }

  function initProgramFilter() {
    const filter = document.querySelector('.type-filter');
    if (!filter || filter.dataset.wired === '1') return;
    filter.dataset.wired = '1';
    const btns     = Array.from(filter.querySelectorAll('.type-filter-btn'));
    const items    = Array.from(document.querySelectorAll('.program-item'));
    const sections = Array.from(document.querySelectorAll('.alpha-section'));
    const navLinks = Array.from(document.querySelectorAll('.alpha-nav a'));
    const apply = (kind) => {
      btns.forEach(b => b.setAttribute('aria-pressed',
        b.dataset.filter === kind ? 'true' : 'false'));
      items.forEach(li => {
        li.hidden = kind !== 'all' && li.dataset.type !== kind;
      });
      sections.forEach(sec => {
        const anyVisible = Array.from(sec.querySelectorAll('.program-item'))
          .some(li => !li.hidden);
        sec.hidden = !anyVisible;
      });
      navLinks.forEach(a => {
        const id = (a.getAttribute('href') || '').slice(1);
        const target = id && document.getElementById(id);
        const off = !target || target.hidden;
        a.classList.toggle('is-off', off);
        if (off) a.setAttribute('aria-disabled', 'true');
        else     a.removeAttribute('aria-disabled');
      });
    };
    btns.forEach(b => b.addEventListener('click', () => apply(b.dataset.filter)));
  }

  function initSchedule() {
    document.querySelectorAll('[data-upcoming-schedule]').forEach(renderUpcoming);

    // Full schedule page — tabbed switcher, default to today (Eastern).
    // Implements the WAI-ARIA tabs pattern with roving tabindex and
    // Left/Right/Home/End keyboard navigation.
    document.querySelectorAll('[data-schedule]').forEach(root => {
      const tabs   = Array.from(root.querySelectorAll('[data-day-tab]'));
      const panels = root.querySelectorAll('[data-day-panel]');
      const show = (day, focus = false) => {
        tabs.forEach(t => {
          const selected = t.dataset.dayTab === day;
          t.setAttribute('aria-selected', selected ? 'true' : 'false');
          t.setAttribute('tabindex', selected ? '0' : '-1');
          if (selected && focus) t.focus();
        });
        panels.forEach(p => { p.hidden = p.dataset.dayPanel !== day; });
      };
      tabs.forEach(t =>
        t.addEventListener('click', () => show(t.dataset.dayTab)));
      root.querySelector('[role="tablist"]')?.addEventListener('keydown', (e) => {
        const currentIdx = tabs.findIndex(t => t.getAttribute('aria-selected') === 'true');
        if (currentIdx < 0) return;
        let nextIdx = null;
        if (e.key === 'ArrowRight') nextIdx = (currentIdx + 1) % tabs.length;
        else if (e.key === 'ArrowLeft') nextIdx = (currentIdx - 1 + tabs.length) % tabs.length;
        else if (e.key === 'Home') nextIdx = 0;
        else if (e.key === 'End')  nextIdx = tabs.length - 1;
        if (nextIdx === null) return;
        e.preventDefault();
        show(tabs[nextIdx].dataset.dayTab, true);
      });
      show(today());
    });
  }
  initSchedule();
  initProgramFilter();

  // --- Contact form ------------------------------------------------------
  function initContactForm() {
    const form        = document.getElementById('contactForm');
    if (!form || form.dataset.wired === '1') return;
    form.dataset.wired = '1';

    const submitBtn   = document.getElementById('contactSubmitBtn');
    const messageEl   = document.getElementById('contactMessage');
    const charCountEl = document.getElementById('charCount');
    const loadTimeEl  = document.getElementById('formLoadTime');

    const modal        = document.getElementById('contactModal');
    const modalTitle   = document.getElementById('contactModalTitle');
    const modalMsg     = document.getElementById('contactModalMsg');
    const modalDismiss = document.getElementById('contactModalDismiss');

    if (loadTimeEl) loadTimeEl.value = Math.floor(Date.now() / 1000);
    if (messageEl && charCountEl) {
      messageEl.addEventListener('input', () => {
        charCountEl.textContent = messageEl.value.length;
      });
    }

    const openModal = (success, message) => {
      if (!modal) return alert(message);
      modalTitle.textContent = success ? 'Message sent' : 'Sending failed';
      modalMsg.textContent   = message;
      modal.classList.toggle('is-success', success);
      modal.classList.toggle('is-error', !success);
      modal.showModal();
    };
    if (modal && modalDismiss) {
      modalDismiss.addEventListener('click', () => modal.close());
      // Click outside the panel (on the ::backdrop) also closes.
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.close();
      });
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name    = form.querySelector('#contactName').value.trim();
      const email   = form.querySelector('#contactEmail').value.trim();
      const message = form.querySelector('#contactMessage').value.trim();
      if (!name || !email || !message) {
        openModal(false, 'Please fill in all required fields.');
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending…';
      try {
        const r = await fetch('/contact.php', {
          method: 'POST',
          body: new FormData(form),
        });
        const data = await r.json();
        openModal(data.success, data.message);
        if (data.success) {
          form.reset();
          if (charCountEl) charCountEl.textContent = '0';
          if (loadTimeEl)  loadTimeEl.value = Math.floor(Date.now() / 1000);
        }
      } catch (err) {
        openModal(false, 'Something went wrong. Please try again.');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Send Message';
      }
    });
  }
  initContactForm();

  async function loadInto(href, push) {
    try {
      const r = await fetch(href);
      if (!r.ok) throw new Error(r.status);
      const html = await r.text();
      const doc  = new DOMParser().parseFromString(html, 'text/html');
      const next = doc.querySelector('#content');
      if (!next) { location.href = href; return; }
      document.getElementById('content').replaceWith(next);
      if (doc.title) document.title = doc.title;
      if (push) history.pushState({}, '', href);
      updateNavHighlight();
      initSchedule();
      initProgramFilter();
      initContactForm();
      const hash = new URL(href, location.href).hash;
      if (hash) {
        const target = document.querySelector(hash);
        if (target) { target.scrollIntoView(); return; }
      }
      window.scrollTo(0, 0);
    } catch (e) {
      location.href = href;
    }
  }
})();
