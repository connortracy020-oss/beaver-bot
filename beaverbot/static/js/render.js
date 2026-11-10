/* Turns the answer's small markup into elements, a few characters at a time as the answer streams in.

   The markup (docs/answer-layer.md): "+ " starts a step, "- " a list item, "> " a quote from OSU's page,
   "## " a small heading, **bold**, and [n] cites a source. Nothing is ever inserted as HTML: every piece of
   answer text becomes a text node, so page text or a model's output can't inject markup. */
import { h } from "./dom.js";

export class AnswerStream {
  /* citeFor(n) -> the source card number for citation n, or null. onCite(card) is called on a chip click. */
  constructor(out, { citeFor, onCite, citeLabel }) {
    Object.assign(this, { out, citeFor, onCite, citeLabel });
    this.atLineStart = true; this.prefix = ""; this.group = null; this.target = null; this.inline = null;
    this.word = ""; this.marker = null; this.stars = 0; this.bold = false; this.fresh = 0; this.lastCite = null; this.gap = false;
  }

  feed(text) { this.fresh = 0; for (const ch of text) this._char(ch); }
  end() { if (this.atLineStart && this.prefix) this._open("p", this.prefix); this._flush(); }

  _char(ch) {
    if (this.atLineStart) {
      if (ch === "\n") {
        if (this.prefix.trim()) { this._open("p", this.prefix); this._newline(); }
        else { this.group = null; this.gap = true; }
        this.prefix = "";
        return;
      }
      this.prefix += ch;
      const p = this.prefix;
      if (p.length < 2 || (p[0] === "#" && p.length < 3)) return;
      const kind = p.startsWith("+ ") ? "step" : p.startsWith("- ") ? "item" : p.startsWith("> ") ? "quote" : p.startsWith("## ") ? "head" : "p";
      this._open(kind, kind === "p" ? p : p.slice(kind === "head" ? 3 : 2));
      return;
    }
    this._inline(ch);
  }

  _open(kind, rest) {
    this.atLineStart = false; this.prefix = "";
    const wrapTag = { step: "ol", item: "ul", quote: "blockquote" }[kind];
    if (wrapTag) {
      if (!this.group || this.group.kind !== kind) {
        this.group = { kind, el: h(wrapTag + (kind === "quote" ? ".from-page" : "")) };
        this.out.append(this.group.el);
      }
      this.target = h(kind === "quote" ? "p" : "li");
      this.group.el.append(this.target);
    } else {
      this.group = null;
      this.target = h(kind === "head" ? "h3" : "p" + (this.out.childElementCount === 0 ? ".lead" : ""));
      this.out.append(this.target);
    }
    this.gap = false;
    this.inline = this.target; this.bold = false;
    for (const ch of rest) this._inline(ch);
  }

  _newline() { this._flush(); this.atLineStart = true; this.prefix = ""; this.bold = false; }

  _inline(ch) {
    if (ch === "\n") return this._newline();
    if (this.marker !== null) {
      this.marker += ch;
      if (ch === "]") { const m = /^\[(\d+)\]$/.exec(this.marker); const raw = this.marker; this.marker = null; m ? this._cite(Number(m[1])) : this._text(raw); }
      else if (this.marker.length > 5 || !/\d/.test(ch)) { const raw = this.marker; this.marker = null; this.word += raw; }
      return;
    }
    if (ch === "*") {
      if (++this.stars === 2) {
        this.stars = 0; this._flushWord(); this.bold = !this.bold;
        if (this.bold) { this.inline = h("strong"); this.target.append(this.inline); } else this.inline = this.target;
      }
      return;
    }
    if (this.stars) { this.word += "*"; this.stars = 0; }
    if (ch === "[") { this._flushWord(); this.marker = "["; return; }
    if (/\s/.test(ch)) { this._flushWord(); this.inline.append(" "); return; }
    this.word += ch;
  }

  _flushWord() {
    if (!this.word) return;
    const span = h("span.w", this.word);
    span.style.animationDelay = (this.fresh++ * 22) + "ms";
    this.inline.append(span); this.word = "";
  }
  _text(raw) { this.word += raw; }
  _flush() { if (this.marker !== null) { this.word += this.marker; this.marker = null; } if (this.stars) { this.word += "*"; this.stars = 0; } this._flushWord(); }

  _cite(n) {
    this._flushWord();
    const card = this.citeFor(n);
    /* The space typed before a marker isn't wanted: a chip brings its own gap, and a hidden one must not leave
       "word ." behind. */
    const before = this.inline.lastChild;
    if (before && before.nodeType === 3 && !before.nodeValue.trim()) before.remove();
    if (card == null) return;
    /* A chip is shown when the source changes, not after every line that cites the same page. */
    if (this.lastCite === card) return;
    this.lastCite = card;
    const chip = h("button.cite", { type: "button", "aria-label": this.citeLabel(card), onclick: () => this.onCite(card) }, String(card));
    this.target.append(chip);
  }
}

/* The answer as plain words, for copying, sharing and reading aloud. */
export function plainText(markup) {
  return markup.split("\n").map(line => line.replace(/^(\+ |- |> |## )/, m => (m === "> " ? "“" : m === "## " ? "" : "• ")).replace(/\s*\[\d+\]/g, "").replace(/\*\*/g, "")
    .replace(/^“(.*)$/, "“$1”")).join("\n").replace(/\n{3,}/g, "\n\n").trim();
}
