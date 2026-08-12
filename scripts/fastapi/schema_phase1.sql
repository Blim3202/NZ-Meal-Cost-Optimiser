-- Phase 1 (+ Phase 2 schema refinements): Supabase schema
-- Run in your Supabase project's SQL Editor (with service_role key).
-- Uses 'public' schema (default PostgREST search path).
-- NOTE: results.store was added live to your project; the rows below mirror that +
-- further Phase 2 decisions (softened FK, pickup_address_id, indexes). Run as DDL.

create extension if not exists "pgcrypto";

-- stores: store_id is TEXT to support both UUID strings (Foodstuffs NW/Pak'nSave)
-- and numeric strings (Woolworths extra1/fulfilmentStoreId) used directly in API requests.
create table if not exists stores (
  store_id text primary key,
  brand text not null check (brand in ('PaknSave', 'NewWorld', 'Woolworths')),
  name text not null,
  address text,
  city text,
  region text,
  lat float,
  lon float,
  banner text,
  click_and_collect boolean,
  delivery boolean,
  pickup_address_id text null,  -- Woolworths extra2 (pickupAddressId) reverse-map; NULL for Foodstuffs
  added_at timestamp default now()
);
create index if not exists store_brand_idx on stores (brand);
create index if not exists store_pickup_idx on stores (pickup_address_id) where pickup_address_id is not null;

-- dishes
create table if not exists dishes (
  dish_name text primary key,
  portion int default 4,
  ingredients jsonb,
  added_at timestamp default now()
);

-- results
-- store_id is a plain indexed TEXT, NOT a hard REFERENCES FK.
--  - Foodstuffs store_id (UUID) matches stores.store_id 1:1.
--  - Woolworths results.store_id is normalized by the Phase 2 worker to extra1 (fulfilmentStoreId)
--    = stores.store_id. Until legacy CSV-derived rows are backfilled, a hard FK would abort inserts.
create table if not exists results (
  company text,
  store text,                       -- store display name (parity with full_results.csv)
  store_id text,
  search_ingredient text,
  returned_ingredient text,
  price numeric(10,2),
  quantity numeric,
  measurement_unit text,
  per_unit_quantity text,
  per_unit_price numeric(10,2),
  is_sale boolean default false,
  sku text,
  department text,
  sub_department text,
  datetime_created timestamp,
  date_created date,
  pk_hash text unique,
  is_valid boolean default null,
  added_at timestamp default now()
);
create index if not exists results_store_idx on results (store_id);
create index if not exists results_date_idx on results (date_created);
create index if not exists results_company_idx on results (company);

-- jobs: queued/sequential worker lifecycle tracking.
create table if not exists jobs (
  job_id uuid primary key default gen_random_uuid(),
  type text,        -- 'optimize' | 'generate_dish' | 'filter_ingredients' | 'validate_results' | 'scale_quantity'
  status text,      -- 'queued' | 'running' | 'done' | 'failed'
  params jsonb,
  result_ref text,  -- optional path/URL/summary to result
  error_message text,
  created_at timestamp default now(),
  updated_at timestamp default now()
);
create index if not exists jobs_status_idx on jobs (status);

-- refresh jobs.updated_at on every update
create or replace function set_updated() returns trigger as $$
begin
  new.updated_at := now();
  return new;
end;
$$ language plpgsql;
drop trigger if exists jobs_set_updated on jobs;
create trigger jobs_set_updated before update on jobs
  for each row execute function set_updated();
