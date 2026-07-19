# Content generation

Generate distinct mechanisms rather than synonym variants. Include concrete scenes, evaluation
criteria, limitations and unsuitable audiences. Never fabricate personal use, prices, effects,
reviews, rankings or awards. The final package must include title, cover, body, graphic pages or
video scenes, keyword map, claim ledger, originality report, compliance report and AI provenance.

## Quality-driven generation guards

When `search_quality` is poor (score < 40 or label `poor`/`empty`):

- **Hard constraints** are injected into `GenerateRequest.constraints`:
  - `evidence_boundary`: no fabricated engagement numbers, rankings or claimed results
  - `disclaimer`: must label public-index sourcing in body (not official hot list)
  - `tone`: restrained, checkable, include boundary / unsuitable audience
  - `claims`: objective statements must be verifiable or converted to subjective
- **Assumptions** are added to `DeliveryPackage.assumptions` for human review.
- **Human review** is strengthened with a note to verify all facts and numbers.
- The **assumption list** includes search_quality recommendations when available.

When quality is fair (score 40–69):

- **Soft constraints**: engagement numbers not in sample must not be stated as facts.
- The package is labeled with a disclaimer about public-index sourcing.

When quality is good (≥ 70): no guards are injected.

`topic_suggestions[].generate_payload.constraints` also include these guards, so one-hop
generate from the topic list carries the correct boundary.
