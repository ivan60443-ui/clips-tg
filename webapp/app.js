/* Клипы — Mini App */
(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor("#0A0A0B"); tg.setBackgroundColor("#0A0A0B"); } catch (e) {}
  }

  const params = new URLSearchParams(location.search);
  const devUid = params.get("uid") || "";
  const startParam = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || params.get("startapp") || "";

  const state = {
    me: null,
    prices: { boost_stars: 25, boost_hours: 24, gifts: [] },
    bot: { username: "", upload_url: "", app_name: "Клипы" },
    tab: "for_you",
    items: [],
    screen: "feed",
    muted: true,
    currentId: null,
    profile: null,
    viewingUser: null,
  };

  const $ = (id) => document.getElementById(id);
  const feedEl = $("feed");
  const toastEl = $("toast");
  let toastT;

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.remove("hidden");
    clearTimeout(toastT);
    toastT = setTimeout(() => toastEl.classList.add("hidden"), 2400);
  }

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (tg && tg.initData) h["X-Init-Data"] = tg.initData;
    else if (devUid) h["X-Dev-User"] = devUid;
    return h;
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { ...headers(), ...(opts.headers || {}) },
    });
    let data = {};
    try { data = await res.json(); } catch (e) { data = { error: "bad json" }; }
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || data.detail || "Ошибка");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function fmt(n) {
    n = Number(n) || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 10000) return Math.round(n / 1000) + "K";
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "K";
    return String(n);
  }

  function initials(name) {
    const p = (name || "?").trim().split(/\s+/);
    return ((p[0] || "?").charAt(0) + (p[1] ? p[1].charAt(0) : "")).toUpperCase();
  }

  function avaHtml(user, cls = "ava") {
    const src = user.photo || "";
    if (src) return `<div class="${cls}"><img src="${esc(src)}" alt=""></div>`;
    return `<div class="${cls}">${esc(initials(user.name))}</div>`;
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function timeAgo(ts) {
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 60) return "только что";
    if (s < 3600) return Math.floor(s / 60) + " мин назад";
    if (s < 86400) return Math.floor(s / 3600) + " ч назад";
    return Math.floor(s / 86400) + " дн назад";
  }

  function heartSvg() {
    return `<svg width="26" height="26" viewBox="0 0 24 24"><path fill="currentColor" d="M12 21s-6.7-4.35-9.33-8.1C.8 10.2 1.1 6.9 3.6 5.2c2-1.4 4.7-1 6.4.8L12 8l2-2c1.7-1.8 4.4-2.2 6.4-.8 2.5 1.7 2.8 5 1 7.7C18.7 16.65 12 21 12 21z"/></svg>`;
  }
  function chatSvg() {
    return `<svg width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M4 4h16v12H7l-3 3V4z"/></svg>`;
  }
  function shareSvg() {
    return `<svg width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M14 5l7 7-7 7v-4H8a6 6 0 0 0-6 6v-2a8 8 0 0 1 8-8h4V5z"/></svg>`;
  }
  function giftSvg() {
    return `<svg width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M20 7h-2.2A3 3 0 0 0 12 4.8 3 3 0 0 0 6.2 7H4v4h8V9h0v2h8V7zM4 13v7h7v-7H4zm9 0v7h7v-7h-7zM9 7a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm6 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>`;
  }

  function renderFeed(items, { append = false } = {}) {
    if (!append) feedEl.innerHTML = "";
    const empty = $("empty");
    if (!append && (!items || !items.length)) {
      empty.classList.remove("hidden");
      const following = state.tab === "following";
      $("empty-title").textContent = following ? "Подписок пока нет" : "Пока тихо";
      $("empty-text").textContent = following
        ? "Подпишись на авторов в рекомендациях — их ролики появятся здесь."
        : "Пришли видео боту в личку — и оно появится здесь.";
      return;
    }
    empty.classList.add("hidden");
    const frag = document.createDocumentFragment();
    for (const it of items) frag.appendChild(slideEl(it));
    feedEl.appendChild(frag);
    requestAnimationFrame(() => {
      playVisible();
      preloadAround();
    });
  }

  function slideEl(it) {
    const el = document.createElement("article");
    el.className = "slide";
    el.dataset.id = it.id;
    const followed = it.author && it.author.followed;
    const isMe = state.me && it.author && it.author.id === state.me.id;
    el.innerHTML = `
      <video playsinline webkit-playsinline loop muted preload="metadata" poster="${esc(it.thumb || "")}" src="${esc(it.src)}"></video>
      <div class="grad"></div>
      <div class="heart-burst">❤</div>
      <div class="mute-badge ${state.muted ? "show" : ""}">🔇</div>
      <div class="pause-badge">⏸</div>
      <div class="meta">
        <div class="author-row">
          ${avaHtml(it.author)}
          <div>
            <div class="author-name" data-open-user="${it.author.id}">
              ${esc(it.author.name)}${it.author.username ? `<span class="at">@${esc(it.author.username)}</span>` : ""}
            </div>
          </div>
          ${isMe ? "" : `<button class="follow-btn ${followed ? "on" : ""}" data-follow="${it.author.id}">${followed ? "Подписка" : "Подписаться"}</button>`}
        </div>
        <div class="caption">${esc(it.caption)}</div>
        ${it.boosted ? `<div class="boost-pill">🚀 В рекомендациях</div>` : ""}
      </div>
      <div class="actions">
        <button class="act like ${it.liked ? "liked" : ""}" data-like="${it.id}">
          <span class="icon">${heartSvg()}</span><span class="cnt">${fmt(it.likes)}</span>
        </button>
        <button class="act" data-comments="${it.id}">
          <span class="icon">${chatSvg()}</span><span class="cnt">${fmt(it.comments)}</span>
        </button>
        <button class="act" data-gift="${it.id}">
          <span class="icon">${giftSvg()}</span><span class="cnt">${fmt(it.gifts)}</span>
        </button>
        <button class="act" data-share="${it.id}">
          <span class="icon">${shareSvg()}</span><span class="cnt">Шер</span>
        </button>
        <button class="act" data-more="${it.id}">
          <span class="icon">···</span><span class="cnt"></span>
        </button>
      </div>
    `;
    bindSlide(el, it);
    return el;
  }

  function bindSlide(el, it) {
    const video = el.querySelector("video");
    video.muted = state.muted;
    const muteBadge = el.querySelector(".mute-badge");
    const pauseBadge = el.querySelector(".pause-badge");
    let lastTap = 0;

    const hit = (e) => {
      const now = Date.now();
      if (now - lastTap < 280) {
        lastTap = 0;
        like(it.id, el, true);
        return;
      }
      lastTap = now;
      setTimeout(() => {
        if (Date.now() - lastTap < 280) return;
        if (state.muted) {
          state.muted = false;
          applyMute();
          muteBadge.classList.remove("show");
          if (video.paused) video.play().catch(() => {});
        } else if (!video.paused) {
          video.pause();
          pauseBadge.classList.add("show");
        } else {
          video.play().catch(() => {});
          pauseBadge.classList.remove("show");
        }
      }, 280);
    };
    el.querySelector("video").addEventListener("click", hit);

    el.querySelector("[data-like]")?.addEventListener("click", (e) => { e.stopPropagation(); like(it.id, el, !it.liked); });
    el.querySelector("[data-comments]")?.addEventListener("click", (e) => { e.stopPropagation(); openComments(it.id); });
    el.querySelector("[data-share]")?.addEventListener("click", (e) => { e.stopPropagation(); share(it); });
    el.querySelector("[data-gift]")?.addEventListener("click", (e) => { e.stopPropagation(); openGifts(it); });
    el.querySelector("[data-more]")?.addEventListener("click", (e) => { e.stopPropagation(); openMore(it); });
    el.querySelector("[data-follow]")?.addEventListener("click", (e) => { e.stopPropagation(); follow(it.author.id, e.currentTarget, it); });
    el.querySelector("[data-open-user]")?.addEventListener("click", (e) => { e.stopPropagation(); openProfile(it.author.id); });
  }

  function applyMute() {
    feedEl.querySelectorAll("video").forEach((v) => { v.muted = state.muted; });
    feedEl.querySelectorAll(".mute-badge").forEach((b) => b.classList.toggle("show", state.muted));
  }

  function playVisible() {
    const slides = [...feedEl.querySelectorAll(".slide")];
    let best = null, bestRatio = 0;
    const root = feedEl.getBoundingClientRect();
    for (const s of slides) {
      const r = s.getBoundingClientRect();
      const vis = Math.min(r.bottom, root.bottom) - Math.max(r.top, root.top);
      const ratio = vis / (root.height || 1);
      if (ratio > bestRatio) { bestRatio = ratio; best = s; }
    }
    for (const s of slides) {
      const v = s.querySelector("video");
      if (!v) continue;
      if (s === best && bestRatio > 0.6) {
        v.muted = state.muted;
        const p = v.play();
        if (p) p.catch(() => {});
        const id = Number(s.dataset.id);
        if (state.currentId !== id) {
          state.currentId = id;
          api(`/api/video/${id}/view`, { method: "POST" }).then((r) => {
            const it = state.items.find((x) => x.id === id);
            if (it) it.views = r.views;
          }).catch(() => {});
        }
      } else {
        v.pause();
      }
    }
  }

  function preloadAround() {
    const slides = [...feedEl.querySelectorAll(".slide")];
    const idx = slides.findIndex((s) => Number(s.dataset.id) === state.currentId);
    [idx + 1, idx + 2].forEach((i) => {
      const v = slides[i] && slides[i].querySelector("video");
      if (v) v.preload = "auto";
    });
  }

  let viewTick;
  feedEl.addEventListener("scroll", () => {
    clearTimeout(viewTick);
    viewTick = setTimeout(() => { playVisible(); preloadAround(); }, 80);
  }, { passive: true });

  async function like(id, el, wantBurst) {
    try {
      const r = await api(`/api/video/${id}/like`, { method: "POST" });
      const it = state.items.find((x) => x.id === id);
      if (it) { it.liked = r.liked; it.likes = r.likes; }
      const btn = el.querySelector("[data-like]");
      btn.classList.toggle("liked", r.liked);
      btn.querySelector(".cnt").textContent = fmt(r.likes);
      if (r.liked && wantBurst) {
        const burst = el.querySelector(".heart-burst");
        burst.classList.remove("go");
        void burst.offsetWidth;
        burst.classList.add("go");
        if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
      }
    } catch (e) { toast(e.message); }
  }

  async function follow(uid, btn, it) {
    try {
      const r = await api(`/api/users/${uid}/follow`, { method: "POST" });
      if (btn) {
        btn.classList.toggle("on", r.followed);
        btn.textContent = r.followed ? "Подписка" : "Подписаться";
      }
      state.items.forEach((x) => {
        if (x.author && x.author.id === uid) x.author.followed = r.followed;
      });
      feedEl.querySelectorAll(`[data-follow="${uid}"]`).forEach((b) => {
        b.classList.toggle("on", r.followed);
        b.textContent = r.followed ? "Подписка" : "Подписаться";
      });
      if (state.profile && state.profile.user.id === uid) {
        state.profile.user.followed = r.followed;
        state.profile.user.followers = r.followers;
      }
    } catch (e) { toast(e.message); }
  }

  function share(it) {
    const link = it.share || "";
    const q = String(it.id);
    if (tg && tg.switchInlineQuery) {
      try { tg.switchInlineQuery(q, ["users", "groups", "channels"]); return; } catch (e) {}
    }
    if (tg && tg.openTelegramLink && link.startsWith("https://t.me/")) {
      tg.openTelegramLink(link);
      return;
    }
    if (navigator.share) {
      navigator.share({ title: "Клипы", text: it.caption || "Ролик", url: link }).catch(() => copy(link));
    } else copy(link);
  }

  function copy(text) {
    if (!text) return toast("Ссылка ещё не готова");
    navigator.clipboard.writeText(text).then(() => toast("Ссылка скопирована")).catch(() => toast(text));
  }

  function openInvoice(url) {
    if (!url) { toast("Счёт отправлен в чат с ботом"); return; }
    if (tg && tg.openInvoice) {
      tg.openInvoice(url, (st) => {
        if (st === "paid") toast("Оплата прошла ✨");
        else if (st === "cancelled") toast("Отменено");
      });
    } else if (tg && tg.openTelegramLink) {
      tg.openTelegramLink(url);
    } else {
      location.href = url;
    }
  }

  /* ----- sheets ----- */
  const sheet = $("sheet");
  const sheetBody = $("sheet-body");
  const sheetTitle = $("sheet-title");

  function openSheet(title, html) {
    sheetTitle.textContent = title;
    sheetBody.innerHTML = "";
    if (typeof html === "string") sheetBody.innerHTML = html;
    else sheetBody.appendChild(html);
    sheet.classList.remove("hidden");
    sheet.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => sheet.classList.add("open"));
  }
  function closeSheet() {
    sheet.classList.remove("open");
    setTimeout(() => { sheet.classList.add("hidden"); sheet.setAttribute("aria-hidden", "true"); }, 250);
  }
  $("sheet-close").onclick = closeSheet;
  $("sheet-backdrop").onclick = closeSheet;

  async function openComments(id) {
    const wrap = document.createElement("div");
    wrap.innerHTML = `<div class="clist" id="clist">Загрузка…</div>
      <form class="composer" id="cform">
        <input name="text" maxlength="500" placeholder="Напиши комментарий…" autocomplete="off" />
        <button type="submit">Отпр.</button>
      </form>`;
    openSheet("Комментарии", wrap);
    try {
      const r = await api(`/api/video/${id}/comments`);
      drawComments(wrap.querySelector("#clist"), r.items || []);
    } catch (e) {
      wrap.querySelector("#clist").textContent = e.message;
    }
    wrap.querySelector("#cform").onsubmit = async (ev) => {
      ev.preventDefault();
      const input = ev.target.text;
      const text = input.value.trim();
      if (!text) return;
      try {
        const r = await api(`/api/video/${id}/comments`, { method: "POST", body: JSON.stringify({ text }) });
        input.value = "";
        const list = wrap.querySelector("#clist");
        if (list.dataset.empty) list.innerHTML = "";
        list.dataset.empty = "";
        list.prepend(commentItem(r));
        const it = state.items.find((x) => x.id === id);
        if (it) it.comments = r.comments;
        const cnt = feedEl.querySelector(`[data-comments="${id}"] .cnt`);
        if (cnt) cnt.textContent = fmt(r.comments);
      } catch (e) { toast(e.message); }
    };
  }

  function drawComments(list, items) {
    list.innerHTML = "";
    if (!items.length) {
      list.dataset.empty = "1";
      list.innerHTML = `<div class="grid-empty">Напиши первый комментарий</div>`;
      return;
    }
    items.forEach((c) => list.appendChild(commentItem(c)));
  }

  function commentItem(c) {
    const d = document.createElement("div");
    d.className = "citem";
    d.innerHTML = `${avaHtml(c.author)}
      <div class="cbody">
        <div class="nm">${esc(c.author.name)}</div>
        <div class="tx">${esc(c.text)}</div>
        <div class="tm">${timeAgo(c.created_at)}</div>
      </div>`;
    return d;
  }

  function openGifts(it) {
    const gifts = (state.prices.gifts || []);
    const box = document.createElement("div");
    box.innerHTML = `<p style="color:var(--mute);margin:0 0 8px">Подарок автору за Telegram Stars. Деньги идут через Telegram, мы только записываем перевод.</p>
      <div class="gift-grid"></div>`;
    const grid = box.querySelector(".gift-grid");
    for (const g of gifts) {
      const b = document.createElement("div");
      b.className = "gift-card";
      b.innerHTML = `<span class="em">${g.emoji}</span><div class="tt">${esc(g.title)}</div>
        <div class="st">${g.stars} ⭐</div><button class="btn primary" style="width:100%;padding:10px">Подарить</button>`;
      b.querySelector("button").onclick = async () => {
        try {
          const r = await api(`/api/video/${it.id}/gift`, { method: "POST", body: JSON.stringify({ gift_id: g.id }) });
          if (r.dev) { toast("Подарок отправлен (демо)"); closeSheet(); }
          else openInvoice(r.invoice_url);
        } catch (e) { toast(e.message); }
      };
      grid.appendChild(b);
    }
    openSheet("Подарок автору", box);
  }

  function openMore(it) {
    const isMe = state.me && it.author && it.author.id === state.me.id;
    const isAdmin = state.me && state.me.is_admin;
    const box = document.createElement("div");
    box.className = "more-list";
    const add = (label, cls, fn) => {
      const b = document.createElement("button");
      b.className = cls || "";
      b.textContent = label;
      b.onclick = fn;
      box.appendChild(b);
    };
    if (isMe) {
      add(`Буст в рекомендации · ${state.prices.boost_stars} ⭐ / ${state.prices.boost_hours} ч`, "", async () => {
        try {
          const r = await api(`/api/video/${it.id}/boost`, { method: "POST" });
          if (r.dev) { toast("Буст включён (демо)"); closeSheet(); }
          else openInvoice(r.invoice_url);
        } catch (e) { toast(e.message); }
      });
    }
    add("Пожаловаться", "danger", async () => {
      try {
        await api(`/api/video/${it.id}/report`, { method: "POST", body: JSON.stringify({ reason: "user_report" }) });
        toast("Жалоба отправлена");
        closeSheet();
      } catch (e) { toast(e.message); }
    });
    if (isMe || isAdmin) {
      add("Удалить ролик", "danger", async () => {
        try {
          await api(`/api/video/${it.id}/delete`, { method: "POST" });
          toast("Ролик удалён");
          closeSheet();
          state.items = state.items.filter((x) => x.id !== it.id);
          const el = feedEl.querySelector(`.slide[data-id="${it.id}"]`);
          if (el) el.remove();
        } catch (e) { toast(e.message); }
      });
    }
    openSheet("Ещё", box);
  }

  /* ----- pages ----- */
  function showScreen(name, { userId } = {}) {
    state.screen = name;
    $("page-upload").classList.toggle("hidden", name !== "upload");
    $("page-profile").classList.toggle("hidden", name !== "profile");
    document.querySelectorAll(".dock-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.screen === (name === "profile" ? "profile" : name));
    });
    if (name === "feed") $("nav-feed").classList.add("active");
    if (name === "upload") setupUpload();
    if (name === "profile") loadProfile(userId || (state.me && state.me.id));
  }

  function setupUpload() {
    const a = $("open-bot");
    const url = state.bot.upload_url || (state.bot.username ? `https://t.me/${state.bot.username}?start=upload` : "#");
    a.href = url;
    a.onclick = (e) => {
      if (tg && tg.openTelegramLink && url.startsWith("https://t.me/")) {
        e.preventDefault();
        tg.openTelegramLink(url);
      }
    };
  }

  async function loadProfile(userId) {
    const root = $("profile-root");
    root.innerHTML = "<p style='text-align:center;color:var(--mute)'>Загрузка…</p>";
    try {
      const r = await api(`/api/users/${userId}`);
      state.profile = r;
      const u = r.user;
      const isMe = u.is_me;
      root.innerHTML = `
        <div class="profile-head">
          <div class="profile-ava">${u.photo ? `<img src="${esc(u.photo)}" alt="">` : esc(initials(u.name))}</div>
          <h2>${esc(u.name)}</h2>
          <div class="uname">${u.username ? "@" + esc(u.username) : "id" + u.id}</div>
          <div class="stats">
            <div class="stat"><b>${fmt(u.videos)}</b><span>роликов</span></div>
            <div class="stat"><b>${fmt(u.followers)}</b><span>подписчиков</span></div>
            <div class="stat"><b>${fmt(u.following)}</b><span>подписок</span></div>
          </div>
          <div class="profile-actions">
            ${isMe
              ? `<button class="btn ghost" id="pf-upload">Загрузить</button>`
              : `<button class="btn ${u.followed ? "ghost" : "primary"}" id="pf-follow">${u.followed ? "Подписка" : "Подписаться"}</button>`}
          </div>
        </div>
        <div class="grid" id="pgrid"></div>`;
      const grid = root.querySelector("#pgrid");
      if (!r.videos.length) {
        grid.innerHTML = `<div class="grid-empty">${isMe ? "У тебя пока нет роликов. Пришли видео боту." : "Пока нет роликов"}</div>`;
      } else {
        r.videos.forEach((v) => {
          const c = document.createElement("div");
          c.className = "cell";
          c.innerHTML = `<video muted playsinline preload="metadata" src="${esc(v.src)}"></video><div class="ov">❤ ${fmt(v.likes)}</div>`;
          c.onclick = () => { showScreen("feed"); jumpTo(v.id); };
          grid.appendChild(c);
        });
      }
      const fu = root.querySelector("#pf-upload");
      if (fu) fu.onclick = () => showScreen("upload");
      const ff = root.querySelector("#pf-follow");
      if (ff) ff.onclick = () => follow(u.id, ff, null).then(() => loadProfile(userId));
    } catch (e) {
      root.innerHTML = `<p style="text-align:center">${esc(e.message)}</p>`;
    }
  }

  async function jumpTo(id) {
    if (!state.items.find((x) => x.id === id)) {
      await loadFeed(state.tab, { pin: id });
    }
    const el = feedEl.querySelector(`.slide[data-id="${id}"]`);
    if (el) el.scrollIntoView({ behavior: "instant", block: "start" });
    playVisible();
  }

  async function openProfile(userId) {
    showScreen("profile", { userId });
  }

  async function loadFeed(tab, { pin } = {}) {
    state.tab = tab;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    try {
      const r = await api(`/api/feed?tab=${encodeURIComponent(tab)}&limit=12${pin ? "&pin=" + pin : ""}`);
      state.items = r.items || [];
      renderFeed(state.items);
      if (pin) {
        const el = feedEl.querySelector(`.slide[data-id="${pin}"]`);
        if (el) el.scrollIntoView({ behavior: "instant", block: "start" });
      }
    } catch (e) {
      $("empty").classList.remove("hidden");
      $("empty-title").textContent = "Не открылось";
      $("empty-text").textContent = e.message;
    }
  }

  $("tabs").addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (!t) return;
    showScreen("feed");
    loadFeed(t.dataset.tab);
  });

  document.querySelector(".dock").addEventListener("click", (e) => {
    const b = e.target.closest(".dock-btn");
    if (!b) return;
    showScreen(b.dataset.screen);
  });

  $("empty-upload").onclick = () => showScreen("upload");

  async function boot() {
    try {
      const r = await api("/api/bootstrap");
      state.me = r.me;
      state.prices = r.prices || state.prices;
      state.bot = r.bot || state.bot;
      state.items = r.feed || [];
      renderFeed(state.items);
      const pin = r.pin || Sparse(startParam);
      if (pin) {
        const el = feedEl.querySelector(`.slide[data-id="${pin}"]`);
        if (el) el.scrollIntoView({ behavior: "instant", block: "start" });
      }
      setupUpload();
      const screen = params.get("screen");
      const screenUser = parseInt(params.get("user") || "0", 10);
      if (screen === "comments") {
        const id = pin || (state.items.find((x) => x.comments > 0) || state.items[0] || {}).id;
        if (id) openComments(id);
      } else if (screen === "profile") showScreen("profile", { userId: screenUser || undefined });
      else if (screen === "upload") showScreen("upload");
      else if (screen === "gifts" && state.items[0]) openGifts(state.items[0]);
    } catch (e) {
      $("empty").classList.remove("hidden");
      $("empty-title").textContent = "Не открылось";
      $("empty-text").textContent = e.message + (e.status === 401 ? ". Открой через кнопку в боте." : "");
    }
  }

  function Sparse(p) {
    if (p && String(p).startsWith("v_")) return parseInt(String(p).slice(2), 10) || 0;
    return 0;
  }

  boot();
})();
