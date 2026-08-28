# v9.4.5 — Reliable OEE shift toggle buttons

- Replaced `st.pills` for combined-shift selection with three state-driven Streamlit buttons.
- Each click toggles `1st`, `2nd`, or `3rd` directly in Python session state.
- Selected buttons are targeted by their exact widget keys and receive a strong red background, white bold text, and pulsing red glow.
- This avoids reliance on undocumented `st.pills` HTML attributes that caused v9.4.4 to show no visual selection.
- OEE calculations, duplicate rules, IWON, permissions, and all other modules remain unchanged.
