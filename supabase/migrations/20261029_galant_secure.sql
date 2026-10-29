-- GALANT: datos documentales privados por usuario.
-- Ejecutar desde Supabase SQL Editor o migraciones administradas.
create extension if not exists pgcrypto;

create table if not exists public.galant_documentos (
    id uuid primary key default gen_random_uuid(),
    usuario_id uuid not null references auth.users(id) on delete cascade,
    archivo text not null check (char_length(archivo) between 1 and 255),
    tipo text not null check (tipo in ('cotizaciones','f30_1')),
    ruta_storage text not null unique,
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    estado text not null default 'pendiente'
        check (estado in ('pendiente','procesando','completado','requiere_revision','error')),
    resultado jsonb not null default '{}'::jsonb,
    error text,
    created_at timestamptz not null default now(),
    procesado_at timestamptz,
    constraint galant_doc_duplicado unique (usuario_id,tipo,sha256)
);

create index if not exists idx_galant_doc_usuario_fecha
    on public.galant_documentos(usuario_id,created_at desc);
create index if not exists idx_galant_doc_pendientes
    on public.galant_documentos(created_at) where estado='pendiente';

alter table public.galant_documentos enable row level security;
revoke all on public.galant_documentos from public, anon, authenticated;
grant select, insert on public.galant_documentos to authenticated;
grant all on public.galant_documentos to service_role;

drop policy if exists "galant_user_read" on public.galant_documentos;
create policy "galant_user_read" on public.galant_documentos for select
    to authenticated using ((select auth.uid()) = usuario_id);

drop policy if exists "galant_user_insert" on public.galant_documentos;
create policy "galant_user_insert" on public.galant_documentos for insert
    to authenticated with check (
        (select auth.uid()) = usuario_id
        and estado = 'pendiente'
        and resultado = '{}'::jsonb
        and error is null
        and split_part(ruta_storage,'/',1) = (select auth.uid())::text
    );

-- PDF privados; no crear un bucket público.
insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('galant-documentos','galant-documentos',false,26214400,array['application/pdf'])
on conflict (id) do nothing;

drop policy if exists "galant_storage_insert" on storage.objects;
create policy "galant_storage_insert" on storage.objects for insert
    to authenticated
    with check (
        bucket_id = 'galant-documentos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );

drop policy if exists "galant_storage_select" on storage.objects;
create policy "galant_storage_select" on storage.objects for select
    to authenticated
    using (
        bucket_id = 'galant-documentos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );

drop policy if exists "galant_storage_delete" on storage.objects;
create policy "galant_storage_delete" on storage.objects for delete
    to authenticated
    using (
        bucket_id = 'galant-documentos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );

-- Los estados del OCR son modificados SOLO por el proceso privado de servicio.
create or replace function public.galant_reclamar_trabajos(max_trabajos integer default 3)
returns setof public.galant_documentos
language plpgsql security definer set search_path=public
as $$
begin
  if (select auth.role()) is distinct from 'service_role' then
      raise exception 'Acceso denegado';
  end if;
  return query
  with pendientes as (
      select id from public.galant_documentos
      where estado='pendiente'
      order by created_at
      for update skip locked
      limit least(greatest(max_trabajos,1),10)
  )
  update public.galant_documentos d
  set estado='procesando'
  from pendientes
  where d.id=pendientes.id
  returning d.*;
end;
$$;
revoke all on function public.galant_reclamar_trabajos(integer)
    from public, anon, authenticated;
grant execute on function public.galant_reclamar_trabajos(integer) to service_role;
