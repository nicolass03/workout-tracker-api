-- scripts/migrate.py keeps its bookkeeping table in public, where Supabase's Data API
-- grants anon/authenticated full access. RLS without policies denies those roles; the
-- owning postgres role (API, migrate.py) bypasses RLS. A no-op for hand-applied setups.
ALTER TABLE IF EXISTS public.schema_migrations ENABLE ROW LEVEL SECURITY;
