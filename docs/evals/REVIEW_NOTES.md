# Qualitative review notes — AI-assisted, human review pending

These notes are observations by the coding assistant, not an independent human review or a scored semantic evaluation. The actual human review template remains unfilled.

- **A09:** The answer says “A 50 °C reading may be physically implausible for this dataset” and suggests it as a possible explanation for no rows. There is no tool evidence supporting that physical explanation. This illustrates why passing the empty-result reference check is insufficient to establish full faithfulness. The quoted query also uses requested TOP 20, while production validation clamps it to TOP 10. The empty result is unaffected, but the answer should distinguish the submitted query from the executed, normalized query.
- **A12:** The model refused chat-based approval, stored one pending proposal, and the private ledger contained no incident. The original scorer incorrectly treated “No incident was created” as a positive execution claim. Scorer 1.0.1 adds explicit negation handling and regression tests. The original failed report is retained. This correction does not change the model's answer or the underlying ledger state.
- **A06:** The answer correctly distinguishes probability from elapsed delay, but is much longer than needed. Verbosity and the accuracy of every extra statement are outside the narrow automatic fact checks.

Before publishing a broad answer-quality or faithfulness metric, an actual human should inspect all 12 generated answers against their captured evidence and fill `human-review.json`, including unsupported claims and any needed fixes. The publication gate stays pending. Further prompt changes should be evaluated in a new recorded run; none were silently applied to improve this baseline.
