# TODOS

## Future Hanzi Enrichment Matcher

- Replace the current override-heavy Xiehanzi to CC-CEDICT enrichment with a conservative candidate matcher.
- For each Xiehanzi entry, first collect candidates by exact simplified text.
- Score each candidate using pinyin evidence, definition evidence, and ambiguity penalties.
- Keep pinyin normalization as matching evidence only, not as display data that is written back into cards.
- Treat pinyin evidence as ordered tiers such as exact, spacing variant, case variant, case plus spacing variant, toneless variant, and no useful match.
- Treat definition evidence as ordered tiers such as normalized exact match, subset match, high token overlap, weak overlap, and contradiction or unrelated text.
- Prefer matches where pinyin and definition evidence agree.
- Report rather than merge when pinyin evidence is weak and definition evidence is not strong.
- Merge into an existing form when the score clearly identifies the same reading or lexical entry.
- Add a new reading to an existing word only when definitions point to the same lexical entry but pinyin evidence shows a genuinely additional reading.
- Create a new form or word when no candidate clears the conservative match threshold.
- Keep separate code paths for matching, manual correction data, and final display pinyin selection.
- Keep manual exceptions as data with a reason field, because some upstream source errors are not reliably expressible as general rules.
- Add reports for every non-exact merge tier with XH pinyin, CC pinyin, XH definitions, CC definitions, score details, and chosen action.
- Use APKG semantic diffs as the final review layer before accepting matcher changes.
