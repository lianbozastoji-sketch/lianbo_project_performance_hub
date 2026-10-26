# Lianbo Project Performance Hub — v11.1.0

## Šta je novo

### 1. Uzroci zastoja (u OEE unosu)
- Čim je **Zastoj** (ili **Organizacioni gubici**) veći od 0, ispod se otvori red **Razlog + Minuta**. Prvi red je već popunjen minutima.
- Dugme **➕** otvara još jedan red za sledeći zastoj (npr. 10 + 20 min umesto jednog od 30), a **✖** briše red.
- Odmah se vidi status: „✓ Raspoređeno 30 od 30 min“ / „Nedostaje još 10 min“ / „Previše“. Čuvanje radi tek kad je zbir tačan i svaki red ima razlog.
- Zastoji koje su tehničari već prijavili u Google formi za tu mašinu i smenu uračunaju se sami.
- Izmena smene menja i njene zastoje, bez dupliranja. Svaki zastoj se čuva posebno (tab `DOWNTIME_EVENTS`).
- Lista uzroka je fiksna (Administracija → OEE podešavanja). Svaki uzrok ima oznaku „ređe“ (kvarovi) ili „kraće“ (zamene, podešavanja).

### 2. OEE jasan menadžeru koji nije na liniji
Na stranicama Dnevno, Nedeljno, Mesečno, Godišnje i Dashboard:
- **rečenica-sažetak**: koliko je OEE, u odnosu na referencu 85 % i na prethodni period, najveći gubitak i upozorenje ako unosi nisu potpuni;
- **pokrivenost unosa**: npr. „uneto 3 od 5 radnih dana“, koji dani nedostaju, poslednji uneti dan;
- pločice OEE / dostupnost / performanse / kvalitet sa **promenom od prethodnog perioda** i oznakom „i“ (objašnjenje pojma);
- **izgubljeno**: komadi ispod targeta, sati (zastoji i organizacija), **€** ako je uneta cena komada;
- **Pareto uzroka** („Zašto smo gubili vreme“) i **OEE po smenama**;
- rang mašina sa **obimom** (komadi, sati rada) i oznakom „malo podataka“;
- **akcije**: „+ Napravi akciju iz gubitka“ pravi Work Ticket (odgovoran, prioritet, rok) povezan sa mašinom i uzrokom;
- opis procesa (proizvod, kupac) iz Administracije; „Šta znače pojmovi?“; sve na srpskom;
- glavni broj je „OEE mašine“, ostale varijante su označene kao „napredno“.

### 3. Novi modul **Uprava**
Cela fabrika na jednom ekranu: kartica po projektu sa trendom za 13 nedelja, 5 najvećih gubitaka sa statusom akcije, broj otvorenih i zakasnelih akcija, unosi koji nedostaju. Dugme na kartici otvara tu nedelju u OEE-u. Vidi ga svako ko ima pravo na OEE.

### 4. Nedeljni e-mail upravi
Svakog ponedeljka od 07:00, za prethodnu nedelju, jednom (EMAIL_LOG sprečava duplo slanje). Primaoci i uključivanje: Administracija → OEE podešavanja (postoji i dugme za probni e-mail).

### 5. IWON — samo za tebe
- IWON je izbačen iz izbora metrike na svim OEE stranicama i iz Administracije.
- Vidi ga **samo korisnik čije je korisničko ime u Streamlit secrets** (`IWON_USERS`), kao **OEE → 🔒 IWON**. Pristup ne može da se doda iz aplikacije, ni kao administrator.
- **Plan za bilo koju nedelju**, sa podacima ili bez (i za buduće nedelje). Osnova su poslednje 4 / 10 / 13 nedelja sa podacima pre te nedelje. Uz plan se upisuje i **prognoza bez poboljšanja**.
- Plan se **zamrzava**. Ponovno generisanje ide samo uz potvrdu, a stara verzija ide u `IWON_PLAN_HISTORY`.
- **„Osveži stvarno“** povuče stvarne podatke i upiše odstupanje od plana i od prognoze u tab `IWON_COMPARE`. Prikazuje i tačnost prognoze kroz nedelje.
- **Plan po uzroku** (`IWON_CAUSE_PLAN`): za svaki uzrok koliko se dešava i koliko traje sada, najbolje već postignuto (najbržih 20 %) i koliko mora da bude da bi se cilj postigao. Ocena: realno / izazovno / nerealno, plus „najviši realan OEE“.
- `OEE_IWON` (A:J) se i dalje upisuje isto kao ranije, pa postojeće formule rade.

### Ostalo
- Tamna tema i crveni sjaj (iz v10.1).
- Novi tabovi se prave sami pri prvom korišćenju; postojeći se ne menjaju i ne brišu:
  - OEE sheet: `DOWNTIME_EVENTS`, `DOWNTIME_CAUSES`, `OEE_SETTINGS`;
  - IWON sheet: `IWON_COMPARE`, `IWON_PLAN_HISTORY`, `IWON_CAUSE_PLAN`;
  - TASKS dobija kolone `Due_Date` i `Source_Ref` (dodaju se na kraj).

## Postavljanje
1. Zameni fajlove iz paketa. **Novi fajl `oee_insights.py`** mora biti u istom folderu kao glavni fajl. Postavi i `ui_theme.py`.
2. Streamlit Cloud → App → Settings → Secrets, dodaj red (sa svojim korisničkim imenom):
   ```
   IWON_USERS = ["tvoje_korisnicko_ime"]
   ```
   Bez ovog reda IWON ne vidi niko.
3. Administracija → OEE podešavanja: cena komada, opisi procesa, e-mail uprave.

## Provera
- Simulacija: 236/236 provera (pandas 2.x i 3.x). Novi scenariji pokrivaju unos zastoja u OEE unosu (jedan ili više redova, ➕, provera zbira), prikaz za menadžere, stranu Uprava, e-mail, IWON za buduće nedelje, zamrzavanje, osvežavanje, plan po uzroku i **da IWON nije vidljiv nikome drugom**.
- Unit testovi: 54/54 (14 novih za proračune: uzroci, pokrivenost, gubici, prognoza, plan po uzroku).
