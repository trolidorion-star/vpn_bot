const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const state = {
  token: "",
  bootstrap: null,
  activeTab: "keys",
};

const els = {
  appTitle: document.getElementById("appTitle"),
  balanceBadge: document.getElementById("balanceBadge"),
  statKeys: document.getElementById("statKeys"),
  statActive: document.getElementById("statActive"),
  statTrial: document.getElementById("statTrial"),
  keysList: document.getElementById("keysList"),
  tariffsList: document.getElementById("tariffsList"),
  profileInfo: document.getElementById("profileInfo"),
  activateTrialBtn: document.getElementById("activateTrialBtn"),
  detailsDialog: document.getElementById("detailsDialog"),
  detailsTitle: document.getElementById("detailsTitle"),
  detailsContent: document.getElementById("detailsContent"),
  closeDialogBtn: document.getElementById("closeDialogBtn"),
};

function notify(text, danger = false) {
  if (tg?.showPopup) {
    tg.showPopup({ title: danger ? "Ошибка" : "Готово", message: text, buttons: [{ type: "ok" }] });
    return;
  }
  alert(text);
}

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  const res = await fetch(path, { ...options, headers });
  let data = {};
  try {
    data = await res.json();
  } catch (e) {
    data = {};
  }
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function initSession() {
  const initData = tg?.initData || "";
  if (!initData) {
    notify("Mini App запускается только внутри Telegram.", true);
    return;
  }
  const data = await api("/miniapp/api/session", {
    method: "POST",
    body: JSON.stringify({ initData }),
  });
  state.token = data.token;
  state.bootstrap = data.bootstrap;
  render();
}

function setLoadingBlocks() {
  els.keysList.innerHTML = `<article class="card">Загрузка ключей...</article>`;
  els.tariffsList.innerHTML = `<article class="card">Загрузка тарифов...</article>`;
  els.profileInfo.textContent = "Загрузка профиля...";
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("ru-RU");
}

function renderStats() {
  const data = state.bootstrap;
  const keys = data.keys || [];
  const activeCount = keys.filter((k) => k.is_active).length;
  els.appTitle.textContent = data.app?.name || "VPN Control Center";
  els.balanceBadge.textContent = `${data.user?.balance_text || "0,00"} ₽`;
  els.statKeys.textContent = String(keys.length);
  els.statActive.textContent = String(activeCount);
  els.statTrial.textContent = data.trial?.available ? "Да" : "Нет";
}

function buildKeyCard(key) {
  const statusClass = key.is_draft ? "draft" : key.is_active ? "active" : "expired";
  const statusText = key.is_draft ? "Черновик" : key.is_active ? "Активен" : "Истек";
  const trafficText =
    key.traffic_limit > 0
      ? `${(key.traffic_used / 1024 ** 3).toFixed(2)} / ${(key.traffic_limit / 1024 ** 3).toFixed(2)} GB`
      : `${(key.traffic_used / 1024 ** 3).toFixed(2)} GB / ∞`;
  return `
    <article class="card">
      <div class="title-row">
        <h3>${key.display_name}</h3>
        <span class="status ${statusClass}">${statusText}</span>
      </div>
      <div class="meta">
        <div>Сервер: ${key.server_name || "Не выбран"}</div>
        <div>До: ${formatDate(key.expires_at)}${key.days_left !== null ? ` (${key.days_left} дн.)` : ""}</div>
        <div>Трафик: ${trafficText}</div>
      </div>
      <div class="actions">
        ${
          key.is_draft
            ? `<button class="btn btn-primary" data-action="configure-key" data-key-id="${key.id}">Настроить</button>`
            : `<button class="btn btn-primary" data-action="open-key" data-key-id="${key.id}">Показать ключ</button>`
        }
      </div>
    </article>
  `;
}

function renderKeys() {
  const keys = state.bootstrap.keys || [];
  if (!keys.length) {
    els.keysList.innerHTML = `<article class="card">У вас пока нет ключей. Купите тариф в соседней вкладке.</article>`;
    return;
  }
  els.keysList.innerHTML = keys.map(buildKeyCard).join("");
}

