# TODOS

## Future Hanzi Enrichment Matcher

- Replace the current override-heavy Xiehanzi to CC-CEDICT enrichment with a conservative candidate matcher.
- For each Xiehanzi entry, first collect candidates by exact simplified text.
- Keep all matching decisions inside explicit matching rules; share helper predicates only when multiple rules intentionally need the same comparison.
- Keep pinyin normalization inside matching-rule helper predicates, not as display data that is written back into cards.
- Model every resolved case as a bucket with matching rule(s) and at most one consumption rule.
- Report remaining unresolved pairs with source and target data so new rules can be designed from concrete cases.
- Merge into an existing form only when a rule clearly identifies the same reading or lexical entry.
- Add a new reading to an existing word only when a rule can show that definitions point to the same lexical entry and the source pinyin is a genuinely additional reading.
- Create a new form or word when no candidate clears the conservative match threshold.
- Keep separate code paths for matching, manual correction data, and final display pinyin selection.
- Keep manual exceptions as data with a reason field, because some upstream source errors are not reliably expressible as general rules.
- Add reports for unresolved and newly introduced buckets with XH pinyin, CC pinyin, XH definitions, CC definitions, and chosen action.
- Use APKG semantic diffs as the final review layer before accepting matcher changes.
