# H6B1 R15 — ASCII Unit Boundary for Quantitative Fulfillment Text

R14 correctly introduced quantitative-specificity upgrades inside one SEC accession, but its `_future_is_quantitative()` detector used a Unicode `\b` boundary after English units such as `million` and `billion`.

In Python regex semantics, Traditional-Chinese characters are word characters. Therefore a valid user-visible string such as:

`約$144 million於未來12個月認列；非新增訂單預測`

has no Unicode word boundary between the final `n` in `million` and the following `於`. R14 consequently returned `False` even though the amount is explicitly quantitative.

R15 changes only this boundary to an ASCII-letter negative lookahead:

`(?:million|billion|m|b)(?![A-Za-z])`

This accepts CJK text and punctuation immediately after the unit while still rejecting glued ASCII suffixes such as `millionUSD` and `2.6MB`.

The change does not alter current-order selection, same-accession provenance, fulfillment percentages, ranking, LINE state, Production state, or any fail-closed evidence rule.
