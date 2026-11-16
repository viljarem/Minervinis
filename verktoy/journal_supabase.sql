-- =====================================================================
--  Tradingjournal – databaseoppsett for Supabase (Postgres)
-- =====================================================================
--  Kjør denne ÉN gang i Supabase:
--    Dashboard → prosjektet ditt → SQL Editor → New query →
--    lim inn ALT under → trykk Run (eller Cmd/Ctrl + Enter).
--
--  Trygt å kjøre flere ganger: alt bruker "if not exists" / "or replace",
--  så du mister ikke data om du kjører den på nytt senere.
--
--  Hvorfor det ser ut som det gjør:
--   * Hver tabell har et "eier"-felt. Nå er det alltid 'meg', men det gjør
--     at vi kan skru på ekte flerbruker senere UTEN å bygge om noe.
--   * Appen snakker med databasen via service_role-nøkkelen på serveren,
--     og journalen er låst bak et passord i Streamlit. Derfor har vi slått
--     PÅ row level security (RLS) og laget ÉN policy som lar service_role
--     gjøre alt. Anonyme nettlesere kommer ikke til.
--   * Pengetall er "numeric" (ikke float) så kroner/øre aldri avrundes feil.
-- =====================================================================

-- Slår på pgcrypto for gen_random_uuid() (finnes som regel allerede).
create extension if not exists "pgcrypto";


-- ---------------------------------------------------------------------
-- Felles: funksjon som holder "oppdatert"-tidsstempelet ferskt.
-- ---------------------------------------------------------------------
create or replace function public.sett_oppdatert()
returns trigger
language plpgsql
as $$
begin
  new.oppdatert = now();
  return new;
end;
$$;


-- ---------------------------------------------------------------------
-- 1) KONTO – kapital og ønsket risiko per handel, per børs.
--    Grunnlag for posisjonskalkulator og samlet risiko (heat).
-- ---------------------------------------------------------------------
create table if not exists public.konto (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  bors        text not null,                       -- 'Oslo Børs' / 'S&P 500 (USA)'
  kapital     numeric not null default 0,          -- total kontostørrelse
  risiko_pct  numeric not null default 1.0,        -- % av kapital å risikere per handel
  valuta      text not null default 'kr',
  opprettet   timestamptz not null default now(),
  oppdatert   timestamptz not null default now(),
  unique (eier, bors)
);

drop trigger if exists konto_oppdatert on public.konto;
create trigger konto_oppdatert before update on public.konto
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 2) LISTER – dine egne watchlister (navn, farge, rekkefølge).
-- ---------------------------------------------------------------------
create table if not exists public.lister (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  navn        text not null check (length(trim(navn)) > 0),
  farge       text not null default '#6B7280',     -- hex-farge for "chip"
  rekkefolge  integer not null default 0,          -- sorteringsrekkefølge i UI
  opprettet   timestamptz not null default now(),
  oppdatert   timestamptz not null default now(),
  unique (eier, navn)
);

drop trigger if exists lister_oppdatert on public.lister;
create trigger lister_oppdatert before update on public.lister
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 3) LISTE_AKSJER – hvilke aksjer ligger på hvilken liste.
--    pivot/stop/mål er DINE planlagte nivåer (live-tall som RS/TrendScore
--    hentes fra screeneren, lagres ikke her).
-- ---------------------------------------------------------------------
create table if not exists public.liste_aksjer (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  liste_id    uuid not null references public.lister(id) on delete cascade,
  ticker      text not null check (length(trim(ticker)) > 0),
  bors        text not null,
  pivot       numeric,
  stop        numeric,
  mal         numeric,
  opprettet   timestamptz not null default now(),
  oppdatert   timestamptz not null default now(),
  unique (liste_id, ticker)
);

create index if not exists liste_aksjer_liste_idx on public.liste_aksjer (liste_id);
create index if not exists liste_aksjer_ticker_idx on public.liste_aksjer (ticker);

drop trigger if exists liste_aksjer_oppdatert on public.liste_aksjer;
create trigger liste_aksjer_oppdatert before update on public.liste_aksjer
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 4) NOTATER – dagbok. Mange daterte notater per aksje; gamle består.
-- ---------------------------------------------------------------------
create table if not exists public.notater (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  ticker      text not null check (length(trim(ticker)) > 0),
  bors        text not null,
  tekst       text not null default '',
  opprettet   timestamptz not null default now(),
  oppdatert   timestamptz not null default now()
);

