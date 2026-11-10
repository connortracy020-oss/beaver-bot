/* Small DOM helpers and the icon set. Icons are simple line drawings made for this project. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* h("button.chip", {type: "button", onclick}, "Text", child) builds an element without ever using innerHTML,
   so text from the server or the visitor can't become markup. */
export function h(spec, attrs, ...kids) {
  const [tag, ...classes] = spec.split(".");
  const el = document.createElement(tag || "div");
  if (classes.length) el.className = classes.join(" ");
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className += (el.className ? " " : "") + v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "hidden" || k === "disabled" || k === "checked" || k === "readOnly") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  add(el, kids);
  return el;
}
export function add(el, kids) {
  for (const kid of [].concat(kids).flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
export const clear = el => { el.replaceChildren(); return el; };

const PATHS = {
  send: "M12 19V5M5.5 11.5 12 5l6.5 6.5",
  menu: "M4 7h16M4 12h16M4 17h16",
  x: "M6 6l12 12M18 6 6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  chevron: "M9 6l6 6-6 6",
  down: "M6 9l6 6 6-6",
  back: "M15 6l-6 6 6 6",
  external: "M14 5h5v5M19 5l-8 8M11 7H6.5A1.5 1.5 0 0 0 5 8.5v9A1.5 1.5 0 0 0 6.5 19h9a1.5 1.5 0 0 0 1.5-1.5V13",
  sun: "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z",
  sliders: "M5 7h7M16 7h3M5 12h3M12 12h7M5 17h9M18 17h1M14 5v4M10 10v4M16 15v4",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3.5 12h17M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.400 5.6 12 3z",
  bookmark: "M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z",
  share: "M12 15V4M8 7.5 12 4l4 3.500M6 11H5.500A1.500 1.500 0 0 0 4 12.500v6A1.500 1.500 0 0 0 5.500 20h13a1.500 1.500 0 0 0 1.500-1.500v-6A1.500 1.500 0 0 0 18.500 11H18",
  copy: "M9 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM5 15V5a1 1 0 0 1 1-1h10",
  up: "M7 11v9H4.500A.500.500 0 0 1 4 19.500v-8a.500.500 0 0 1 .500-.500H7zm0 0 3.600-6.600A1.800 1.800 0 0 1 14 5.400L13.300 9H18a2 2 0 0 1 2 2.300l-1 6.500A2.500 2.500 0 0 1 16.500 20H7",
  downthumb: "M7 13V4H4.500A.500.500 0 0 0 4 4.500v8a.500.500 0 0 0 .500.500H7zm0 0 3.600 6.600A1.800 1.800 0 0 0 14 18.600L13.300 15H18a2 2 0 0 0 2-2.300l-1-6.500A2.500 2.500 0 0 0 16.500 4H7",
  volume: "M4 10v4h3.500L12 18V6L7.500 10H4zM15.500 9a4 4 0 0 1 0 6M18 6.500a7.500 7.500 0 0 1 0 11",
  stop: "M7 7h10v10H7z",
  flag: "M6 21V4M6 4.500h10.500l-2 3.800 2 3.700H6",
  calendar: "M6 5h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM4 10h16M8.500 3v4M15.500 3v4",
  clock: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 8v4.300l2.800 1.700",
  list: "M9 7h10M9 12h10M9 17h10M5 7h.01M5 12h.01M5 17h.01",
  home: "M4 11.500 12 5l8 6.500M6.500 10v9h11v-9M10 19v-5h4v5",
  heart: "M12 19.500S4.500 15 4.500 9.800A3.800 3.800 0 0 1 12 8a3.800 3.800 0 0 1 7.500 1.800C19.500 15 12 19.500 12 19.500z",
  wallet: "M5 7.500h13a1.500 1.500 0 0 1 1.500 1.500v8.500A1.500 1.500 0 0 1 18 19H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h10.500M15.500 13.300h.01",
  cap: "M3 9.500 12 5l9 4.500-9 4.500-9-4.500zM7 12v4c1.500 1.300 3.200 2 5 2s3.500-.700 5-2v-4M21 9.500v5",
  door: "M7 20V5.500A1.500 1.500 0 0 1 8.500 4h7A1.500 1.500 0 0 1 17 5.500V20M4.500 20h15M13.500 12.500h.01",
  access: "M12 6.200a1.200 1.200 0 1 0 0-2.400 1.200 1.200 0 0 0 0 2.400zM6 8.500l6 1 6-1M12 9.500v4.500M12 14l-3 6M12 14l3 6",
  hands: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6.400 6.400l3.500 3.500M14.100 14.100l3.500 3.500M17.600 6.400l-3.500 3.500M9.900 14.100l-3.500 3.500",
  scale: "M12 4v16M7.500 20h9M5 7.500h14M5 7.500l-2.500 6a2.700 2.700 0 0 0 5 0L5 7.500zM19 7.500l-2.500 6a2.700 2.700 0 0 0 5 0l-2.500-6z",
  laptop: "M6 6h12a1 1 0 0 1 1 1v8.500H5V7a1 1 0 0 1 1-1zM3 18.500h18",
  phone: "M8 3.500h8A1.500 1.500 0 0 1 17.500 5v14A1.500 1.500 0 0 1 16 20.500H8A1.500 1.500 0 0 1 6.500 19V5A1.500 1.500 0 0 1 8 3.500zM11 17.500h2",
  call: "M6.500 4h3l1.500 4-2 1.500a11 11 0 0 0 5.500 5.500l1.500-2 4 1.500v3a1.500 1.500 0 0 1-1.500 1.500A14.500 14.500 0 0 1 5 5.500 1.500 1.500 0 0 1 6.500 4z",
  lock: "M7.500 11V8.500a4.500 4.500 0 0 1 9 0V11M6.500 11h11A1.500 1.500 0 0 1 19 12.500v6A1.500 1.500 0 0 1 17.500 20h-11A1.500 1.500 0 0 1 5 18.500v-6A1.500 1.500 0 0 1 6.500 11z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.500 20a7.500 7.500 0 0 1 15 0",
  search: "M10.500 4a6.500 6.500 0 1 0 0 13 6.500 6.500 0 0 0 0-13zM15.300 15.300 20 20",
  info: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 11v5M12 8h.01",
  alert: "M12 4.500 3.500 19h17L12 4.500zM12 10.500v4M12 16.800h.01",
  sparkle: "M12 4l1.700 4.800L18.500 10.500l-4.800 1.700L12 17l-1.700-4.800L5.500 10.500l4.800-1.700L12 4zM18.500 15.500l.700 1.800 1.800.700-1.800.700-.700 1.800-.700-1.800-1.800-.700 1.800-.700.700-1.800z",
  pin: "M12 21s6.500-5.800 6.500-11A6.500 6.500 0 0 0 5.500 10c0 5.200 6.500 11 6.500 11zM12 7.800a2.200 2.200 0 1 0 0 4.400 2.200 2.200 0 0 0 0-4.400z",
  book: "M5 5.500A1.500 1.500 0 0 1 6.500 4H19v13H6.500A1.500 1.500 0 0 0 5 18.500v-13zM5 18.500A1.500 1.500 0 0 0 6.500 20H19",
  refresh: "M19 6v4.500h-4.500M5 18v-4.500h4.500M18.300 10.500A6.800 6.800 0 0 0 6.300 8M5.700 13.500a6.800 6.800 0 0 0 12 2.500",
  print: "M7.500 8.500V4h9v4.500M7.500 16.500H6A1.500 1.500 0 0 1 4.500 15v-5A1.500 1.500 0 0 1 6 8.500h12a1.500 1.500 0 0 1 1.500 1.500v5a1.500 1.500 0 0 1-1.500 1.500h-1.500M7.500 14h9v6h-9z",
  undo: "M8.500 7 5 10.500 8.500 14M5 10.500h9a5 5 0 0 1 0 10h-3",
  shield: "M12 3.500 5 6v5.500c0 4.200 2.700 7.500 7 9 4.300-1.500 7-4.800 7-9V6l-7-2.500z",
  grid: "M5 5h5.500v5.500H5zM13.500 5H19v5.500h-5.500zM5 13.500h5.500V19H5zM13.500 13.500H19V19h-5.500z",
  form: "M7 3.500h7L18.500 8v11A1.500 1.500 0 0 1 17 20.500H7A1.500 1.500 0 0 1 5.500 19V5A1.500 1.500 0 0 1 7 3.500zM14 3.500V8h4.500M8.500 12.500h7M8.500 16h5",
  swap: "M7 8h12l-3-3M17 16H5l3 3",
  trash: "M5 7h14M9.500 7V4.500h5V7M7 7l.800 12a1.500 1.500 0 0 0 1.500 1.400h5.400a1.500 1.500 0 0 0 1.500-1.400L17 7M10 11v5.500M14 11v5.500",
  tool: "M14.500 5.500a4 4 0 0 0-5.200 5.200L4.500 15.500v4h4l4.800-4.800a4 4 0 0 0 5.200-5.200L16 12l-2.500-.500L13 9l2.500-2.500-1-1z",
  bolt: "M13 3.500 5.500 13.500H11L10 20.500l8-10.500h-5.500L13 3.500z",
};
export function icon(name, cls = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "ico" + (cls ? " " + cls : ""));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", PATHS[name] || PATHS.info);
  svg.append(path);
  return svg;
}

export const reducedMotion = () => document.documentElement.dataset.motion === "reduce" || matchMedia("(prefers-reduced-motion: reduce)").matches;
export const sleep = ms => new Promise(r => setTimeout(r, reducedMotion() ? 0 : ms));
export function replay(el, cls, ms = 600) {
  if (!el) return;
  el.classList.remove(cls); void el.getBoundingClientRect(); el.classList.add(cls);
  clearTimeout(el["_t" + cls]); el["_t" + cls] = setTimeout(() => el.classList.remove(cls), ms);
}

const MONTHS = { en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                 es: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"] };
export function parseDate(iso) { const [y, m, d] = iso.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); }
export function shortDate(iso, lang = "en") {
  if (!iso) return "";
  const d = parseDate(iso), m = MONTHS[lang] || MONTHS.en;
  return lang === "es" ? `${d.getDate()} ${m[d.getMonth()]} ${d.getFullYear()}` : `${m[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}
export const money = n => (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;
