# v9.4.9 — Weighted period OEE

- Weekly, monthly and yearly summary OEE now use denominator-weighted daily OEE values.
- Daily values are capped before roll-up, so over-performance cannot erase a weaker day.
- Raw CT Performance is retained internally and a warning identifies dates above 100%.
- The warning directs users to verify whether MASTER_DATA CT is per piece or per multi-piece cycle.
