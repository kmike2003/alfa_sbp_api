<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>СБП · Рекуррентная оплата</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Onest:wght@300;400;500;600;700&display=swap');
:root{
  --bg:#0f1117;--surface:#181c27;--surface2:#1e2235;--border:#252b3b;--border2:#2f3650;
  --accent:#ef3124;--accent-dim:#b5231a;--accent-bg:rgba(239,49,36,.08);
  --text:#e8eaf0;--muted:#6b7280;--muted2:#9aa3af;
  --green:#22c55e;--green-bg:rgba(34,197,94,.08);--green-border:rgba(34,197,94,.25);
  --yellow:#eab308;--yellow-bg:rgba(234,179,8,.08);--yellow-border:rgba(234,179,8,.25);
  --red:#ef4444;--red-bg:rgba(239,68,68,.08);--red-border:rgba(239,68,68,.25);
  --blue:#3b82f6;--blue-bg:rgba(59,130,246,.08);--blue-border:rgba(59,130,246,.25);
  --r:12px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Onest',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
.app{display:flex;min-height:100vh;}
.sidebar{width:220px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh;overflow-y:auto;}
.logo{padding:20px 18px 16px;border-bottom:1px solid var(--border);}
.logo-mark{width:36px;height:36px;background:var(--accent);border-radius:9px;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;color:#fff;margin-bottom:10px;}
.logo-title{font-size:14px;font-weight:600;}
.logo-sub{font-size:11px;color:var(--muted);margin-top:2px;}
.nav{padding:12px 10px;flex:1;}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:8px;
  cursor:pointer;font-size:13px;font-weight:500;color:var(--muted2);transition:all .15s;
  margin-bottom:2px;border:none;background:none;width:100%;text-align:left;font-family:inherit;}
.nav-item:hover{background:rgba(255,255,255,.04);color:var(--text);}
.nav-item.active{background:var(--accent-bg);color:var(--accent);border:1px solid rgba(239,49,36,.15);}
.nav-icon{font-size:16px;width:20px;text-align:center;}
.nav-badge{margin-left:auto;background:var(--accent);color:#fff;font-size:10px;
  font-weight:700;padding:1px 6px;border-radius:999px;display:none;}
.sidebar-footer{padding:10px;border-top:1px solid var(--border);}
.env-badge{padding:7px 10px;border-radius:8px;font-size:11px;font-weight:600;
  display:flex;align-items:center;gap:6px;border:1px solid;margin-bottom:8px;}
.env-badge.test{background:var(--yellow-bg);border-color:var(--yellow-border);color:var(--yellow);}
.env-badge.prod{background:var(--green-bg);border-color:var(--green-border);color:var(--green);}
.logout-btn{width:100%;padding:7px;background:none;border:1px solid var(--border);border-radius:7px;
  color:var(--muted);font-family:inherit;font-size:12px;cursor:pointer;transition:all .15s;}
.logout-btn:hover{border-color:var(--red-border);color:var(--red);}
.main{flex:1;padding:32px 28px 80px;max-width:700px;}
.page{display:none;}.page.active{display:block;}
.page-header{margin-bottom:24px;}
.page-title{font-size:20px;font-weight:700;margin-bottom:4px;}
.page-sub{font-size:13px;color:var(--muted);}
.login-screen{display:flex;align-items:center;justify-content:center;min-height:100vh;background:var(--bg);}
.login-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:36px;width:100%;max-width:360px;}
.login-logo{display:flex;align-items:center;gap:12px;margin-bottom:28px;}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:24px;margin-bottom:16px;}
.sect{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
.field-group{display:flex;flex-direction:column;gap:12px;margin-bottom:18px;}
.field label{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-bottom:5px;
  letter-spacing:.04em;text-transform:uppercase;}
.field input,.field select{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;color:var(--text);font-family:inherit;font-size:14px;outline:none;transition:border-color .15s;}
.field input:focus,.field select:focus{border-color:var(--accent);}
.field input::placeholder{color:var(--muted);}
.field-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
select option{background:#1e2235;}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 18px;
  border-radius:8px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:all .15s;}
.btn-primary{background:var(--accent);color:#fff;width:100%;padding:13px;}
.btn-primary:hover{background:var(--accent-dim);}
.btn-primary:disabled{opacity:.4;cursor:not-allowed;}
.btn-secondary{background:transparent;border:1px solid var(--border);color:var(--muted2);}
.btn-secondary:hover{border-color:var(--border2);color:var(--text);background:rgba(255,255,255,.03);}
.btn-sm{padding:6px 12px;font-size:12px;}
.btn-danger{background:var(--red-bg);border:1px solid var(--red-border);color:var(--red);}
.btn-danger:hover{background:rgba(239,68,68,.15);}
.btn-success{background:var(--green-bg);border:1px solid var(--green-border);color:var(--green);}
.spinner{width:15px;height:15px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;
  border-radius:50%;animation:spin .6s linear infinite;display:none;}
@keyframes spin{to{transform:rotate(360deg);}}
.alert{border-radius:8px;padding:11px 13px;font-size:12px;line-height:1.6;margin-bottom:14px;display:none;white-space:pre-line;}
.alert.error{background:var(--red-bg);border:1px solid var(--red-border);color:var(--red);}
.alert.success{background:var(--green-bg);border:1px solid var(--green-border);color:var(--green);}
.alert.info{background:var(--blue-bg);border:1px solid var(--blue-border);color:var(--blue);}
.alert.warn{background:var(--yellow-bg);border:1px solid var(--yellow-border);color:var(--yellow);}
.hint{background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;font-size:12px;color:var(--muted);line-height:1.6;}
.hint b{color:var(--muted2);}
.steps{display:flex;align-items:center;gap:6px;margin-bottom:20px;}
.step-dot{width:24px;height:24px;border-radius:50%;border:1.5px solid var(--border);
  display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:var(--muted);}
.step-dot.active{border-color:var(--accent);background:var(--accent);color:#fff;}
.step-dot.done{border-color:var(--green);background:var(--green);color:#fff;}
.step-line{flex:1;height:1px;background:var(--border);}
.result-card{display:none;flex-direction:column;align-items:center;gap:14px;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:24px;margin-top:16px;}
#qr-img{width:210px;height:210px;border-radius:10px;background:#fff;padding:8px;
  box-shadow:0 0 0 1px var(--border);display:none;}
.payment-link-box{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;font-size:12px;color:var(--accent);word-break:break-all;line-height:1.5;
  user-select:all;cursor:text;}
.order-meta{font-size:10px;color:var(--muted);text-align:center;word-break:break-all;line-height:1.7;}
.client-summary{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;
  padding:12px;font-size:12px;line-height:1.9;}
.client-summary b{color:var(--muted);font-weight:500;}
.poll-indicator{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--yellow);
  background:var(--yellow-bg);border:1px solid var(--yellow-border);border-radius:8px;
  padding:9px 13px;width:100%;}
.poll-dot{width:8px;height:8px;border-radius:50%;background:var(--yellow);animation:pulse 1.2s ease-in-out infinite;flex-shrink:0;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.3;}}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:var(--r);}
table{width:100%;border-collapse:collapse;font-size:12px;}
thead{background:var(--surface2);}
th{padding:9px 12px;text-align:left;font-weight:600;color:var(--muted);font-size:10px;
  text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--border);}
