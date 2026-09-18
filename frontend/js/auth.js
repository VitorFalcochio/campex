const USERS_KEY = "campex.auth.users";
const SESSION_KEY = "campex.auth.session";

function readJson(key, fallback) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "");
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function validateName(name) {
  return String(name || "").trim().length >= 2;
}

function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizeEmail(email));
}

function validatePassword(password) {
  return String(password || "").length >= 6;
}

function randomSalt() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function hashPassword(password, salt) {
  const payload = new TextEncoder().encode(`${salt}:${password}`);
  const digest = await crypto.subtle.digest("SHA-256", payload);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function publicUser(user) {
  return {
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role,
    created_at: user.created_at,
  };
}

export function listLocalUsers() {
  const users = readJson(USERS_KEY, []);
  return Array.isArray(users) ? users : [];
}

export function getCurrentUser() {
  const session = readJson(SESSION_KEY, null);
  if (!session?.user_id) return null;
  const user = listLocalUsers().find((item) => item.id === session.user_id);
  return user ? publicUser(user) : null;
}

export async function createLocalAccount({ name, email, password }) {
  const normalizedEmail = normalizeEmail(email);
  if (!validateName(name)) {
    throw new Error("Informe um nome com pelo menos 2 caracteres.");
  }
  if (!validateEmail(normalizedEmail)) {
    throw new Error("Informe um email válido.");
  }
  if (!validatePassword(password)) {
    throw new Error("A senha precisa ter pelo menos 6 caracteres.");
  }

  const users = listLocalUsers();
  if (users.some((user) => user.email === normalizedEmail)) {
    throw new Error("Já existe uma conta com este email.");
  }

  const salt = randomSalt();
  const now = new Date().toISOString();
  const user = {
    id: `usr_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
    name: String(name).trim(),
    email: normalizedEmail,
    role: "operator",
    password_salt: salt,
    password_hash: await hashPassword(password, salt),
    created_at: now,
  };
  writeJson(USERS_KEY, [...users, user]);
  writeJson(SESSION_KEY, { user_id: user.id, signed_in_at: now });
  return publicUser(user);
}

export async function signInLocal({ email, password }) {
  const normalizedEmail = normalizeEmail(email);
  const user = listLocalUsers().find((item) => item.email === normalizedEmail);
  if (!user) {
    throw new Error("Email ou senha inválidos.");
  }
  const passwordHash = await hashPassword(password, user.password_salt);
  if (passwordHash !== user.password_hash) {
    throw new Error("Email ou senha inválidos.");
  }
  writeJson(SESSION_KEY, { user_id: user.id, signed_in_at: new Date().toISOString() });
  return publicUser(user);
}

export function signOutLocal() {
  localStorage.removeItem(SESSION_KEY);
}
