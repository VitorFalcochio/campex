const loginForm = document.querySelector("#loginForm");
const signupForm = document.querySelector("#signupForm");
const loginStatus = document.querySelector("#loginStatus");
const signupStatus = document.querySelector("#signupStatus");
const showSignupButton = document.querySelector("#showSignupButton");
const showLoginButton = document.querySelector("#showLoginButton");
const publicSignupAccess = document.querySelector("#publicSignupAccess");
const googleOAuthButton = document.querySelector("#googleOAuthButton");
const loginPasswordInput = document.querySelector("#loginPasswordInput");
const loginPasswordToggle = document.querySelector("#loginPasswordToggle");
const firstRunPanel = document.querySelector("#firstRunPanel");
const firstRunForm = document.querySelector("#firstRunForm");
const firstRunStatus = document.querySelector("#firstRunStatus");

normalizeLocalHost();

function normalizeLocalHost() {
  if (window.location.hostname !== "0.0.0.0") return;
  const next = new URL(window.location.href);
  next.hostname = "127.0.0.1";
  window.location.replace(next.toString());
}

function safeNext(value) {
  const fallback = "/operations-view?view=home";
  if (!value || !value.startsWith("/") || value.startsWith("//")) return fallback;
  return value;
}

function nextPath() {
  return safeNext(new URLSearchParams(window.location.search).get("next"));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", Accept: "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch (_error) {
      detail = await response.text();
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function configureGoogleOAuthButton() {
  if (!googleOAuthButton) return;
  googleOAuthButton.href = `/auth/oauth/google/start?next=${encodeURIComponent(nextPath())}`;
}

function showSignupMode() {
  if (!signupForm) return;
  loginForm.hidden = true;
  signupForm.hidden = false;
  firstRunPanel.hidden = true;
  if (signupStatus) signupStatus.textContent = "";
  signupForm.querySelector("input[name='nome']")?.focus();
}

function showLoginMode() {
  if (signupForm) signupForm.hidden = true;
  firstRunPanel.hidden = true;
  loginForm.hidden = false;
  loginStatus.textContent = "";
  loginForm.querySelector("input[name='email']")?.focus();
}

function toggleLoginPassword() {
  const showing = loginPasswordInput.type === "text";
  loginPasswordInput.type = showing ? "password" : "text";
  loginPasswordToggle.setAttribute("aria-label", showing ? "Mostrar senha" : "Ocultar senha");
  loginPasswordToggle.setAttribute("aria-pressed", String(!showing));
}

async function login(event) {
  event.preventDefault();
  const data = new FormData(loginForm);
  try {
    await requestJson("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: String(data.get("email") || ""),
        senha: String(data.get("senha") || ""),
      }),
    });
    window.location.href = nextPath();
  } catch (error) {
    loginStatus.textContent = `Não foi possível entrar: ${error.message}`;
  }
}

async function signup(event) {
  event.preventDefault();
  if (!signupForm || !signupStatus) return;
  const data = new FormData(signupForm);
  try {
    const payload = await requestJson("/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        nome: String(data.get("nome") || ""),
        email: String(data.get("email") || ""),
        senha: String(data.get("senha") || ""),
        empresa_nome: String(data.get("empresa_nome") || ""),
      }),
    });
    window.location.href = payload.next || "/operations-view?view=home";
  } catch (error) {
    signupStatus.textContent = `Não foi possível criar conta: ${error.message}`;
  }
}

async function completeFirstRun(event) {
  event.preventDefault();
  const data = new FormData(firstRunForm);
  try {
    const payload = await requestJson("/first-run/complete", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(data.entries())),
    });
    window.location.href = payload.next || nextPath();
  } catch (error) {
    firstRunStatus.textContent = `Não foi possível concluir First Run: ${error.message}`;
  }
}

async function bootstrapLogin() {
  configureGoogleOAuthButton();
  const params = new URLSearchParams(window.location.search);
  if (params.has("oauth_error")) {
    loginStatus.textContent = "Não foi possível concluir o login com Google. Use e-mail e senha ou confirme o acesso com a Campex.";
  }
  try {
    const auth = await requestJson("/auth/status");

    const publicSignupEnabled = Boolean(auth.public_signup);
    if (publicSignupAccess) publicSignupAccess.hidden = !publicSignupEnabled;
    if (showSignupButton) showSignupButton.hidden = !publicSignupEnabled;

    if (auth.authenticated) {
      window.location.replace(nextPath());
      return;
    }
    const firstRun = await requestJson("/first-run/status");
    if (firstRun.available) {
      loginForm.hidden = true;
      if (signupForm) signupForm.hidden = true;
      firstRunPanel.hidden = false;
      firstRunStatus.textContent = firstRun.message || "First Run disponível.";
    }
  } catch (error) {
    loginStatus.textContent = `Autenticação indisponível: ${error.message}`;
  }
}

loginForm?.addEventListener("submit", login);
signupForm?.addEventListener("submit", signup);
firstRunForm?.addEventListener("submit", completeFirstRun);
showSignupButton?.addEventListener("click", showSignupMode);
showLoginButton?.addEventListener("click", showLoginMode);
loginPasswordToggle?.addEventListener("click", toggleLoginPassword);
bootstrapLogin();