create index if not exists notater_ticker_idx on public.notater (ticker);
create index if not exists notater_dato_idx on public.notater (opprettet desc);

drop trigger if exists notater_oppdatert on public.notater;
create trigger notater_oppdatert before update on public.notater
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 5) HANDLER – én rad per handel. Delsalg ligger i egen tabell under,
--    så en handel kan selges i flere biter og stop kan traile.
--    status: 'OPEN' mens den lever, 'CLOSED' når alt er solgt.
--    kilde: fri tekst ('minervini','golden_cross','qullamaggie', ...)
--    setup: fri tekst ('VCP','breakout','momentum', ...)
-- ---------------------------------------------------------------------
create table if not exists public.handler (
  id            uuid primary key default gen_random_uuid(),
  eier          text not null default 'meg',
  ticker        text not null check (length(trim(ticker)) > 0),
  bors          text not null,
  status        text not null default 'OPEN' check (status in ('OPEN','CLOSED')),
  kjop_dato     date not null,
  kjop_kurs     numeric not null check (kjop_kurs > 0),
  antall        numeric not null check (antall > 0),
  stop          numeric,                            -- opprinnelig stop (til R)
  mal           numeric,
  pivot         numeric,
  setup         text not null default '',
  kilde         text not null default '',
  trigger       text not null default '',           -- kjøpssignal (pill)
  notat         text not null default '',
  -- Evaluering (fylles ved lukking):
  fulgte_plan   text not null default '',           -- 'Ja'/'Nei'/'Delvis'
  evaluering    text not null default '',
  opprettet     timestamptz not null default now(),
  oppdatert     timestamptz not null default now()
);

create index if not exists handler_status_idx on public.handler (status);
create index if not exists handler_ticker_idx on public.handler (ticker);
create index if not exists handler_kjop_dato_idx on public.handler (kjop_dato desc);

drop trigger if exists handler_oppdatert on public.handler;
create trigger handler_oppdatert before update on public.handler
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 6) DELSALG – ett eller flere salg per handel (delsalg + trailing).
--    Summen av antall her bør matche handelens antall når den er CLOSED.
-- ---------------------------------------------------------------------
create table if not exists public.delsalg (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  handel_id   uuid not null references public.handler(id) on delete cascade,
  salg_dato   date not null,
  salg_kurs   numeric not null check (salg_kurs > 0),
  antall      numeric not null check (antall > 0),
  arsak       text not null default '',
  opprettet   timestamptz not null default now()
);

create index if not exists delsalg_handel_idx on public.delsalg (handel_id);


-- ---------------------------------------------------------------------
-- 7) TAGGER + HANDEL_TAGGER – frie, filtrerbare tagger (mange-til-mange).
--    F.eks. disiplin: 'Fulgte planen','FOMO','Solgte for tidlig'.
-- ---------------------------------------------------------------------
create table if not exists public.tagger (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  navn        text not null check (length(trim(navn)) > 0),
  farge       text not null default '#6B7280',
  unique (eier, navn)
);

create table if not exists public.handel_tagger (
  handel_id   uuid not null references public.handler(id) on delete cascade,
  tag_id      uuid not null references public.tagger(id) on delete cascade,
  primary key (handel_id, tag_id)
);


-- ---------------------------------------------------------------------
-- 8) ANALYSER – egen tese per aksje (fase 2). Kan kobles til en handel.
--    Entry/SL/Target lagres så R/R og snapshot kan gjenskapes i ettertid.
-- ---------------------------------------------------------------------
create table if not exists public.analyser (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  ticker      text not null check (length(trim(ticker)) > 0),
  bors        text not null,
  tittel      text not null default '',
  dato        date not null default current_date,
  strategi    text not null default '',             -- oppsett/strategi
  tekst       text not null default '',             -- fritekst / tese
  entry       numeric,
  stop        numeric,
  mal         numeric,
  handel_id   uuid references public.handler(id) on delete set null,
  opprettet   timestamptz not null default now(),
  oppdatert   timestamptz not null default now()
);

create index if not exists analyser_ticker_idx on public.analyser (ticker);

