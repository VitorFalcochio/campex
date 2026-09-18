const shellState = {
  popover: null,
  lastFocused: null,
  user: null,
  authenticated: false,
  workspace: {
    organization: null,
    activeUnit: null,
    activeUnitId: null,
    units: [],
  },
};

function normalizeCampexLocalHost() {
  if (window.location.hostname !== "0.0.0.0") return;
  const next = new URL(window.location.href);
  next.hostname = "127.0.0.1";
  window.location.replace(next.toString());
}

normalizeCampexLocalHost();

/* CAMPEX PRODUCT SHELL V1 */

const SHELL_DESTINATIONS = [
  { label: "Início", href: "/operations-view?view=home", icon: "home" },
  { label: "Operação", href: "/operations-view", icon: "operations" },
  { label: "Eventos", href: "/events", icon: "events" },
  { label: "Intelligence", href: "/insights", icon: "insights" },
  { label: "Relatórios", href: "/reports", icon: "insights" },
  { label: "Ao vivo", href: "/live-grid", icon: "camera" },
];

function normalizePrimaryNavigation() {
  document.querySelectorAll(".cx-nav").forEach((nav) => {
    nav.innerHTML = `
      ${SHELL_DESTINATIONS.map((item) => `
        <a href="${item.href}">
          <span class="cx-nav-icon" data-icon="${item.icon}"></span>
          ${item.label}
        </a>
      `).join("")}
      <hr />
      <a href="/settings/cameras">
        <span class="cx-nav-icon" data-icon="settings"></span>
        Configurações
      </a>
    `;
  });
}

function normalizeAccountFooter() {
  document.querySelectorAll(".cx-account").forEach((account) => {
    const links = account.querySelectorAll(".cx-footer-link");

    links.forEach((link) => {
      const icon = link.querySelector(".cx-nav-icon");

      if (icon?.dataset.icon === "help") {
        link.href = "/help";
        link.innerHTML = `
          <span class="cx-nav-icon" data-icon="help"></span>
          Ajuda
        `;
      }

      if (icon?.dataset.icon === "status") {
        link.href = "/local-diagnostics-view";
        link.innerHTML = `
          <span class="cx-nav-icon" data-icon="status"></span>
          <span>Status do sistema</span>
          <i class="cx-shell-online-dot" aria-hidden="true"></i>
        `;
      }
    });
  });
}

function ensureGlobalHeaderTools() {
  document.querySelectorAll(".cx-header-tools").forEach((tools) => {
    const hasPageSearch = tools.querySelector(
      "#workspaceSearch, .cx-top-search, [data-shell-search]"
    );

    if (!hasPageSearch) {
      tools.insertAdjacentHTML(
        "afterbegin",
        `<button class="cx-shell-search-trigger" type="button" data-shell-search>
          <span class="cx-shell-search-label">Buscar na Campex</span>
          <kbd>⌘K</kbd>
        </button>`
      );
    }

    if (!tools.querySelector('[aria-label="Ajuda"]')) {
      tools.insertAdjacentHTML(
        "beforeend",
        `<button class="cx-icon-button" type="button" aria-label="Ajuda">
          <span class="cx-nav-icon" data-icon="help"></span>
        </button>`
      );
    }

    if (!tools.querySelector('[aria-label="Notificações"]')) {
      tools.insertAdjacentHTML(
        "beforeend",
        `<button class="cx-icon-button" type="button" aria-label="Notificações">
          <span class="cx-nav-icon" data-icon="alert"></span>
        </button>`
      );
    }

    if (!tools.querySelector(".cx-top-avatar")) {
      tools.insertAdjacentHTML(
        "beforeend",
        `<button class="cx-top-avatar" type="button" aria-label="Conta">C</button>`
      );
    }
  });
}

