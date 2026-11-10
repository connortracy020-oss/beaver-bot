/* Saved answers live in this browser only (localStorage). No account, and nothing is sent to the server. */
const KEY = "bb-saved", MAX = 60;

export function all() {
  try { const list = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(list) ? list : []; }
  catch (e) { return []; }
}
function write(list) { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX))); return true; } catch (e) { return false; } }
export function has(id) { return all().some(s => s.id === id); }
export function add(item) { const list = all().filter(s => s.id !== item.id); list.unshift(item); return write(list); }
export function remove(id) { return write(all().filter(s => s.id !== id)); }
export function clearAll() { return write([]); }
export function idFor(question, lang) {
  let hash = 0; const text = lang + ":" + question.trim().toLowerCase();
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return "a" + (hash >>> 0).toString(36);
}
