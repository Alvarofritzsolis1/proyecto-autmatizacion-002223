-- Recuperar trabajos atascados si se interrumpe el proceso OCR.
alter table public.galant_documentos
    add column if not exists iniciado_at timestamptz;
alter table public.galant_documentos
    add column if not exists intentos integer not null default 0;

create or replace function public.galant_reclamar_trabajos(max_trabajos integer default 3)
returns setof public.galant_documentos
language plpgsql security definer set search_path=public
as $$
begin
    if (select auth.role()) is distinct from 'service_role' then
        raise exception 'Acceso denegado';
    end if;
    -- Reintento limitado; nunca crear una cola infinita.
    update public.galant_documentos
    set estado='error', error='El OCR excedió el máximo de reintentos'
    where estado='procesando'
      and iniciado_at < now() - interval '30 minutes'
      and intentos >= 3;

    return query
    with elegibles as (
        select id from public.galant_documentos
        where estado='pendiente'
           or (
               estado='procesando'
               and iniciado_at < now() - interval '30 minutes'
               and intentos < 3
           )
        order by created_at
        for update skip locked
        limit least(greatest(max_trabajos,1),10)
    )
    update public.galant_documentos d
    set estado='procesando', iniciado_at=now(), intentos=d.intentos+1
    from elegibles where d.id=elegibles.id
    returning d.*;
end;
$$;
revoke all on function public.galant_reclamar_trabajos(integer)
    from public, anon, authenticated;
grant execute on function public.galant_reclamar_trabajos(integer) to service_role;