td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:rgba(255,255,255,.012);}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:999px;
  font-size:10px;font-weight:600;white-space:nowrap;}
.badge-green{background:var(--green-bg);border:1px solid var(--green-border);color:var(--green);}
.badge-red{background:var(--red-bg);border:1px solid var(--red-border);color:var(--red);}
.badge-yellow{background:var(--yellow-bg);border:1px solid var(--yellow-border);color:var(--yellow);}
.badge-muted{background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--muted);}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:100;
  align-items:center;justify-content:center;padding:16px;}
.modal-overlay.open{display:flex;}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:24px;width:100%;max-width:420px;position:relative;}
.modal-close{position:absolute;top:12px;right:12px;background:none;border:none;color:var(--muted);
  font-size:20px;cursor:pointer;line-height:1;}
.modal-close:hover{color:var(--text);}
.modal-title{font-size:15px;font-weight:600;margin-bottom:18px;}
.history-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:14px;margin-bottom:10px;font-size:12px;line-height:1.9;}
.history-item b{color:var(--muted);font-weight:500;}
.history-amount{font-size:18px;font-weight:700;}
.empty{text-align:center;padding:48px 20px;color:var(--muted);}
.empty .empty-icon{font-size:40px;margin-bottom:12px;}
.empty p{font-size:13px;line-height:1.6;}
@media(max-width:680px){
  .app{flex-direction:column;}
  .sidebar{width:100%;height:auto;position:relative;}
  .nav{display:flex;flex-wrap:wrap;padding:8px;gap:4px;}
  .nav-item{flex:1;min-width:70px;justify-content:center;font-size:11px;padding:7px 4px;}
  .nav-item span:not(.nav-icon){display:none;}
  .logo{display:none;}.sidebar-footer{display:none;}
  .main{padding:14px 12px 60px;}
  .field-row{grid-template-columns:1fr;}
}
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login-screen" class="login-screen">
  <div class="login-card">
    <div class="login-logo">
      <div style="width:40px;height:40px;background:var(--accent);border-radius:10px;
        display:flex;align-items:center;justify-content:center;font-weight:700;font-size:17px;color:#fff;flex-shrink:0">СБП</div>
      <div>
        <div style="font-size:17px;font-weight:700">Рекуррентная оплата</div>
        <div style="font-size:12px;color:var(--muted);margin-top:2px">Альфа-банк · Панель управления</div>
      </div>
    </div>
    <div class="alert error" id="login-error"></div>
    <div class="field-group">
      <div class="field">
        <label>Логин</label>
        <input type="text" id="login-user" placeholder="admin" autocomplete="username">
      </div>
      <div class="field">
        <label>Пароль</label>
        <input type="password" id="login-pass" placeholder="••••••••" autocomplete="current-password"
          onkeydown="if(event.key==='Enter')doLogin()">
      </div>
    </div>
    <button class="btn btn-primary" id="login-btn" onclick="doLogin()">
      <span class="spinner" id="login-spinner"></span>
      <span id="login-btn-text">Войти</span>
    </button>
  </div>
