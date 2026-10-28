# Lianbo Project Performance Hub — v11.2.0

## Ispravljeno
- **Žuta greška „cookie_manager component“ i sporost:** komponenta za „Remember me“ pravila se pri svakom kliku. To je dodavalo još jedno učitavanje stranice na svaki klik i povremeno izbacivalo ovu grešku. Sada se koristi samo na stranici za prijavu i pri odjavi.
- **Brže:**
  - logo se šalje kao 4 KB umesto 36 KB pri svakom kliku;
  - OEE proračuni su oko 40 % brži;
  - podešavanja i lista uzroka čitaju se iz Google-a jednom na sat (odmah posle izmene), a zastoji na 5–10 minuta, umesto na svaki minut.

## Unos zastoja (OEE → Unos)
- **Razlog se upisuje slobodno** (npr. „zamena senzora na OP30“), nema više biranja sa liste.
- Svaki zastoj je poseban red: razlog i minuti. **➕** dodaje sledeći, **✖** briše red. Zbir mora da odgovara polju „Zastoj“, odnosno „Organizacioni gubici“.
- Polja su prazna umesto „0.00“. **Klik na polje označi ceo broj**, pa novi unos zameni stari.
- Minuti su celi brojevi („20“, a ne „20.00“).
- U izveštajima se isti razlog prepoznaje bez obzira na velika i mala slova i razmake („senzor OP30“ = „Senzor  op30“).

## IWON
- **Unos je u Administration → 🔒 IWON:** Ciljevi, Plan i prognoza (generisanje), Osveži stvarno.
- **Prikaz je u OEE → 🔒 IWON:**
  - grafikon Cilj / Prognoza / Stvarno za sve nedelje sa planom (stvarno se računa uživo iz OEE unosa);
  - grafikoni plana za izabranu nedelju;
  - plan i stvarno po mašini;
  - plan po razlogu zastoja.
- Ako za izabrani projekat i proces nema plana, stranica napiše **za koje projekte, procese i nedelje planovi postoje**. Ranije je samo pisalo „nema“.
- I dalje vidljivo samo korisnicima iz `[iwon] USERS` u secrets.

## Upload
Svih 11 fajlova iz paketa, bez foldera. `.streamlit/config.toml` samo jednom, ako još nije postavljen (sadržaj je u poruci).

## Provera
Simulacija 243/243 (pandas 2 i 3), unit testovi 54/54.
