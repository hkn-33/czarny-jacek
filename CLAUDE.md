# CLAUDE.md

Chat replies: Polish unless I write in English. Be terse and direct. Point out flaws and risks; don't praise by default.
Everything written to the repo is in English: code, identifiers, comments, commit messages, docs, specs, ADRs.

## Process
- Large features and new projects: I run the process skills myself (/grill-with-docs, /to-spec, /to-tickets). Don't start building a large feature without a spec.
- When interviewing me (grilling), ask at most 15 questions, most important first. Batch related questions. Stop earlier if the design is clear.
- Small changes: just do them. Don't interview me about a typo.
- Use the tdd skill for logic and bugs. Run the full test suite and review only when I say the work is done.
- If something is ambiguous and a wrong guess is costly, ask. Otherwise state your assumption in one line and proceed.

## Libraries and docs
- Before writing an integration, client or utility, check whether a maintained library or Nuxt module already does it. Don't hand-roll what exists.
- Use Context7 for current library/framework docs instead of relying on memory. Use web search to check what is currently recommended.
- Suggest a library with one line of reasoning (maintenance, popularity, fit) and ask before adding a dependency.
- Web scraping: use Scrapling. Don't write raw requests/BeautifulSoup scrapers.

## Reuse before writing
- Before adding code, search for existing similar code. Extend it instead of creating a near-copy.
- Extract a shared helper/component when a second use appears, not before. No abstractions for a single use.

## Scope and cleanup
- Touch only what the task requires. Don't refactor or reformat adjacent code. Match the repo's existing style.
- Remove everything your change made obsolete: unused imports, variables, functions, files, old code paths you replaced.
- Unrelated dead code: mention it, don't delete it.

## Code style
- Readability over brevity. No clever one-liners, no dense chaining, no cryptic abbreviations. Descriptive names, early returns, small functions.
- Self-documenting: types everywhere (type hints in Python, strict TypeScript).
- Comments only for non-obvious "why". Never comment what the code says.
- No speculative features, config options, or error handling for impossible cases.

## Repo map
- Keep the "Repo map" section of the repo's CLAUDE.md current. When you add, move, rename or delete a folder or a key module, update it in the same change.
- Folder-level only, one line per entry. Don't list individual files.

## Defaults (a repo's own CLAUDE.md overrides these)
- Language: TypeScript, never plain JavaScript. Python for scripts, data, AI/RAG and agents.
- In Node.js/TypeScript use async/await, never .then().
- Apps with a UI: Nuxt + Tailwind CSS, always.
## Repo map
- `czarny_jacek/` — app: vision (card reading), calibration (finds the game on screen), shoe (count), strategy, main (launcher + overlay)
- `templates/` — `ranks/` digital card glyphs, `felt/` rectified physical cards (dealer's felt spot), `felt_anchor.png` (felt text) for finding the game
- `samples/` — author's screenshots (contain casino session id, keep private)
- `tests/` — checks against the samples
- `captures/` — game-area screenshots saved by the app on every table change (test data from live play)
- `docs/screenshots/` — README images (personal data blurred)