</div>

<!-- APP -->
<div id="main-app" class="app" style="display:none">
  <nav class="sidebar">
    <div class="logo">
      <div class="logo-mark">СБП</div>
      <div class="logo-title">Рекуррентная оплата</div>
      <div class="logo-sub">Альфа-банк API</div>
    </div>
    <div class="nav">
      <button class="nav-item active" onclick="showPage('page-qr')" id="nav-qr">
        <span class="nav-icon">📲</span><span>Создать QR</span>
      </button>
      <button class="nav-item" onclick="showPage('page-bindings')" id="nav-bindings">
        <span class="nav-icon">🔗</span><span>Привязки</span>
        <span class="nav-badge" id="bindings-badge"></span>
      </button>
      <button class="nav-item" onclick="showPage('page-history')" id="nav-history">
        <span class="nav-icon">📋</span><span>История</span>
      </button>
    </div>
    <div class="sidebar-footer">
      <div class="env-badge" id="env-badge">⏳ …</div>
      <button class="logout-btn" onclick="doLogout()">← Выйти</button>
    </div>
  </nav>

  <main class="main">

    <!-- QR PAGE -->
    <div class="page active" id="page-qr">
      <div class="page-header">
        <div class="page-title">Создать QR-код и ссылку</div>
        <div class="page-sub">Клиент сканирует → привязывает счёт → ежемесячные списания автоматически</div>
      </div>
      <div class="steps">
        <div class="step-dot active" id="sd1">1</div><div class="step-line"></div>
        <div class="step-dot" id="sd2">2</div><div class="step-line"></div>
        <div class="step-dot" id="sd3">3</div>
      </div>
      <div class="card">
        <div class="sect">Данные клиента</div>
        <div class="field-group">
          <div class="field-row">
            <div class="field"><label>Имя клиента *</label>
              <input type="text" id="q-name" placeholder="Иванов Иван Иванович"></div>
            <div class="field"><label>Телефон</label>
              <input type="tel" id="q-phone" placeholder="+79991234567"></div>
          </div>
          <div class="field"><label>Email</label>
            <input type="email" id="q-email" placeholder="client@email.com"></div>
          <div class="field">
            <label>Назначение платежа * <span style="color:var(--muted);font-weight:400;text-transform:none">(до 99 символов, без % +)</span></label>
            <input type="text" id="q-desc" placeholder="Ежемесячная подписка тариф Базовый" maxlength="99">
          </div>
          <div class="field-row">
            <div class="field"><label>Сумма (₽) *</label>
              <input type="number" id="q-amount" placeholder="1500" min="1" step="0.01"></div>
            <div class="field"><label>День списания</label>
              <select id="q-day">
                <script>for(let i=1;i<=28;i++)document.write(`<option value="${i}">${i}-е число</option>`)</script>
              </select>
            </div>
          </div>
        </div>
        <div class="alert error" id="qr-error"></div>
        <button class="btn btn-primary" id="qr-btn" onclick="generateQR()">
          <span class="spinner" id="qr-spinner"></span>
          <span id="qr-btn-text">Сформировать QR-код с привязкой</span>
        </button>
      </div>

      <div class="result-card" id="qr-result">
        <div class="badge badge-green" id="qr-result-status">✓ QR готов — ожидание сканирования</div>
        <img id="qr-img" alt="QR">
        <div class="client-summary" id="qr-summary"></div>
        <div style="width:100%">
          <div class="sect" style="margin-bottom:8px">Ссылка для клиента</div>
          <div class="payment-link-box" id="qr-link-box">—</div>
        </div>
        <!-- Только кнопка копировать, без "Поделиться" -->
        <button class="btn btn-secondary btn-sm" id="qr-copy-btn" onclick="copyLink()" style="width:100%">
          📋 Копировать ссылку
        </button>
        <div class="poll-indicator" id="qr-poll" style="display:none">
          <div class="poll-dot" id="poll-dot"></div>
          <span id="poll-status-text">Ожидание подтверждения…</span>&nbsp;<span id="poll-timer">120</span>с
        </div>
        <div class="order-meta" id="qr-meta"></div>
        <button class="btn btn-secondary btn-sm" onclick="resetQR()" style="width:100%">← Новый клиент</button>
      </div>
    </div>

    <!-- BINDINGS PAGE -->
    <div class="page" id="page-bindings">
      <div class="page-header">
        <div class="page-title">Привязки</div>
        <div class="page-sub">Клиенты с привязанными счетами СБП</div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
        <button class="btn btn-secondary btn-sm" onclick="renderBindings()">🔄 Обновить</button>
        <button class="btn btn-secondary btn-sm" onclick="showAddManual()">+ Добавить вручную</button>
      </div>
      <div class="alert error" id="bind-error"></div>
      <div class="alert info" style="display:block;font-size:12px;margin-bottom:12px">
        ℹ️ Binding ID появляется автоматически после того, как клиент сканирует QR и подтверждает привязку.
        При необходимости можно ввести вручную через кнопку «Ввести» в таблице.
      </div>
      <div id="bindings-empty" class="empty" style="display:none">
        <div class="empty-icon">🔗</div>
        <p>Привязок пока нет.<br>Создайте QR-код — запись появится здесь сразу.</p>
      </div>
      <div class="table-wrap" id="bindings-table-wrap" style="display:none">
        <table><thead><tr>
          <th>Клиент</th><th>Binding ID</th><th>Сумма</th>
          <th>Следующее списание</th><th>Статус</th><th></th>
        </tr></thead>
        <tbody id="bindings-tbody"></tbody></table>
      </div>

      <div class="card" id="manual-form" style="display:none;margin-top:16px">
        <div style="font-size:13px;font-weight:600;margin-bottom:16px">✏️ Добавить привязку вручную</div>
        <div class="field-group">
          <div class="field-row">
            <div class="field"><label>Имя *</label><input type="text" id="mb-name" placeholder="Иванов Иван"></div>
            <div class="field"><label>Телефон / Email</label><input type="text" id="mb-contact" placeholder="+79991234567"></div>
          </div>
          <div class="field">
            <label>Binding ID * <span style="color:var(--muted);font-weight:400;text-transform:none">(из ЛК банка)</span></label>
            <input type="text" id="mb-bindingid" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
          </div>
          <div class="field-row">
            <div class="field"><label>Сумма ₽/мес *</label><input type="number" id="mb-amount" placeholder="1500"></div>
            <div class="field"><label>День списания</label>
              <select id="mb-day">
                <script>for(let i=1;i<=28;i++)document.write(`<option value="${i}">${i}-е число</option>`)</script>
              </select>
            </div>
          </div>
          <div class="field"><label>Назначение</label><input type="text" id="mb-desc" placeholder="Ежемесячная подписка"></div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary" style="flex:1" onclick="saveManual()">Сохранить</button>
          <button class="btn btn-secondary" onclick="hideAddManual()">Отмена</button>
        </div>
      </div>
    </div>

    <!-- HISTORY PAGE -->
    <div class="page" id="page-history">
      <div class="page-header">
        <div class="page-title">История списаний</div>
        <div class="page-sub">Все проведённые транзакции</div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button class="btn btn-secondary btn-sm" onclick="loadHistory()">🔄 Обновить</button>
        <button class="btn btn-danger btn-sm" onclick="clearHistory()">🗑 Очистить</button>
      </div>
      <div id="history-empty" class="empty">
        <div class="empty-icon">📋</div>
        <p>История пуста.<br>Нажмите 💳 у клиента в разделе Привязки.</p>
      </div>
      <div id="history-list"></div>
    </div>

  </main>