function shellSearchResults(query = "") {
  const q = String(query).trim().toLowerCase();

  return SHELL_DESTINATIONS
    .concat([
      { label: "Configurações", href: "/settings/cameras", icon: "settings" },
      { label: "Ajuda", href: "/help", icon: "help" },
      { label: "Status do sistema", href: "/local-diagnostics-view", icon: "status" },
    ])
    .filter((item) => !q || item.label.toLowerCase().includes(q));
}

function renderShellSearchResults(container, query = "") {
  const rows = shellSearchResults(query);

  container.innerHTML = rows.length
    ? rows.map((item, index) => `
        <a class="cx-command-item ${index === 0 ? "active" : ""}" href="${item.href}">
          <span class="cx-nav-icon" data-icon="${item.icon}"></span>
          <span>${sanitize(item.label)}</span>
          <small>↵</small>
        </a>
      `).join("")
    : `<div class="cx-command-empty">Nenhum resultado encontrado.</div>`;
}

function closeCommandPalette() {
  document.querySelector(".cx-command-overlay")?.remove();
}

function openCommandPalette() {
  closeCommandPalette();
  closePopover();

  const overlay = document.createElement("div");
  overlay.className = "cx-command-overlay";

  overlay.innerHTML = `
    <div class="cx-command-palette" role="dialog" aria-modal="true" aria-label="Buscar na Campex">
      <div class="cx-command-search">
        <span class="cx-nav-icon" data-icon="search"></span>
        <input
          type="text"
          placeholder="Buscar páginas e áreas..."
          autocomplete="off"
          aria-label="Buscar páginas e áreas"
        />
        <kbd>ESC</kbd>
      </div>

      <div class="cx-command-section-label">Navegação</div>
      <div class="cx-command-results"></div>
    </div>
  `;

  document.body.appendChild(overlay);

  const input = overlay.querySelector("input");
  const results = overlay.querySelector(".cx-command-results");

  renderShellSearchResults(results);

  input.addEventListener("input", () => {
    renderShellSearchResults(results, input.value);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      const first = results.querySelector(".cx-command-item");
      if (first) window.location.href = first.href;
    }
  });

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeCommandPalette();
  });

  requestAnimationFrame(() => input.focus());
}

function closeAccountPanel() {
  document.querySelector(".cx-account-overlay")?.remove();
}

function openAccountPanel() {
  closeAccountPanel();
  closePopover();

  const user = shellState.user || {};

  const name = shellState.authenticated
    ? (user.nome || user.email || "Usuário Campex")
    : "Sessão não iniciada";

  const email = shellState.authenticated
    ? (user.email || "E-mail não informado")
    : "Entre para acessar sua conta.";

  const role = shellState.authenticated
    ? (user.role || user.funcao || "Usuário")
    : "Sem sessão";

  const overlay = document.createElement("div");
  overlay.className = "cx-account-overlay";

  overlay.innerHTML = `
    <section class="cx-account-panel" role="dialog" aria-modal="true" aria-label="Minha conta">
      <header>
        <div>
          <span>CONTA</span>
          <h2>Minha conta</h2>
        </div>
        <button type="button" class="cx-account-close" aria-label="Fechar">×</button>
      </header>

      <div class="cx-account-identity">
        <div class="cx-account-avatar-large">${sanitize(initialsFrom(name))}</div>
        <div>
          <strong>${sanitize(name)}</strong>
          <span>${sanitize(email)}</span>
        </div>
      </div>

      <div class="cx-account-details">
        <div>
          <span>Função</span>
          <strong>${sanitize(role)}</strong>
        </div>
        <div>
          <span>Organização</span>
          <strong>Cliente piloto</strong>
        </div>
        <div>
          <span>Unidade</span>
          <strong>Unidade principal</strong>
        </div>
      </div>

      <nav class="cx-account-actions">
        <a href="/settings/cameras">
          <span class="cx-nav-icon" data-icon="settings"></span>
          Configurações
        </a>
        <a href="/settings/cameras#destinatarios">
          <span class="cx-nav-icon" data-icon="alert"></span>
          Preferências de notificações
        </a>
        <a href="/local-diagnostics-view">
          <span class="cx-nav-icon" data-icon="status"></span>
          Status do sistema
        </a>
        <a href="/help">
          <span class="cx-nav-icon" data-icon="help"></span>
          Ajuda e suporte
        </a>
      </nav>
    </section>
  `;

  document.body.appendChild(overlay);

  overlay.querySelector(".cx-account-close")
    ?.addEventListener("click", closeAccountPanel);

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeAccountPanel();
  });
}