function renderTariffs() {
  const { tariffs = [], user = {}, app = {} } = state.bootstrap;
  if (!tariffs.length) {
    els.tariffsList.innerHTML = `<article class="card">Активных тарифов нет.</article>`;
    return;
  }
  const cards = tariffs
    .map((t) => {
      const priceRub = Number(t.price_rub || 0);
      const canBalance = app.can_use_balance && priceRub > 0 && user.balance_cents >= priceRub * 100;
      return `
      <article class="card">
        <div class="title-row">
          <h3>${t.name}</h3>
          <span class="status ${t.is_active ? "active" : "expired"}">${t.duration_days} дн.</span>
        </div>
        <div class="meta">
          <div>USDT: ${(Number(t.price_cents || 0) / 100).toFixed(2)}</div>
          <div>Stars: ${Number(t.price_stars || 0)}</div>
          <div>Рубли: ${priceRub ? `${priceRub} ₽` : "—"}</div>
        </div>
        <div class="actions">
          ${
            canBalance
              ? `<button class="btn btn-primary" data-action="buy-balance" data-tariff-id="${t.id}">Купить за баланс</button>`
              : app.crypto_enabled
              ? `<button class="btn" data-action="open-bot-buy">Открыть оплату в боте</button>`
              : `<button class="btn" data-action="open-bot-buy">Купить в боте</button>`
          }
        </div>
      </article>`;
    })
    .join("");
  els.tariffsList.innerHTML = cards;
}

function renderProfile() {
  const { user, app, trial } = state.bootstrap;
  els.profileInfo.innerHTML = `
    Telegram ID: <b>${user.telegram_id}</b><br />
    Username: <b>${user.username ? `@${user.username}` : "не задан"}</b><br />
    Баланс: <b>${user.balance_text} ₽</b><br />
    Оплата балансом: <b>${app.can_use_balance ? "включена" : "выключена"}</b>
  `;
  els.activateTrialBtn.classList.toggle("hidden", !trial?.available);
}

function render() {
  renderStats();
  renderKeys();
  renderTariffs();
  renderProfile();
}

function showDialog(title, html) {
  els.detailsTitle.textContent = title;
  els.detailsContent.innerHTML = html;
  els.detailsDialog.showModal();
}

function closeDialog() {
  els.detailsDialog.close();
}

function attachTabHandlers() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      if (!tab) return;
      state.activeTab = tab;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      document
        .querySelectorAll(".tab-content")
        .forEach((c) => c.classList.toggle("is-active", c.dataset.content === tab));
    });
  });
}

async function refreshBootstrap() {
  const data = await api("/miniapp/api/bootstrap");
  state.bootstrap = data.data;
  render();
}

async function onBuyBalance(tariffId) {
  try {
    await api("/miniapp/api/payments/balance", {
      method: "POST",
      body: JSON.stringify({ tariff_id: Number(tariffId) }),
    });
    await refreshBootstrap();
    notify("Оплата балансом выполнена.");
  } catch (e) {
    notify(e.message, true);
  }
}

function onOpenBotBuy() {
  notify("Для Stars/карты/USDT используйте экран оплаты в самом боте (кнопка «Купить ключ»).");
}

async function onOpenKey(keyId) {
  try {
    const res = await api(`/miniapp/api/keys/${keyId}/material`);
    const data = res.data;
    if (data.status === "draft") {
      notify("Ключ еще не настроен. Сначала выберите сервер и протокол.", true);
      return;
    }
    const splitBlock = data.split_url
      ? `<p><b>Split URL:</b><br /><a href="${data.split_url}" target="_blank">${data.split_url}</a></p>`
      : "";
    showDialog(
      "Данные ключа",
      `
      <p><b>Ссылка:</b></p>
      <pre class="modal-code">${data.link}</pre>
      <p><button class="btn btn-primary" id="copyLinkBtn">Скопировать ссылку</button></p>
      <p><img class="qr-img" src="data:image/png;base64,${data.qr_base64}" alt="QR" /></p>
      ${splitBlock}
      <p><b>JSON конфиг:</b></p>
      <pre class="modal-code">${data.json_config.replace(/</g, "&lt;")}</pre>
      `
    );
    const copyBtn = document.getElementById("copyLinkBtn");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(data.link);
          notify("Ссылка скопирована.");
        } catch (e) {
          notify("Не удалось скопировать автоматически.");
        }
      });
    }
  } catch (e) {
    notify(e.message, true);
  }
}

