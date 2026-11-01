# 0009 — Source-available licensing and contribution rights

- Status: accepted by the owner — **pending legal review**
- Date: 2026-11-01

## Context

The repository became public on 2026-11-01. It was published under the Apache License 2.0 and, the
same day, the licence was replaced with the **PolyForm Noncommercial License 1.0.0**. The intent is
to sell commercial licences: noncommercial use is free, business use is paid.

Three properties of that arrangement drive every decision below.

1. **PolyForm Noncommercial is not an open-source licence.** It permits noncommercial purposes,
   personal use, and use by charities, educational institutions, public research bodies, public
   safety and health organizations, environmental organizations and government institutions. Every
   other use — including a company using the software internally, or evaluating it for a commercial
   purpose — needs a commercial licence. The project must therefore never be described as open
   source, in code, documentation, UI or marketing.
2. **Grants already made cannot be withdrawn.** Apache 2.0 §2 gave every recipient of the published
   commits a perpetual, irrevocable, royalty-free copyright licence, usable commercially. Replacing
   `LICENSE` binds new recipients only. It does not reach anyone who already cloned, downloaded or
   forked the repository while Apache 2.0 applied. See "Open item: the Apache snapshot" below.
3. **There is no inbound = outbound grant.** PolyForm Noncommercial says "These terms do not allow
   you to sublicense or transfer any of your licenses" and "do not imply any other licenses". A pull
   request merged without a CLA would be code BitNomad AB could not offer commercially — the
   restrictions would travel with it. Under this licence the CLA is not bureaucratic overhead, it is
   the only thing that keeps the product licensable.

### Provenance audit (2026-11-01)

| Question | Finding |
| --- | --- |
| Third-party or vendored source in the tree | None. 209 tracked files, all project source: 102 `.py`, 61 `.ts`/`.tsx`, 23 `.md`, no binaries, fonts or vendored directories. |
| Third-party copyright headers | None. No `Copyright`, `@license` or `SPDX-License-Identifier` headers other than the licence text itself. |
| Commit authors | All commits authored by BitNomad AB (`BitNomadAB <76220589+BitNomadAB@users.noreply.github.com>`) or its owner (`Michael Roesler`). No external contributor has ever committed. |
| History depth | Two commits (`Initial commit`, `v1`) plus a local agent checkpoint. The history is an import from the earlier private `MyBoards` repository, so commit granularity does not evidence day-to-day authorship. |
| Backend dependency licences | MIT, BSD-2/3, Apache-2.0, PSF-2.0 and MIT-0 only. **No GPL, AGPL or SSPL.** One MPL-2.0 dependency (`certifi`, runtime). |
| Frontend dependency licences | 212 packages: MIT, ISC, Apache-2.0, BSD-2/3, 0BSD, MIT-0, CC-BY-4.0, and MPL-2.0 (`lightningcss`, build-time only). **No GPL, AGPL or SSPL.** |
| Bundled third-party assets | None. Icons come from `lucide-react` (ISC), not vendored files. |

Permissively licensed dependencies may be distributed inside a PolyForm-licensed product; the
MPL-2.0 files keep their own notices. Nothing in the tree blocks commercial licensing.

## Decision

1. **Ship under PolyForm Noncommercial 1.0.0** (`LICENSE`), source-available, with commercial
   licences sold separately by BitNomad AB.
2. **Never call it open source.** The README, `AGENTS.md` and any UI copy say "source-available".
3. **Require a CLA for non-trivial contributions** (`CLA.md`): a perpetual, irrevocable,
   sublicensable copyright grant, explicitly effective outside the public terms, so BitNomad AB can
   relicense contributions commercially. Contributors keep copyright.
4. **Require DCO sign-off** on every commit (`git commit -s`) as a provenance statement. It
   complements the CLA; it does not replace it.
5. **Carry a `Required Notice:` line.** PolyForm's *Notices* section obliges distributors to pass on
   copies of the terms plus any plain-text lines beginning with `Required Notice:`. `NOTICE` holds
   that line; every redistribution must keep it.
6. **Treat the brand as reserved.** PolyForm Noncommercial is silent on trademarks, which is weaker
   than Apache 2.0 §6 was. Until a trademark policy exists, no fork or redistribution may present
   itself as the official product.
7. **Keep the dependency bar**: no GPL/AGPL/SSPL in runtime or bundled code, and a record here
   whenever a manifest changes.

## Open item: the Apache snapshot

`15d7145` (`Initial commit`) and `e42a07d` (`v1`) were published while `LICENSE` was Apache 2.0, and
that code is essentially the whole codebase. Anyone who obtained it holds an irrevocable commercial
licence to it. Under a source-available model this is a hole in the offering: a competitor can check
out `e42a07d` and use, modify and ship the product commercially, legitimately.

| Option | Effect | Cost |
| --- | --- | --- |
| **Rewrite the published history** — squash everything into one initial commit under PolyForm and force-push | Removes the Apache-licensed snapshot from the public history | Cheap now (minutes of exposure, no stars or forks). Cannot recall copies already taken; GitHub may keep unreachable commits reachable by SHA for a while. |
| Leave the history as it is | The Apache grant stays permanently available in the history | Defensible only if the commercial model does not depend on exclusivity |

The window is short and closing, so this needs an explicit decision rather than a default.

## Open questions for legal counsel

Not legal advice — a brief for a Swedish IP/tech lawyer. In order of risk:

1. **Who owns the code today?** The company has one employee and the owner is a board member
   (*styrelseledamot*), not necessarily an employee. Upphovsrättslagen (1960:729) 40 a § transfers
   the economic rights to computer programs created *in employment*; it says nothing about a board
   member who writes code. Confirm whether an employment contract and/or a separate assignment
   (*överlåtelseavtal*) actually transfers the rights, and whether it covers the period before the
   company was formed.
2. **The Apache snapshot** (above): is a history rewrite worth doing, and does it achieve anything
   beyond reducing reach?
3. **Boundary of "noncommercial".** How is a company evaluating the software, an internal tool at a
   nonprofit with commercial activity, or a consultant building for a client treated? This decides
   what the sales conversation must cover.
4. **Moral rights.** 27 § first paragraph (attribution) and third paragraph (the respect right does
   not apply to computer programs). Confirm what the CLA must say and how attribution should work in
   practice.
5. **Is the CLA enforceable as drafted?** Particularly the relicensing grant in §2, the employer
   clause in §4.3, and whether a Swedish company should prefer copyright assignment to a licence
   grant.
6. **The AI-generated portion.** Parts of the codebase were written with AI assistance. Confirm how
   that affects protectability, what originality warranty BitNomad AB can honestly give commercial
   customers, and whether the CLA's AI disclosure clause is sufficient.
7. **Warranties and indemnities** for commercial customers, given the dependency set above. The draft
   CLA deliberately contains no indemnity (§6).
8. **Trademark.** "Tralala" is a generic-sounding mark. Confirm registrability, and whether a
   trademark policy is needed now that the licence no longer reserves rights expressly.
9. **Governing law and forum** of the CLA (§10).

## Consequences

- Contributions without a signed CLA cannot be merged; the first outside pull request must be held
  until the paperwork exists.
- Adoption narrows: the project will not be tagged open source by GitHub, and most companies cannot
  even evaluate it without buying a licence. That is the trade the owner chose, but it should be a
  conscious one.
- `CLA.md` and `CONTRIBUTING.md` are public templates. Signed agreements must be stored outside the
  repository.
- The dependency audit above is a snapshot of 2026-11-01 and must be repeated when manifests change.