function routeKey(pathname = window.location.pathname, search = window.location.search) {
  if (pathname === "/operations-view" && new URLSearchParams(search).get("view") === "home") return "/operations-view?view=home";
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return "/settings/cameras";
  if (pathname === "/overview") return "/overview";
  if (pathname === "/dashboard" || pathname === "/" || pathname === "/operations-view") return "/operations-view";
  return pathname;
}

function closePopover() {
  if (shellState.popover) {
    shellState.popover.remove();
    shellState.popover = null;
  }
}

function closeDrawer() {
  document.body.classList.remove("sidebar-open");
  document.querySelector(".cx-mobile-overlay")?.setAttribute("hidden", "");
  document.querySelector(".cx-mobile-menu")?.setAttribute("aria-expanded", "false");
  document.querySelectorAll(".cx-collapse").forEach((button) => button.setAttribute("aria-expanded", "false"));
}

function closeSidePanels() {
  document.querySelectorAll(".cx-detail-drawer.open").forEach((panel) => {
    panel.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  });
  if (shellState.lastFocused) shellState.lastFocused.focus({ preventScroll: true });
}

function sanitize(text) {
  const value = String(text ?? "");
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initialsFrom(name, fallback = "C") {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return fallback;
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

function roleLabel(role) {
  const labels = {
    admin_campex: "Administrador Campex",
    admin_cliente: "Administrador",
    operador: "Operador",
    visualizador: "Visualizador",
  };
  return labels[role] || role || "Usuário";
}

function organizationName(user = shellState.user || {}) {
  return user.cliente_nome || user.empresa_nome || user.organizacao_nome || user.organization_name || "Indústria Alpha";
}

function avatarMarkup(name, photoUrl, className = "cx-avatar") {
  const safeName = sanitize(name || "Usuário Campex");
  if (photoUrl) {
    return `<span class="${className}"><img src="${sanitize(photoUrl)}" alt="${safeName}" /></span>`;
  }
  return `<span class="${className}" aria-hidden="true">${sanitize(initialsFrom(name))}</span>`;
}

function popoverItem(item) {
  if (typeof item === "string") return `<span class="cx-popover-note">${sanitize(item)}</span>`;
  if (item.type === "divider") return `<hr class="cx-popover-divider" />`;
  if (item.type === "account-header") {
    return `
      <div class="cx-popover-account-head">
        ${avatarMarkup(item.name, item.photoUrl, "cx-popover-avatar")}
        <div>
          <strong>${sanitize(item.name)}</strong>
          <span>${sanitize(item.email)}</span>
          <small>${sanitize(item.company)}</small>
        </div>
      </div>
    `;
  }
  const label = sanitize(item.label);
  const icon = item.icon ? `<span class="cx-nav-icon" data-icon="${sanitize(item.icon)}"></span>` : "";
  const attrs = [
    item.action ? `data-popover-action="${sanitize(item.action)}"` : "",
    item.unitId ? `data-unit-id="${sanitize(item.unitId)}"` : "",
    item.href ? `href="${sanitize(item.href)}"` : "",
    item.disabled ? "aria-disabled=\"true\"" : "",
  ].filter(Boolean).join(" ");
  if (item.href && !item.disabled) {
    return `<a role="menuitem" ${attrs}>${icon}<span>${label}</span></a>`;
  }
  return `<button type="button" role="menuitem" ${attrs} ${item.disabled ? "disabled" : ""}>${icon}<span>${label}</span></button>`;
}

function openPopover(anchor, title, items) {
  closePopover();
  shellState.lastFocused = anchor;
  const rect = anchor.getBoundingClientRect();
  const popover = document.createElement("div");
  popover.className = "cx-popover";
  popover.setAttribute("role", "menu");
  popover.tabIndex = -1;
  popover.innerHTML = `<span class="cx-popover-title">${sanitize(title)}</span>${items.map(popoverItem).join("")}`;
  document.body.appendChild(popover);

  const popoverRect = popover.getBoundingClientRect();
  const margin = 12;
  const width = popoverRect.width || 280;
  const height = popoverRect.height || 360;
  const left = Math.min(
    Math.max(margin, rect.right - width),
    window.innerWidth - width - margin
  );
  const preferredTop = rect.top - height - 10;
  const fallbackTop = rect.bottom + 10;
  const top = preferredTop >= margin
    ? preferredTop
    : Math.min(Math.max(margin, fallbackTop), window.innerHeight - height - margin);

  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
  shellState.popover = popover;
  popover.focus();
}

async function loadShellUser() {
  try {
    const response = await fetch("/auth/status", { headers: { "Accept": "application/json" } });
    if (!response.ok) return { authenticated: false, user: null, bootstrap: false };
    return response.json();
  } catch {
    return { authenticated: false, user: null, bootstrap: false };
  }
}

function updateIdentity(auth) {
  shellState.authenticated = Boolean(auth?.authenticated);
  shellState.user = auth?.user || null;
  const user = shellState.user || {};
  const displayName = shellState.authenticated ? (user.nome || user.email || "Usuário Campex") : "Entrar";
  const company = shellState.authenticated ? organizationName(user) : "Sessão necessária";
  const role = shellState.authenticated ? roleLabel(user.role || user.funcao) : "Sessão necessária";
  const initials = shellState.authenticated ? initialsFrom(displayName) : "C";
  const photoUrl = user.avatar_url || user.foto_url || user.photo_url || user.profile_photo_url;

  document.querySelectorAll(".cx-profile-name").forEach((node) => { node.textContent = displayName; });
  document.querySelectorAll(".cx-profile-role").forEach((node) => {
    node.textContent = company;
    node.title = `${company} · ${role}`;
  });
  document.querySelectorAll(".cx-avatar, .cx-top-avatar").forEach((node) => {
    node.textContent = "";
    node.style.backgroundImage = photoUrl ? `url("${photoUrl}")` : "";
    node.classList.toggle("has-image", Boolean(photoUrl));
    if (!photoUrl) node.textContent = initials;
  });
  document.querySelectorAll(".cx-profile-trigger").forEach((node) => {
    node.setAttribute("aria-label", shellState.authenticated ? `Conta de ${displayName}` : "Entrar na Campex");
  });
}

function updateWorkspaceSwitcher() {
  const workspace = shellState.workspace || {};
  const organization = workspace.organization || {};
  const unit = workspace.activeUnit || {};
  const organizationLabel = organization.nome || organization.name || organizationName();
  const unitLabel = unit.nome || unit.name || "Unidade principal";
  document.querySelectorAll(".cx-workspace-switcher").forEach((switcher) => {
    switcher.title = `${organizationLabel} · ${unitLabel}`;
    const initials = switcher.querySelector(".cx-workspace-initials");
    const strong = switcher.querySelector(".cx-workspace-copy strong");
    const small = switcher.querySelector(".cx-workspace-copy small");
    if (initials) initials.textContent = initialsFrom(organizationLabel, "CP");
    if (strong) strong.textContent = organizationLabel;
    if (small) small.textContent = unitLabel;
  });
}

function setupActiveNavigation() {
  const current = routeKey();
  document.querySelectorAll(".cx-nav a").forEach((link) => {
    const url = new URL(link.href, window.location.origin);
    const active = routeKey(url.pathname, url.search) === current;
    link.classList.toggle("active", active);
    link.setAttribute("aria-current", active ? "page" : "false");
    const label = link.textContent.trim();
    link.setAttribute("title", label);
    link.setAttribute("aria-label", label);
  });
  document.querySelectorAll(".cx-footer-link").forEach((link) => {
    const label = link.textContent.trim();
    link.setAttribute("title", label);
    link.setAttribute("aria-label", label);
  });
}

function setupSidebar() {
  const sidebar = document.querySelector(".cx-sidebar");
  if (!sidebar) return;
  const overlay = document.createElement("button");
  overlay.className = "cx-mobile-overlay";
  overlay.type = "button";
  overlay.hidden = true;
  overlay.setAttribute("aria-label", "Fechar navegação");
  document.body.appendChild(overlay);
  overlay.addEventListener("click", closeDrawer);

  const mobileMenu = document.createElement("button");
  mobileMenu.className = "cx-mobile-menu";
  mobileMenu.type = "button";
  mobileMenu.setAttribute("aria-label", "Abrir navegação");
  mobileMenu.setAttribute("aria-expanded", "false");
  mobileMenu.innerHTML = "☰";
  document.body.appendChild(mobileMenu);
  mobileMenu.addEventListener("click", () => {
    const open = !document.body.classList.contains("sidebar-open");
    document.body.classList.toggle("sidebar-open", open);
    overlay.hidden = !open;
    mobileMenu.setAttribute("aria-expanded", String(open));
    document.querySelectorAll(".cx-collapse").forEach((button) => button.setAttribute("aria-expanded", String(open)));
    if (open) sidebar.querySelector("a, button")?.focus({ preventScroll: true });
  });

  document.querySelectorAll(".cx-collapse").forEach((button) => {
    button.setAttribute("aria-expanded", "true");
    button.addEventListener("click", () => {
      const mobile = window.matchMedia("(max-width: 860px)").matches;
      if (mobile) {
        const open = !document.body.classList.contains("sidebar-open");
        document.body.classList.toggle("sidebar-open", open);
        overlay.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
        mobileMenu.setAttribute("aria-expanded", String(open));
        if (open) sidebar.querySelector("a, button")?.focus({ preventScroll: true });
        return;
      }
      document.body.classList.toggle("sidebar-collapsed");
      button.setAttribute("aria-expanded", String(!document.body.classList.contains("sidebar-collapsed")));
    });
  });
}

function setupGlobalButtons() {
  document.addEventListener("click", (event) => {
    const shellSearch = event.target.closest("[data-shell-search]");
    if (shellSearch) {
      openCommandPalette();
      return;
    }

    const popoverAction = event.target.closest("[data-popover-action]");
    if (popoverAction) {
      const action = popoverAction.dataset.popoverAction;
      if (action === "logout") {
        fetch("/auth/logout", { method: "POST" })
          .finally(() => { window.location.href = "/login?next=%2Foperations-view%3Fview%3Dhome"; });
      }

      if (action === "account") {
        openAccountPanel();
      }
      if (action === "select-unit") {
        window.dispatchEvent(new CustomEvent("campex:set-active-unit", { detail: { unitId: popoverAction.dataset.unitId } }));
        closePopover();
      }
      if (action === "copy-location") {
        navigator.clipboard?.writeText(window.location.href).catch(() => {});
        closePopover();
      }
      return;
    }

    const profile = event.target.closest(".cx-profile-trigger, .cx-top-avatar");
    if (profile) {
      const user = shellState.user || {};
      const name = user.nome || user.email || "Usuário Campex";
      const email = user.email || "E-mail não informado";
      const company = organizationName(user);
      const photoUrl = user.avatar_url || user.foto_url || user.photo_url || user.profile_photo_url;
      const profileItems = shellState.authenticated ? [
        { type: "account-header", name, email, company, photoUrl },
        { type: "divider" },
        { label: "Minha conta", href: "/settings/cameras#minha-conta", icon: "users" },
        { label: "Organização", href: "/settings/cameras#cliente", icon: "integrations" },
        { label: "Usuários e permissões", href: "/settings/cameras#usuarios", icon: "users" },
        { label: "Preferências", href: "/settings/cameras#minha-conta", icon: "settings" },
        { type: "divider" },
        { label: "Status do sistema", href: "/local-diagnostics-view", icon: "status" },
        { label: "Ajuda e suporte", href: "/help", icon: "help" },
        { type: "divider" },
        { label: "Sair", action: "logout", icon: "logout" },
      ] : [
        "Entre para acessar dados protegidos.",
        { label: "Entrar", href: `/login?next=${encodeURIComponent(`${window.location.pathname}${window.location.search}${window.location.hash}`)}`, icon: "users" },
      ];
      openPopover(profile, shellState.authenticated ? "Conta" : "Sessão", profileItems);
      return;
    }

    const iconButton = event.target.closest(".cx-icon-button");
    if (iconButton) {
      const label = iconButton.getAttribute("aria-label") || "Menu";
      openPopover(iconButton, label, label.includes("Notifica")
        ? ["Nenhuma notificação nova", { label: "Abrir Eventos", href: "/events", icon: "events" }]
        : [{ label: "Ajuda e suporte", href: "/help", icon: "help" }, { label: "Status do sistema", href: "/local-diagnostics-view", icon: "status" }]);
      return;
    }

    const workspaceSwitcher = event.target.closest(".cx-workspace-switcher");
    if (workspaceSwitcher) {
      const workspace = shellState.workspace || {};
      const organization = workspace.organization || {};
      const units = Array.isArray(workspace.units) ? workspace.units : [];
      const activeUnitId = workspace.activeUnitId || workspace.activeUnit?.id;
      const organizationLabel = organization.nome || organization.name || organizationName();
      const activeUnitLabel = workspace.activeUnit?.nome || workspace.activeUnit?.name || "Unidade principal";
      const unitItems = units.length
        ? units.map((unit) => ({
            label: `${unit.id === activeUnitId ? "✓ " : ""}${unit.nome || unit.name || "Unidade sem nome"}`,
            action: "select-unit",
            unitId: unit.id,
            icon: "integrations",
          }))
        : ["Nenhuma unidade acessível carregada."];
      openPopover(workspaceSwitcher, "Unidade ativa", [
        `${organizationLabel} · ${activeUnitLabel}`,
        { type: "divider" },
        ...unitItems,
        { type: "divider" },
        { label: "Configurar unidades", href: "/settings/cameras#unidades", icon: "settings" },
      ]);
      return;
    }

    const rowMenu = event.target.closest(".cx-row-menu:not([data-open-detail])");
    if (rowMenu) {
      openPopover(rowMenu, "Ações", [{ label: "Copiar referência", action: "copy-location" }, { label: "Ir para Eventos", href: "/events", icon: "events" }]);
      return;
    }

    if (shellState.popover && !event.target.closest(".cx-popover")) closePopover();
  });
}

window.addEventListener("campex:workspace-context", (event) => {
  shellState.workspace = event.detail || shellState.workspace;
  updateWorkspaceSwitcher();
});

function setupKeyboard() {
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openCommandPalette();
      return;
    }

    if (event.key === "Escape") {
      closePopover();
      closeCommandPalette();
      closeAccountPanel();
      closeSidePanels();
      closeDrawer();
    }
  });
}

normalizePrimaryNavigation();
normalizeAccountFooter();
ensureGlobalHeaderTools();
setupActiveNavigation();
setupSidebar();
setupGlobalButtons();
setupKeyboard();
loadShellUser().then(updateIdentity);