async function onConfigureKey(keyId) {
  try {
    const srvRes = await api(`/miniapp/api/keys/${keyId}/servers`);
    const servers = srvRes.data || [];
    if (!servers.length) {
      notify("Нет доступных серверов.", true);
      return;
    }
    const options = servers
      .map((s) => `<option value="${s.id}">${s.name}</option>`)
      .join("");
    showDialog(
      "Настройка ключа",
      `
      <p>Выберите сервер и протокол для ключа #${keyId}.</p>
      <p><select id="serverSelect" class="btn">${options}</select></p>
      <p><select id="inboundSelect" class="btn"><option>Загрузка...</option></select></p>
      <p><button id="provisionBtn" class="btn btn-primary">Применить</button></p>
      `
    );

    const serverSelect = document.getElementById("serverSelect");
    const inboundSelect = document.getElementById("inboundSelect");
    const loadInbounds = async () => {
      const serverId = Number(serverSelect.value);
      const inRes = await api(`/miniapp/api/servers/${serverId}/inbounds`);
      const optionsHtml = (inRes.data || [])
        .map((item) => `<option value="${item.id}">${item.remark || "VPN"} (#${item.id})</option>`)
        .join("");
      inboundSelect.innerHTML = optionsHtml || "<option>Нет протоколов</option>";
    };
    serverSelect.addEventListener("change", loadInbounds);
    await loadInbounds();

    const provisionBtn = document.getElementById("provisionBtn");
    provisionBtn?.addEventListener("click", async () => {
      try {
        await api(`/miniapp/api/keys/${keyId}/provision`, {
          method: "POST",
          body: JSON.stringify({
            server_id: Number(serverSelect.value),
            inbound_id: Number(inboundSelect.value),
          }),
        });
        closeDialog();
        await refreshBootstrap();
        notify("Ключ настроен.");
      } catch (e) {
        notify(e.message, true);
      }
    });
  } catch (e) {
    notify(e.message, true);
  }
}

async function onActivateTrial() {
  try {
    await api("/miniapp/api/trial/activate", { method: "POST", body: JSON.stringify({}) });
    await refreshBootstrap();
    notify("Пробный период активирован. Настройте созданный ключ во вкладке «Ключи».");
  } catch (e) {
    notify(e.message, true);
  }
}

function attachGlobalActions() {
  document.body.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    if (!action) return;

    if (action === "buy-balance") {
      await onBuyBalance(target.dataset.tariffId);
      return;
    }
    if (action === "open-bot-buy") {
      onOpenBotBuy();
      return;
    }
    if (action === "open-key") {
      await onOpenKey(target.dataset.keyId);
      return;
    }
    if (action === "configure-key") {
      await onConfigureKey(target.dataset.keyId);
    }
  });

  els.activateTrialBtn.addEventListener("click", onActivateTrial);
  els.closeDialogBtn.addEventListener("click", closeDialog);
  els.detailsDialog.addEventListener("click", (event) => {
    const rect = els.detailsDialog.getBoundingClientRect();
    const clickInside =
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom;
    if (!clickInside) {
      closeDialog();
    }
  });
}

async function start() {
  setLoadingBlocks();
  attachTabHandlers();
  attachGlobalActions();
  try {
    await initSession();
  } catch (e) {
    notify(`Не удалось открыть Mini App: ${e.message}`, true);
  }
}

start();
