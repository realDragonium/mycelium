(() => {
  "use strict";
  // The ranking is pure, so a test can load this file outside a browser and
  // call it.
  const AROUND = 60;

  // Cut at spaces so an excerpt starts and ends on whole words.
  const excerpt = (text, at, length) => {
    let start = Math.max(0, at - AROUND);
    let end = Math.min(text.length, at + length + AROUND);
    if (start > 0) {
      const space = text.indexOf(" ", start);
      start = space >= 0 && space < at ? space + 1 : at;
    }
    if (end < text.length) {
      const space = text.lastIndexOf(" ", end);
      end = space >= at + length ? space : at + length;
    }
    return (start ? "… " : "") + text.slice(start, end) + (end < text.length ? " …" : "");
  };

  // The forms a word may take as a whole word: itself, its regular plural,
  // and, for a plural, its singular. No stemming beyond that.
  const formsOf = (word) => {
    const forms = new Set([word]);
    if (word.length >= 3) {
      forms.add(word + "s").add(word + "es");
      if (word.endsWith("y")) forms.add(word.slice(0, -1) + "ies");
    }
    if (word.length > 3 && word.endsWith("s")) {
      forms.add(word.slice(0, -1));
      if (word.endsWith("es")) forms.add(word.slice(0, -2));
      if (word.endsWith("ies")) forms.add(word.slice(0, -3) + "y");
    }
    return [...forms].sort((a, b) => b.length - a.length);
  };

  // How well a word occurs in a text: as a whole word, in any of its forms, 3;
  // at the start of a word 2; inside one 1, only for a word of three letters
  // or more; not at all 0.
  const patterns = new Map();
  const patternsOf = (word) => {
    if (!patterns.has(word)) {
      const quote = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const edge = "[^\\p{L}\\p{N}]";
      const forms = formsOf(word);
      patterns.set(word, {
        forms,
        exact: new RegExp(`(?:^|${edge})(${quote(word)})(?=$|${edge})`, "giu"),
        whole: new RegExp(`(?:^|${edge})(${forms.map(quote).join("|")})(?=$|${edge})`, "giu"),
        start: new RegExp(`(?:^|${edge})(${quote(word)})`, "giu"),
      });
    }
    return patterns.get(word);
  };
  // A global pattern carries on from where `test` last stopped.
  const finds = (pattern, text) => {
    pattern.lastIndex = 0;
    return pattern.test(text);
  };
  // Where each occurrence of a word at a level starts and ends; a whole word
  // may be one of its other forms.
  const occurrences = (text, word, level) => {
    if (level === 1) {
      const lower = text.toLowerCase();
      const found = [];
      for (let at = lower.indexOf(word); at >= 0; at = lower.indexOf(word, at + word.length)) {
        found.push([at, at + word.length]);
      }
      return found;
    }
    const { whole, start } = patternsOf(word);
    const pattern = level === 3 ? whole : start;
    pattern.lastIndex = 0;
    return [...text.matchAll(pattern)].map((m) => [m.index + m[0].length - m[1].length, m.index + m[0].length]);
  };
  const INSIDE = 3;
  const fit = (text, word) => {
    const { forms, whole, start } = patternsOf(word);
    const lower = text.toLowerCase();
    if (!forms.some((form) => lower.includes(form))) return 0;
    if (finds(whole, text)) return 3;
    if (finds(start, text)) return 2;
    return word.length >= INSIDE && lower.includes(word) ? 1 : 0;
  };
  // A query of several words found as written, from the start of a word.
  const holds = (text, phrase) => fit(text, phrase) >= 2;

  // A match's worth as one number: its quality first, then where it is (a
  // title or another name 2, a heading 1, text 0), then whether the word is
  // there as written rather than in another form. A match inside a word
  // counts as one in text wherever it is.
  const worth = (text, word, field) => {
    const level = fit(text, word);
    if (!level) return 0;
    return (level * 3 + (level > 1 ? field : 0)) * 2 + (level < 3 || finds(patternsOf(word).exact, text) ? 1 : 0);
  };
  const levelOf = (value) => Math.floor(value / 6);
  const fieldOf = (value) => Math.floor(value / 2) % 3;
  const exactOf = (value) => value % 2;
  const total = (values, part) => values.reduce((sum, value) => sum + part(value), 0);
  const AS_A_NAME = (3 * 3 + 2) * 2;

  const inSection = (section, word) =>
    Math.max(worth(section.heading, word, 1), worth(section.text, word, 0));
  const spaced = (text) => text.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  const tokens = (text) => text.toLowerCase().split(/[\s_-]+/).filter(Boolean);
  // A name as one word, as it is written in code: "Usage score" as "usagescore".
  const squash = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
  const SQUASHED_PREFIX = 4;
  // The forms a name may take squashed, given the query squashed; a lone "s"
  // typed as a word of its own is the start of one, not a plural.
  const squashedForms = (squashed, said) => {
    const last = said.length ? said[said.length - 1].length : 0;
    return formsOf(squashed).filter((form) => form.length >= squashed.length || squashed.length - form.length < last);
  };
  // How a name matches the query squashed: as the whole name 2, as its start 1.
  const asSquashed = (name, squashed, forms) => {
    const flat = squash(name);
    return forms.includes(flat) ? 2 : squashed.length >= SQUASHED_PREFIX && flat.startsWith(squashed) ? 1 : 0;
  };
  // A name that is the query, word for word, in any of the words' forms and
  // whether words are joined by spaces, "_" or "-".
  const isNamed = (name, said) => {
    const parts = tokens(name);
    return parts.length === said.length && parts.every((part, at) => formsOf(said[at]).includes(part));
  };

  // Every word must occur somewhere in the page; a concept's other names count
  // as its title. The whole query as written counts first: as a whole title
  // or name 4, in one 3, in a heading 2, in text 1. The excerpt comes from the
  // section holding it, otherwise from the one where the words occur best. A
  // name that explains the match better than the title is given as `alias`.
  const match = (entry, words, query, phrase, squashed, forms) => {
    const names = [entry.title, ...(entry.aliases || [])];
    const said = tokens(query);
    const squashedAs = Math.max(...names.map((name) => asSquashed(name, squashed, forms)));
    const named = squashedAs === 2 || names.some((name) => isNamed(name, said));
    const prefixed = squashedAs === 1;
    const byName = words.map((word) => Math.max(...names.map((name) => worth(name, word, 2))));
    const found = words.map((word, at) =>
      Math.max(byName[at], ...entry.sections.map((s) => inSection(s, word))),
    );
    // Only a query that is a name, or the start of one, with its words joined
    // finds a page without holding its words.
    const unjoined = found.some((value) => !value);
    if (unjoined && !named && !prefixed) return null;
    const best = unjoined ? found.map((value) => Math.max(value, AS_A_NAME)) : found;
    const explains = (name) =>
      (spaced(name) === query
        ? 3
        : isNamed(name, said) || asSquashed(name, squashed, forms) === 2
          ? 2
          : (phrase && holds(name, phrase)) || asSquashed(name, squashed, forms)
            ? 1
            : 0) * 1000 +
      words.reduce((sum, word) => sum + worth(name, word, 2), 0);
    const shown = names.slice(1).reduce((top, name) => (explains(name) > explains(top) ? name : top), entry.title);
    const hit = {
      words: unjoined ? said : words,
      quality: total(best, levelOf),
      field: total(best, fieldOf),
      exact: total(best, exactOf),
      // How many words the title itself matches as well as any other place.
      byTitle: words.filter((word, at) => levelOf(best[at]) > 1 && worth(entry.title, word, 2) >= best[at]).length,
      // Every word starts a word of the title or another name.
      titled: named || prefixed || byName.every((value) => levelOf(value) >= 2),
      nameQuality: named
        ? said.length * 3
        : prefixed
          ? Math.max(said.length * 2, total(byName, levelOf))
          : total(byName, levelOf),
      nameExact: total(byName, exactOf),
      ownTitle: words.filter((word, at) => worth(entry.title, word, 2) >= byName[at]).length,
      // Some word is found only inside a word, and the page not by its name.
      inside: !named && !prefixed && best.some((value) => levelOf(value) === 1),
      ...(shown !== entry.title && { alias: shown }),
      ...(squashedAs && { squashed }),
    };
    if (named) return { phrase: 4, ...hit };
    if (phrase && names.some((name) => holds(name, phrase))) return { phrase: 3, ...hit };
    const inHeading = phrase && entry.sections.find((s) => holds(s.heading, phrase));
    if (inHeading) {
      return { phrase: 2, ...hit, anchor: inHeading.anchor, detail: inHeading.heading };
    }
    const inText = phrase && entry.sections.find((s) => holds(s.text, phrase));
    if (inText) {
      const [at, end] = occurrences(inText.text, phrase, fit(inText.text, phrase))[0];
      return { phrase: 1, ...hit, anchor: inText.anchor, detail: excerpt(inText.text, at, end - at) };
    }
    const rest = words.filter((word, at) => byName[at] < best[at]);
    if (!rest.length || !entry.sections.length) return { phrase: 0, ...hit };
    const sum = (s) => rest.reduce((all, word) => all + inSection(s, word), 0);
    const section = entry.sections.reduce((top, s) => (sum(s) > sum(top) ? s : top));
    const textWords = rest.filter((word) => worth(section.text, word, 0) >= worth(section.heading, word, 1) && fit(section.text, word));
    if (!textWords.length) return { phrase: 0, ...hit, anchor: section.anchor, detail: section.heading };
    const [at, end] = textWords
      .map((word) => occurrences(section.text, word, fit(section.text, word))[0])
      .reduce((first, found) => (found[0] < first[0] ? found : first));
    return { phrase: 0, ...hit, anchor: section.anchor, detail: excerpt(section.text, at, end - at) };
  };

  // How often the words occur as whole words in a page's headings and text.
  const often = (entry, words) =>
    entry.sections.reduce(
      (sum, s) => sum + words.reduce((n, word) => n + occurrences(s.heading, word, 3).length + occurrences(s.text, word, 3).length, 0),
      0,
    );

  const unwritten = (a, b) => Boolean(a.entry.stub) - Boolean(b.entry.stub);
  // Among matches by name: how well the names match, the word as written
  // before another form of it, the title before another name, a written page
  // before one not written yet, then the shorter title. A query that is
  // exactly a page's name puts a written page first even where only its other
  // name is that query.
  const byName = (a, b) =>
    b.nameQuality - a.nameQuality ||
    b.nameExact - a.nameExact ||
    (a.phrase === 4 && unwritten(a, b)) ||
    b.ownTitle - a.ownTitle ||
    unwritten(a, b) ||
    a.entry.title.length - b.entry.title.length;
  // Among the rest: how well the words match, then where, a title or another
  // name before a heading before text; the word as written, the title, a
  // written page, then the page that holds the words more often.
  const byText = (a, b) =>
    b.quality - a.quality ||
    b.field - a.field ||
    b.exact - a.exact ||
    b.byTitle - a.byTitle ||
    unwritten(a, b) ||
    b.often - a.often;
  // The whole query as a name, then held by a name; then pages whose names
  // hold every word, at least at the start of a word, so a title shows while
  // it is being typed; then the whole query in a heading, in text, and the
  // words apart.
  const tierOf = (hit) => (hit.phrase >= 3 ? hit.phrase + 2 : hit.titled ? 4 : hit.phrase + 1);

  // A page found by its name opens at its top, so the excerpt is how it
  // starts.
  const opening = (entry) => {
    const first = entry.sections.find((s) => s.text);
    return first ? excerpt(first.text, 0, AROUND) : "";
  };

  const ranked = (entries, query) => {
    const said = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const words = [...new Set(said)];
    const whole = said.join(" ");
    const phrase = said.length > 1 ? whole : "";
    const squashed = squash(whole);
    const forms = squashedForms(squashed, tokens(whole));
    const found = [];
    for (const entry of entries) {
      const hit = words.length && match(entry, words, whole, phrase, squashed, forms);
      if (hit) {
        const tier = tierOf(hit);
        const { anchor, detail, ...rest } = hit;
        const place = tier >= 4 ? { detail: opening(entry) } : { anchor, detail };
        found.push({ entry, tier, ...rest, ...place, often: tier < 4 ? often(entry, words) : 0 });
      }
    }
    // Matches inside a word are kept only when nothing better is found.
    const shown = found.some((hit) => !hit.inside) ? found.filter((hit) => !hit.inside) : found;
    return shown.sort(
      (a, b) =>
        b.tier - a.tier ||
        (a.tier >= 4 ? byName : byText)(a, b) ||
        a.entry.title.localeCompare(b.entry.title),
    );
  };

  // The entries a query finds, best first, each with the words it matched by,
  // the anchor and the excerpt to show. A query that finds nothing as typed is
  // tried as an identifier's words: "_" and "-" read as spaces and camel case
  // split, so it must be given before it is lowercased.
  const rank = (entries, query) => {
    const typed = query.trim();
    const found = ranked(entries, typed);
    const apart = typed
      .replace(/(\p{Lu})(\p{Lu}\p{Ll})/gu, "$1 $2")
      .replace(/([\p{Ll}\p{N}])(\p{Lu})/gu, "$1 $2")
      .replace(/[_-]+/g, " ");
    if (!weak(found) || apart.toLowerCase() === typed.toLowerCase()) return found;
    const split = ranked(entries, apart);
    return weak(split) && found.length ? found : split;
  };
  // Nothing found, or only matches inside words.
  const weak = (found) => !found.length || found[0].inside;

  // Where to mark the matched words in a text: whole words and word starts,
  // as a hit is counted, never a word of one letter; for a hit found only
  // inside words, those too. A word is marked where it occurs best, so "red"
  // marks the word itself and not "re" of "redo" beside it. A name matched
  // with its words joined is marked as far as the query reaches into it.
  const marks = (text, words, squashed = "", inside = false) => {
    if (text.toLowerCase().length !== text.length) return [];
    const spans = [];
    for (const word of words) {
      const level = word.length >= 2 ? fit(text, word) : 0;
      if (level >= 2 || (level === 1 && inside)) spans.push(...occurrences(text, word, level));
    }
    const flat = squashed ? squash(text) : "";
    if (flat && formsOf(squashed).includes(flat)) {
      spans.push([0, text.length]);
    } else if (flat.startsWith(squashed) && squashed.length >= SQUASHED_PREFIX) {
      let seen = 0;
      let start = -1;
      for (let at = 0; at < text.length && seen < squashed.length; at++) {
        if (squash(text[at])) {
          if (start < 0) start = at;
          if (++seen === squashed.length) spans.push([start, at + 1]);
        }
      }
    }
    spans.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    const merged = [];
    for (const [start, end] of spans) {
      const last = merged[merged.length - 1];
      if (last && start <= last[1]) last[1] = Math.max(last[1], end);
      else merged.push([start, end]);
    }
    return merged;
  };

  // Edits between two texts, counting a swap of neighbours as one; anything
  // over `most` is given as `most + 1`.
  const edits = (a, b, most) => {
    if (Math.abs(a.length - b.length) > most) return most + 1;
    let before = null;
    let row = Array.from({ length: b.length + 1 }, (_, at) => at);
    for (let i = 1; i <= a.length; i++) {
      const next = [i];
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        let value = Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + cost);
        if (before && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
          value = Math.min(value, before[j - 2] + 1);
        }
        next.push(value);
      }
      if (Math.min(...next) > most) return most + 1;
      before = row;
      row = next;
    }
    return Math.min(row[b.length], most + 1);
  };
  const MAX_SUGGESTIONS = 3;
  // For a query that finds nothing: the names one edit from it, or two for a
  // query longer than six characters, closest first, at most one per page.
  const suggest = (entries, query) => {
    const typed = spaced(query);
    const flat = squash(query);
    if (!flat) return [];
    const most = typed.length <= 6 ? 1 : 2;
    const close = [];
    for (const entry of entries) {
      let best = null;
      for (const name of [entry.title, ...(entry.aliases || [])]) {
        const apart = Math.min(edits(typed, spaced(name), most), edits(flat, squash(name), most));
        if (apart <= most && (!best || apart < best.apart)) best = { entry, name, apart };
      }
      if (best) close.push(best);
    }
    return close
      .sort((a, b) => a.apart - b.apart || unwritten(a, b) || a.name.localeCompare(b.name))
      .slice(0, MAX_SUGGESTIONS)
      .map(({ entry, name }) => ({ entry, name }));
  };

  // Every word of the index with how often it occurs, built on the first
  // query that needs it.
  const vocabularies = new WeakMap();
  const vocabularyOf = (entries) => {
    let known = vocabularies.get(entries);
    if (known) return known;
    const counts = new Map();
    const add = (text) => {
      for (const [word] of (text || "").toLowerCase().matchAll(/[\p{L}\p{N}]+/gu)) {
        counts.set(word, (counts.get(word) || 0) + 1);
      }
    };
    for (const entry of entries) {
      add(entry.title);
      for (const name of entry.aliases || []) add(name);
      for (const section of entry.sections) {
        add(section.heading);
        add(section.text);
      }
    }
    const sorted = [...counts.keys()].sort();
    const byLength = new Map();
    for (const word of sorted) {
      if (!byLength.has(word.length)) byLength.set(word.length, []);
      byLength.get(word.length).push(word);
    }
    known = { counts, sorted, byLength };
    vocabularies.set(entries, known);
    return known;
  };
  const startsSome = (sorted, word) => {
    let low = 0;
    let high = sorted.length;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (sorted[middle] < word) low = middle + 1;
      else high = middle;
    }
    return low < sorted.length && sorted[low].startsWith(word);
  };
  const MIN_CORRECTED = 4;
  const MIN_CORRECTED_OVER_INSIDE = 5;
  // The query with each word the index does not know, as a word, a form of
  // one or the start of one, replaced by the nearest word it does: one edit
  // away, or two for a word longer than seven letters; the more frequent, then
  // the first alphabetically, of equally near words. Null when no word is
  // replaced.
  const correct = (entries, query) => {
    const { counts, sorted, byLength } = vocabularyOf(entries);
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean).map((word) => {
      if (
        word.length < MIN_CORRECTED ||
        !/^[\p{L}\p{N}]+$/u.test(word) ||
        formsOf(word).some((form) => counts.has(form)) ||
        startsSome(sorted, word)
      ) {
        return { word, changed: false };
      }
      const most = word.length <= 7 ? 1 : 2;
      let best = null;
      let nearest = most + 1;
      for (let length = word.length - most; length <= word.length + most; length++) {
        for (const other of byLength.get(length) || []) {
          const apart = edits(word, other, most);
          const better =
            apart < nearest ||
            (apart === nearest && (counts.get(other) - counts.get(best) || (other < best ? 1 : 0)) > 0);
          if (apart <= most && better) {
            best = other;
            nearest = apart;
          }
        }
      }
      return best ? { word: best, changed: true } : { word, changed: false };
    });
    return words.some(({ changed }) => changed) ? { query: words.map(({ word }) => word).join(" "), words } : null;
  };

  // What a query shows: what it finds; failing that, or with only matches
  // inside words, what the query corrected finds better, as `corrected`;
  // failing that, the names close to it.
  const lookup = (entries, query) => {
    const found = rank(entries, query);
    if (!weak(found)) return { found, corrected: null, suggested: [] };
    const corrected = correct(entries, query);
    const instead = corrected ? rank(entries, corrected.query) : [];
    // A short fragment that matches inside words was probably typed as a
    // fragment: "ment" should show its matches, not results for "menu".
    const typed = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const fragment =
      found.length > 0 &&
      corrected !== null &&
      corrected.words.some(({ changed }, at) => changed && typed[at].length < MIN_CORRECTED_OVER_INSIDE);
    if (instead.length && !fragment && (!found.length || !weak(instead))) {
      return { found: instead, corrected, suggested: [] };
    }
    return { found, corrected: null, suggested: found.length ? [] : suggest(entries, query) };
  };

  // What the live status says of a list of results.
  const statusOf = (found, shown, suggested, corrected = "", typed = "") => {
    if (found) {
      return (corrected ? `No results for ${typed}. Showing results for ${corrected}. ` : "") +
        plural(found) + (shown < found ? `, showing the first ${shown}` : "") + ". Use the arrow keys to choose one.";
    }
    if (!suggested.length) return "Nothing found.";
    const names = suggested.map(({ name }) => name);
    const listed = names.length > 1 ? names.slice(0, -1).join(", ") + " or " + names[names.length - 1] : names[0];
    return `Nothing found. Did you mean ${listed}? Use the arrow keys to choose one.`;
  };
  const plural = (n) => `${n} ${n === 1 ? "result" : "results"}`;

  if (typeof module === "object" && module.exports) {
    module.exports = { rank, marks, suggest, correct, lookup, statusOf, vocabularyOf };
    return;
  }

  const root = document.currentScript.dataset.root || "";

  // A flow step inside a folded group is hidden until its group opens. A link
  // to it leads to the group without the script; with it, to the step.
  for (const link of document.querySelectorAll("a[data-step]")) {
    link.setAttribute("href", "#" + link.dataset.step);
  }
  const unfold = (hash) => {
    let target = null;
    // A fragment that is not valid percent-encoding names nothing.
    try {
      target = hash.length > 1 && document.getElementById(decodeURIComponent(hash.slice(1)));
    } catch { return null; }
    let opened = false;
    for (let fold = target && target.parentElement.closest("details"); fold;
      fold = fold.parentElement.closest("details")) {
      if (!fold.open) opened = fold.open = true;
    }
    return opened && target;
  };
  const unfoldAddress = () => {
    const target = unfold(location.hash);
    if (target) target.scrollIntoView();
  };
  addEventListener("hashchange", unfoldAddress);
  unfoldAddress();
  // Opened before the browser follows the link, so it lands on a visible step
  // even when the address already ends in it.
  document.addEventListener("click", (event) => {
    const link = event.target.closest && event.target.closest('a[href^="#"]');
    if (link) unfold(link.getAttribute("href"));
  });

  // The sidebar scrolls on its own; keep the current page in view.
  const sidebar = document.querySelector(".sidebar");
  const current = sidebar && sidebar.querySelector('a[aria-current="page"]');
  if (current && sidebar.scrollHeight > sidebar.clientHeight) {
    const top = current.offsetTop - sidebar.offsetTop;
    if (top + current.offsetHeight > sidebar.clientHeight) {
      sidebar.scrollTop = top - sidebar.clientHeight / 3;
    }
  }

  // With the script a button folds the sidebar on a narrow screen, in place
  // of the checkbox that does it without one.
  const toggle = document.querySelector(".sidebar-button");
  const checkbox = document.getElementById("sidebar-toggle");
  if (toggle && sidebar) {
    toggle.setAttribute("aria-expanded", String(Boolean(checkbox && checkbox.checked)));
    for (const fallback of document.querySelectorAll(".sidebar-toggle, .sidebar-label")) fallback.remove();
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      toggle.setAttribute("aria-expanded", String(toggle.getAttribute("aria-expanded") !== "true"));
    });
    // The search's own Escape is marked as handled.
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (toggle.getAttribute("aria-expanded") !== "true" || !toggle.getClientRects().length) return;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
      event.preventDefault();
    });
  }

  // The contents list marks the section being read, in both of its copies.
  const contents = [...document.querySelectorAll('.contents a[href^="#"]')]
    .map((link) => [link, document.getElementById(decodeURIComponent(link.hash.slice(1)))])
    .filter(([, heading]) => heading);
  if (contents.length) {
    let pending = false;
    const mark = () => {
      pending = false;
      const line = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) + 8;
      let reading = null;
      for (const [, heading] of contents) {
        if (heading.getBoundingClientRect().top <= line) reading = heading;
      }
      if (innerHeight + scrollY >= document.documentElement.scrollHeight - 2) {
        reading = contents[contents.length - 1][1];
      }
      for (const [link, heading] of contents) {
        if (heading === reading) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
    };
    addEventListener("scroll", () => {
      if (!pending) {
        pending = true;
        requestAnimationFrame(mark);
      }
    }, { passive: true });
    mark();
  }

  // A table box takes focus to be scrolled only when there is something to
  // scroll.
  const tables = document.querySelectorAll(".table-scroll");
  const fitTables = () => {
    for (const box of tables) box.tabIndex = box.scrollWidth > box.clientWidth ? 0 : -1;
  };
  if (tables.length) {
    fitTables();
    addEventListener("resize", fitTables);
  }

  const search = document.querySelector(".search");
  const input = document.getElementById("search");
  const panel = document.getElementById("search-panel");
  const count = document.getElementById("search-count");
  const results = document.getElementById("search-results");
  const status = document.getElementById("search-status");
  const entries = window.SITE_SEARCH || [];
  if (!search || !input || !panel || !count || !results || !status) return;
  search.hidden = false;
  const MAX_RESULTS = 20;
  const MIN_LENGTH = 2;

  // The matched words in <mark>, built as nodes so no text is read as markup.
  const highlighted = (text, words, squashed, inside) => {
    const out = document.createDocumentFragment();
    let position = 0;
    for (const [start, end] of marks(text, words, squashed, inside)) {
      if (start > position) out.append(text.slice(position, start));
      const mark = document.createElement("mark");
      mark.textContent = text.slice(start, end);
      out.append(mark);
      position = end;
    }
    out.append(text.slice(position));
    return out;
  };

  let selected = -1;
  const options = () => [...results.querySelectorAll('[role="option"]:not([aria-disabled])')];
  const select = (index) => {
    const all = options();
    selected = index;
    all.forEach((option, at) => option.setAttribute("aria-selected", String(at === index)));
    if (all[index]) {
      input.setAttribute("aria-activedescendant", all[index].id);
      all[index].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };
  const close = () => {
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    select(-1);
    status.textContent = "";
  };

  const markStub = (link) => {
    link.className = "stub";
    const tag = document.createElement("span");
    tag.className = "search-tag";
    tag.textContent = "not written yet";
    link.append(" ", tag);
  };
  const option = (id) => {
    const item = document.createElement("li");
    item.id = id;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", "false");
    return item;
  };
  const note = (id) => {
    const item = option(id);
    item.className = "search-none";
    item.setAttribute("aria-disabled", "true");
    item.removeAttribute("aria-selected");
    return item;
  };
  // The stylesheet is shared with pages that must not change, so these few
  // styles are set here.
  const muted = (text) => {
    const label = document.createElement("span");
    label.style.fontWeight = "400";
    label.style.color = "var(--muted)";
    label.textContent = text;
    return label;
  };

  const show = (all = false) => {
    const query = input.value.trim();
    results.replaceChildren();
    results.scrollTop = 0;
    select(-1);
    if (query.length < MIN_LENGTH) {
      close();
      return;
    }
    const { found, corrected, suggested } = lookup(entries, query);
    if (corrected) {
      const line = note("search-corrected");
      // Naming the query as typed says the word is not on the site, which a
      // bare "showing results for" would pass off as a typing mistake.
      line.append("No results for " + query.trim() + ". Showing results for");
      for (const { word, changed } of corrected.words) {
        if (!changed) {
          line.append(" " + word);
          continue;
        }
        const strong = document.createElement("strong");
        strong.style.color = "var(--text)";
        strong.textContent = word;
        line.append(" ", strong);
      }
      results.append(line);
    }
    const shown = all ? found.length : Math.min(found.length, MAX_RESULTS);
    found.slice(0, shown).forEach(({ entry, words, alias, anchor, detail, squashed, inside }, index) => {
      const item = option("search-result-" + index);
      const link = document.createElement("a");
      link.href = root + entry.href + (anchor ? "#" + encodeURIComponent(anchor) : "");
      link.tabIndex = -1;
      link.append(highlighted(entry.title, words, squashed, inside));
      if (entry.stub) markStub(link);
      if (alias) {
        const other = document.createElement("span");
        other.className = "search-detail";
        other.append("also called: ", highlighted(alias, words, squashed, inside));
        link.append(other);
      }
      if (detail) {
        const text = document.createElement("span");
        text.className = "search-detail";
        text.append(highlighted(detail, words, "", inside));
        link.append(text);
      }
      item.append(link);
      results.append(item);
    });
    if (shown < found.length) {
      const item = option("search-show-all");
      item.className = "search-more";
      const button = document.createElement("button");
      button.type = "button";
      button.tabIndex = -1;
      button.textContent = `Show all ${found.length}`;
      // The button is gone once the list is redrawn, so a click that bubbled
      // on would read as one outside the search and close it.
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        show(true);
        select(shown);
        input.focus();
      });
      item.append(button);
      results.append(item);
    }
    if (!found.length) {
      const none = note("search-none");
      none.textContent = "Nothing found.";
      results.append(none);
    }
    suggested.forEach(({ entry, name }, index) => {
      const item = option("search-suggestion-" + index);
      const link = document.createElement("a");
      link.href = root + entry.href;
      link.tabIndex = -1;
      link.append(muted("Did you mean: "), name);
      if (entry.stub) markStub(link);
      item.append(link);
      results.append(item);
    });
    count.textContent = !found.length
      ? ""
      : shown < found.length
        ? `Showing ${shown} of ${found.length}`
        : plural(found.length);
    count.hidden = !found.length;
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
    status.textContent = statusOf(found.length, shown, suggested, corrected ? corrected.query : "", query.trim());
  };

  input.addEventListener("input", () => show());
  input.addEventListener("focus", () => show());
  input.addEventListener("keydown", (event) => {
    const all = options();
    // The first Escape closes the results and keeps the query; the next one
    // clears it.
    if (event.key === "Escape") {
      if (!panel.hidden) close();
      else input.value = "";
      event.preventDefault();
    } else if (event.key === "ArrowDown" && all.length) {
      if (panel.hidden) show();
      select(Math.min(selected + 1, all.length - 1));
      event.preventDefault();
    } else if (event.key === "ArrowUp" && all.length) {
      select(Math.max(selected - 1, -1));
      event.preventDefault();
    } else if (event.key === "Enter" && !panel.hidden && all.length) {
      all[Math.max(selected, 0)].querySelector("a, button").click();
      event.preventDefault();
    }
  });
  // A result on this same page changes only the address; close over it.
  results.addEventListener("click", (event) => {
    if (event.target.closest("a")) close();
  });
  panel.addEventListener("mousedown", (event) => event.preventDefault());
  search.addEventListener("focusout", (event) => {
    if (!event.relatedTarget || !search.contains(event.relatedTarget)) close();
  });
  document.addEventListener("click", (event) => {
    if (!search.contains(event.target)) close();
  });
  // A page restored by the back button keeps its last state.
  addEventListener("pageshow", (event) => {
    if (event.persisted) close();
  });

  document.addEventListener("keydown", (event) => {
    const typing = event.target.closest?.("input, textarea, select, [contenteditable]");
    if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      input.focus();
      input.select();
    }
  });
})();
