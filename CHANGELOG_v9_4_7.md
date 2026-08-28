# v9.4.7 — OEE calculation fix

- Corrected Machine Availability to `(Open time - Down time - Organisational loss) / Open time`.
- Applied the same formula to daily, weekly, monthly and yearly aggregation.
- Removed the artificial 99% OEE display ceiling; valid results can now reach 100%.
