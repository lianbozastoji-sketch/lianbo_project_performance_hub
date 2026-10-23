# Lianbo Project Performance Hub — v10.0.0 (vizuelni redizajn)

Logika i podaci su isti kao u v9.9.1. Menja se samo izgled.

## Novi fajl
- `ui_theme.py` — ceo izgled (boje, meniji, kartice, grafikoni) na jednom mestu. **Mora se postaviti na GitHub.**

## Meniji
- Bočni meni je podeljen u grupe **Rad / Analitika / Sistem**. Aktivni modul je istaknut.
- Na vrhu je kartica korisnika, a dole su alati (osvežavanje, odjava).
- Svaka stranica ima zaglavlje sa ikonom, nazivom, opisom i oznakama (korisnik, vreme, verzija).
- Na telefonu je meni pregledan, bez bočnog skrolovanja.

## KPI
- Navigacija u dva nivoa: **📈 Pregled · 🔍 Analiza · 🧑‍🔧 Tehničari · 🗂 Podaci**, pa stranica unutar grupe.
- KPI pločice sa statusom u boji (zeleno, žuto, crveno) i trakom napretka prema cilju.

## Grafikoni (industrijski stil)
- Jedinstvena paleta, tačkasta mreža, srpski format brojeva (1.234,5) i nazivi osa na srpskom.
- Linije sa ciljnom vrednošću (npr. iskorišćenost 85 %) i istaknutom poslednjom tačkom.
- Novi **Pareto** grafikon (stubići + kumulativna linija + granica 80 %).
- Krug („donut“) sa ukupnim zbirom u sredini; stubići sa vrednostima.
- OEE merač u boji statusa, sa granicom 85.

## Work Tickets
- Kanban sa brojem taskova po koloni i sažetkom na vrhu.
- Kartice taskova sa bojom prioriteta i oznakama statusa i procesa.
- Kolona „Closed“ prikazuje 12 poslednjih, a ostatak je u „Prikaži još“.

## Provera
- Simulacija: 119/119 provera (pandas 2.x i 3.x). Unit testovi: 39/39 OK.
