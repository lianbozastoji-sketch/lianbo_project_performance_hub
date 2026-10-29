# Lianbo Project Performance Hub — v11.3.1

## IWON ciljevi se sada čitaju iz tvog sheet-a
- Aplikacija **prvo čita tab iz linka** (gid 1806481969), bez obzira kako se tab zove, a posle i stari tab „Admin podešavanja“.
- **Raspored tabele:** razume tabelu po redovima (godina, nedelja, projekat, proces, cilj) i tabelu po kolonama (projekat/proces u redu, CW1 … CW53 u kolonama). Zaglavlje može biti bilo gde u prvih 10 redova.
- **Nazivi kolona:** Godina/Year, CW/KW/Nedelja, Projekat/Project, Proces/Process, Cilj/Target/Target OEE…
- **Vrednosti:** 85, „85,5“, „85 %“, ćelija u procentima (0,85), nedelja „CW43“ / „43“ / „KW 43“.
- **Projekat i proces:** „APP-350“ u sheet-u je isto što i „APP350“ u MASTER_DATA. Velika i mala slova, razmaci i crtice se ne gledaju.
- **Izmene u sheet-u se vide posle 2 minuta**, ili odmah posle klika na „🔄 Učitaj ponovo“. Ranije su se videle tek posle 5 minuta.
- **Administration → 🔒 IWON → Ciljevi → „Odakle aplikacija čita ciljeve“:** za svaki tab piše šta je pročitano (projekti, procesi, nedelje, broj ciljeva) i koji redovi su preskočeni i zašto.
- **Tvoj tab se nikad ne prepisuje.** Ako je urađen na svoj način, ciljevi se menjaju samo u sheet-u, a u aplikaciji se samo prikazuju.

## OEE → 🔒 IWON
- Ciljevi se prikazuju odmah, i pre nego što se napravi plan po mašini.
- Za nedelje koje imaju cilj, a nemaju plan, postoji dugme **„Napravi plan za tih N nedelja“**.
- Ako za izabrani projekat i proces nema ništa, stranica navodi za koje projekte i procese u sheet-u postoje ciljevi.

## Provera
Simulacija 276/276 (pandas 2 i 3), sa tabom kao ručno pravljenim: zaglavlje u 3. redu, „APP-350“, „CW51“, „85,5 %“, 0,86. Unit testovi 60/60.
