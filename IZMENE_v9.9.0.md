# Lianbo Project Performance Hub — v9.9.0

## Zašto su unosi ponekad „nestajali“

| Uzrok | Posledica za korisnika | Ispravka |
|---|---|---|
| Uvoz u ALL_ACTIVITIES radio je samo pozadinski proces, a on se nikad nije pokretao (tražio je `AUTOMATION_TOKEN`, a GitHub workflow ga nije prosleđivao). | Unosi iz Google Forms-a i Work Tickets-a nisu se videli u KPI-u. Alarmi za nedostajuće vreme nisu slati. | KPI sam uvozi nove unose (najviše na 2 min, odmah posle čuvanja aktivnosti). Pozadinski proces radi i bez tokena. Workflow sada prosleđuje token. |
| Polja za datum i vreme prihvatala su samo tačan format. | Unos `23.10.2026.` (sa tačkom na kraju), `8.30` ili kraj bez „End Date“ je odbijen, iako je sve bilo uneto ispravno. | Prihvataju se svi uobičajeni zapisi. Prazan End Date znači isti dan. |
| Mešani formati vremena (`08:30` i `8:30:00`) | Deo redova je tiho izbačen iz KPI-a. | Svaki red se čita posebno. |
| Kolona u sheet-u nazvana drugačije (npr. `Assigned To` umesto `Assigned_To`) | Vrednost je upisivana prazna, pa se task nije video. | Kolone se prepoznaju bez obzira na razmak, velika slova i donju crtu. |
| Tekst koji počinje sa `-`, `+` ili `=` | Google Sheets ga je sačuvao kao `#ERROR!`. | Takav tekst se čuva kao tekst. |
| Ime upisano drugačije (`Nikolić Bojan`, `Djordje`) | Osoba je u KPI-u bila „podeljena“ na dve. Dobijala je lažan alarm da nema unosa. | Imena se porede bez obzira na redosled reči, velika slova i dijakritike (đ = dj). KPI prikazuje zvanično ime. |
| Forma se praznila i kada je unos odbijen | Ljudi su odustajali od ponovnog kucanja. | Podaci ostaju posle greške, a brišu se tek posle uspešnog čuvanja. |
| Keš je posle Google greške 429 tiho vraćao stare podatke (do 1 h) | Novi unosi se nisu videli. | Stari podaci se prikazuju samo posle svih ponovnih pokušaja i uz vidljivo upozorenje. Provere duplikata i izmene redova uvek čitaju živ sheet. |
| BN Forms: decimalni zarez (`12,5`) i zamena dana i meseca | BN unos je izgubljen ili upisan pod pogrešnim datumom. | Ispravljeno. Već uvezeni redovi sa pogrešnim datumom ispravljaju se na istom mestu, bez duplikata. |
| Line Verification: datumi tipa `15.06.2026` | Redovi su izbačeni ili su dobili pogrešan datum. | Ispravljeno. |

## Brzina

- Ranije je svaki zahtev ka Google-u čekao fiksnih 0,35 s, za sve korisnike redom. Sada se čeka samo kada bi se prešla stvarna Google kvota.
- Slika pozadine (~300 KB) ranije se slala uz svaki klik. Sada se preuzima jednom (`static/` i `.streamlit/config.toml`).
- Work Tickets više ne pokreće punu sinhronizaciju pri prvom otvaranju.
- KPI obrada je keširana.
- Provera ID-jeva taskova radi jednom u 10 min za ceo server, umesto za svakog korisnika.
- E-mail log više ne čita ceo sheet pri svakom upisu.
- Ponovljen prikaz iste stranice: 0 Google poziva.

## Ostalo

- Dvostruki klik na „Save“ ne pravi duplikat.
- Ako pukne naknadni korak (e-mail, ENVA), korisnik vidi „JE sačuvano“ umesto crvene greške.
- Alarm za nedostajuće vreme šalje se samo posle uspešne sinhronizacije i nikad dva puta.
- OEE za period ponovo koristi dnevno ograničene komponente (pravilo iz v9.4.9).
- „Remember me“ radi i kod prvog učitavanja stranice.

## Provera

```
python -m unittest discover -s tests -p "test_*.py"
python tests/simulation/run_simulation.py
```