drop trigger if exists analyser_oppdatert on public.analyser;
create trigger analyser_oppdatert before update on public.analyser
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 9) TEGNINGER – chart-tegninger som JSONB (fase 3).
--    kobling: enten låst til en analyse (snapshot) ELLER aktivt arbeidslag
--    på en aksje. 'data' = {id,type,role,points,style,label}.
-- ---------------------------------------------------------------------
create table if not exists public.tegninger (
  id          uuid primary key default gen_random_uuid(),
  eier        text not null default 'meg',
  ticker      text not null,
  bors        text not null,
  analyse_id  uuid references public.analyser(id) on delete cascade,
  aktiv       boolean not null default true,        -- true = arbeidslag, false = snapshot
  data        jsonb not null default '[]'::jsonb,
  opprettet   timestamptz not null default now(),
  oppdatert   timestamptz not null default now()
);

create index if not exists tegninger_ticker_idx on public.tegninger (ticker);
create index if not exists tegninger_analyse_idx on public.tegninger (analyse_id);

drop trigger if exists tegninger_oppdatert on public.tegninger;
create trigger tegninger_oppdatert before update on public.tegninger
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 11) INNSTILLINGER – enkel nokkel/verdi-lagring (JSON) per eier.
--     Brukes til redigerbare setup-/trigger-tagger m.m. som da synkes
--     paa tvers av telefon, Mac og PC. Appen takler at tabellen mangler.
-- ---------------------------------------------------------------------
create table if not exists public.innstillinger (
  eier       text not null default 'meg',
  nokkel     text not null,
  verdi      jsonb not null default 'null'::jsonb,
  oppdatert  timestamptz not null default now(),
  primary key (eier, nokkel)
);

drop trigger if exists innstillinger_oppdatert on public.innstillinger;
create trigger innstillinger_oppdatert before update on public.innstillinger
  for each row execute function public.sett_oppdatert();


-- ---------------------------------------------------------------------
-- 12) SKANN_CACHE – ferdig skann-resultat lagret som JSON, delt paa
--     tvers av enheter. Appen leser ferdig resultat ved aapning saa den
--     ikke maa regne paa nytt. Dette er bare screener-resultater
--     (offentlig info), derfor ikke laast bak journal-passordet.
--     Noekkel: eier + bors + oppsett + datadato (siste handelsdag).
-- ---------------------------------------------------------------------
create table if not exists public.skann_cache (
  eier        text not null default 'meg',
  bors        text not null,
  oppsett     text not null,                        -- 'Minervini' / 'Golden Cross' / ...
  datadato    date not null,                        -- siste handelsdag i datagrunnlaget
  antall      integer not null default 0,
  rader       jsonb not null default '[]'::jsonb,   -- hele resultatet som liste av objekter
  oppdatert   timestamptz not null default now(),
  primary key (eier, bors, oppsett, datadato)
);

create index if not exists skann_cache_oppslag_idx
  on public.skann_cache (bors, oppsett, datadato desc);

drop trigger if exists skann_cache_oppdatert on public.skann_cache;
create trigger skann_cache_oppdatert before update on public.skann_cache
  for each row execute function public.sett_oppdatert();


-- =====================================================================
--  SIKKERHET: row level security (RLS)
-- =====================================================================
--  Vi slår PÅ RLS på alle tabeller og lager én policy per tabell som
--  bare gir service_role full tilgang. Appen bruker service_role-nøkkelen
--  på serveren (aldri i nettleseren), og journalen er passordlåst.
--  Anonyme nettlesere får dermed INGEN tilgang.
--  (Dagen vi vil ha ekte flerbruker, bytter vi disse policyene ut med
--   regler basert på auth.uid() = eier – uten å røre tabellene.)
-- =====================================================================

do $$
declare
  t text;
begin
  foreach t in array array[
    'konto','lister','liste_aksjer','notater','handler',
    'delsalg','tagger','handel_tagger','analyser','tegninger','innstillinger',
    'skann_cache'
  ]
  loop
    execute format('alter table public.%I enable row level security;', t);
    execute format('drop policy if exists %I on public.%I;', t || '_service_all', t);
    execute format(
      'create policy %I on public.%I for all to service_role using (true) with check (true);',
      t || '_service_all', t
    );
  end loop;
end $$;

-- Ferdig. Du skal se "Success. No rows returned". Gå tilbake til appen.
