/* Talking to the Beaver Bot server. Questions go in the request body, never in a URL. */

export async function getJSON(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw Object.assign(new Error("request failed"), { status: res.status });
  return res.json();
}

export async function postJSON(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw Object.assign(new Error("request failed"), { status: res.status });
  return res.json();
}

/* Ask a question and read the answer as it streams in. `on` receives (event, data) for:
   status {step}, meta {kind, pages, ...}, delta {t}, done {text}, error {message}. */
export async function ask(body, on, signal) {
  let res;
  try {
    res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  } catch (e) {
    if (e.name === "AbortError") return;
    return on("error", { message: "offline" });
  }
  if (!res.ok || !res.body) return on("error", { message: res.status === 503 ? "busy" : "server" });
  const reader = res.body.getReader(), decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut); buffer = buffer.slice(cut + 2);
        let event = "message", data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) { try { on(event, JSON.parse(data)); } catch (e) { /* skip a malformed event */ } }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") on("error", { message: "offline" });
  }
}

let configPromise;
export function config() { return configPromise || (configPromise = getJSON("/api/config")); }