</div>

<!-- CHARGE MODAL -->
<div class="modal-overlay" id="charge-modal">
  <div class="modal">
    <button class="modal-close" onclick="closeModal('charge-modal')">✕</button>
    <div class="modal-title">💳 Списать платёж</div>
    <div class="alert error" id="charge-error"></div>
    <div class="alert success" id="charge-success"></div>
    <div id="charge-form-inner">
      <div class="field-group">
        <div class="field"><label>Клиент</label><input id="ch-name" readonly style="opacity:.6"></div>
        <div class="field-row">
          <div class="field"><label>Сумма (₽)</label><input type="number" id="ch-amount" min="1" step="0.01"></div>
          <div class="field"><label>Назначение *</label><input type="text" id="ch-desc" maxlength="99"></div>
        </div>
      </div>
      <div class="hint" style="margin-bottom:16px">
        Выполнится <b>register.do → paymentOrderBinding.do</b>.<br>
        Банк спишет без подтверждения клиентом. Требуется пермиссия <b>AUTO_PAYMENT</b>.
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" id="charge-btn" style="flex:1" onclick="executeCharge()">
          <span class="spinner" id="charge-spinner"></span>
          <span id="charge-btn-text">Списать</span>
        </button>
        <button class="btn btn-secondary" onclick="closeModal('charge-modal')">Отмена</button>
      </div>
    </div>
  </div>
</div>

<!-- DEACT MODAL -->
<div class="modal-overlay" id="deact-modal">
  <div class="modal">
    <button class="modal-close" onclick="closeModal('deact-modal')">✕</button>
    <div class="modal-title">🚫 Деактивировать привязку</div>
    <div class="alert warn" style="display:block">⚠️ После деактивации повторные списания невозможны.</div>
    <div class="alert error" id="deact-error"></div>
    <div class="alert success" id="deact-success"></div>
    <p id="deact-label" style="font-size:14px;margin:14px 0"></p>
    <div id="deact-btns" style="display:flex;gap:8px">
      <button class="btn btn-danger" id="deact-btn" style="flex:1" onclick="executeDeactivate()">
        <span class="spinner" id="deact-spinner"></span>
        <span id="deact-btn-text">Деактивировать</span>
      </button>
      <button class="btn btn-secondary" onclick="closeModal('deact-modal')">Отмена</button>
    </div>
  </div>
</div>

<script src="/static/app.js" defer></script>

</body>
</html>