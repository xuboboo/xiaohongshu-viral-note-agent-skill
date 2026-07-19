# Content intelligence v5.1

Originality checks combine independent signals:

- normalized literal similarity;
- 64-bit SimHash and Hamming distance;
- MinHash approximation over n-grams;
- rare-phrase overlap;
- configurable text embeddings and cosine similarity;
- image perceptual hash;
- optional OCR text overlap.

A single strong plagiarism signal may block publication. Missing optional providers must produce an
explicit degraded-mode report rather than a fabricated score.

Claims must bind to specific evidence references containing source, locator, excerpt digest,
verification state and optional expiry. Evidence for one claim must not automatically verify another.

Trend analysis uses robust growth, acceleration, change-point and saturation features. Content-gap
results are hypotheses based on available samples, not official platform demand measurements.

Candidate ranking uses a trained LightGBM LambdaMART model when a validated model artifact exists.
Without one, use the audited deterministic ranker. Apply embedding-aware MMR after relevance ranking
to avoid near-duplicate final options.
