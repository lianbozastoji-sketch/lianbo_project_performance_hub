# Lianbo Project Performance Hub — v10.1.0 (OEE: klik na grafikon)

## Novo u OEE modulu
- **Klik na stubić ili tačku** otvara karticu tog perioda ispod grafikona:
  - OEE → dostupnost, performanse, kvalitet (i formula A × P × Q)
  - Dostupnost → vreme zastoja, organizacioni gubici, radno vreme
  - Kvalitet → OK, NOK, ukupno komada
  - Performanse → ukupno komada naspram targeta, razlika
  - kod više mašina: 3 mašine koje su najviše spustile rezultat
- Radi za Dnevno, Nedeljno, Mesečno, Godišnje i Dashboard. Umesto 4 odvojena grafikona je jedan, sa izborom OEE / Dostupnost / Performanse / Kvalitet.
- **Unutar perioda**: klik na mesec pokazuje njegove nedelje, klik na nedelju njene dane, klik na dan njegove mašine.
- **„Otvori detaljnije“** spušta jedan nivo niže (godina › mesec › nedelja › dan), a dugmad „←“ vraćaju nazad sa istim filterima.
- Osa uvek pokazuje ceo period (cela nedelja, svi meseci). Dan bez unosa je prazno mesto, a jedan uneti dan je stubić, ne usamljena tačka.
- **Rang mašina**: vodoravne trake iste debljine, visina raste sa brojem mašina, linija cilja 85 %, klik na mašinu otvara njene detalje.
- Dnevni prikaz: klik na stubić OEE / Availability / Q-rate / Performance otvara odgovarajuće detalje.

## Izgled
- Izabrani meni, izabrana „pilula“ i pritisnuto dugme svetle crvenkasto (glow), više nema belog dugmeta.
- Aplikacija ima tamnu temu u `.streamlit/config.toml`, pa su i tabele tamne (ranije bele).

## Fajlovi koje treba zameniti
`lianbo_project_performance_hub.py`, `ui_theme.py`, `config.py`, `.streamlit/config.toml`, `tests/…`, `README.md`.

## Provera
- Simulacija: 172/172 provere (pandas 2.x i 3.x). Novi scenario proverava kalendarske periode, sve brojeve na kartici (ručno izračunate), klikove, spuštanje i vraćanje nazad, i da nijedna stranica ne prikazuje grešku.
- Svi grafikoni u aplikaciji provereni su na ispravna plotly svojstva.
- Unit testovi: 39/39 OK.
