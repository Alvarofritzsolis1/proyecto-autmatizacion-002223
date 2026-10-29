-- GALANT: presupuesto compartido y transaccional para Google Vision.
-- Aplicar DESPUÉS de las migraciones 20261029_galant_secure.sql y _retries.sql.
-- Evita llamadas de la propia aplicación por encima del límite.
-- NO equivale a limitar cargos de otros proyectos o llamadas externas de Google.
create table if not exists public.galant_vision_consumo (
    periodo date not null,
    dia date not null,
    unidades integer not null default 0 check (unidades >= 0),
    primary key(periodo,dia)
);
alter table public.galant_vision_consumo enable row level security;
revoke all on public.galant_vision_consumo from public, anon, authenticated;
grant select,insert,update on public.galant_vision_consumo to service_role;

create or replace function public.galant_reservar_vision(
    max_mensual integer default 300,
    max_diario integer default 20
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    mes_actual date := date_trunc('month', now() at time zone 'UTC')::date;
    dia_actual date := (now() at time zone 'UTC')::date;
    usados_mes integer;
    usados_dia integer;
    limite_mes integer := least(greatest(coalesce(max_mensual,0),0),900);
    limite_dia integer := least(greatest(coalesce(max_diario,0),0),30);
begin
    if (select auth.role()) is distinct from 'service_role' then
        raise exception 'Solo el trabajador privado puede reservar OCR externo';
    end if;
    -- Cada ejecución consume una unidad incluso si Vision falla: conservador.
    -- Bloqueo transaccional evita exceder la cuota por trabajadores paralelos.
    perform pg_advisory_xact_lock(hashtext('galant_vision'), hashtext(mes_actual::text));
    select coalesce(sum(unidades),0) into usados_mes
      from public.galant_vision_consumo where periodo=mes_actual;
    select coalesce(unidades,0) into usados_dia
      from public.galant_vision_consumo
      where periodo=mes_actual and dia=dia_actual;
    usados_dia := coalesce(usados_dia,0);

    if limite_mes=0 or limite_dia=0
       or usados_mes>=limite_mes or usados_dia>=limite_dia then
        return false;
    end if;

    insert into public.galant_vision_consumo(periodo,dia,unidades)
        values(mes_actual,dia_actual,1)
    on conflict(periodo,dia)
        do update set unidades=public.galant_vision_consumo.unidades+1;
    return true;
end;
$$;
revoke all on function public.galant_reservar_vision(integer,integer)
    from public, anon, authenticated;
grant execute on function public.galant_reservar_vision(integer,integer)
    to service_role;
