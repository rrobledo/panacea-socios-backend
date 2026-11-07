-- Ajuste de puntos según el total de ventas registradas por socio — versión para DataGrip.
--
-- Para cada socio con ventas:
--   corresponde = floor(total de sus ventas / monto_por_punto)      (por defecto 1000 pesos = 1 punto)
--   ya_otorgado = puntos que ya recibió POR COMPRAS:
--                   ACUMULACION + REVERSO_COMPRA + ajustes previos de este mismo script
--   diferencia  = corresponde - ya_otorgado
-- Si la diferencia es positiva se registra un movimiento MIGRACION por esa cantidad y se
-- suma al saldo del socio (movimientos_puntos + socios.saldo_puntos).
--
-- Qué NO se toca:
--   - Canjes, juegos, expiraciones, ajustes manuales y el bono de bienvenida: no cuentan
--     como "ya otorgado", así que el socio conserva lo que gastó/recibió por esas vías.
--   - Socios a los que ya se les dio MÁS de lo que corresponde: no se les descuenta nada
--     (aparecen en el resumen como "con_exceso").
--   - reglas_puntos: la conversión se usa solo para este ajuste.
--
-- Se puede ejecutar más de una vez: solo registra lo que falte.
--
-- CÓMO USARLO
--   1. Revisar el parámetro monto_por_punto.
--   2. Ejecutar TODO el script (seleccionar todo + Ctrl+Enter).
--   3. Revisar los dos SELECT finales (detalle por socio y resumen).
--   4. Por defecto termina con ROLLBACK (simulación). Para aplicar, cambiar la última
--      línea por COMMIT y volver a ejecutar todo.

BEGIN;

-- ══ PARÁMETROS ════════════════════════════════════════════════════════════════
CREATE TEMP TABLE params ON COMMIT DROP AS
SELECT 1000::numeric                              AS monto_por_punto,
       'ajuste_ventas_1000'::text                 AS marca,        -- identifica los ajustes de este script
       'Ajuste por ventas registradas (1000 pesos = 1 punto)'::text AS descripcion;

DO $$
BEGIN
  IF (SELECT monto_por_punto FROM params) IS NULL OR (SELECT monto_por_punto FROM params) <= 0 THEN
    RAISE EXCEPTION 'monto_por_punto debe ser mayor a 0';
  END IF;
  -- Bloquea los socios con ventas para que la app no les cambie el saldo mientras tanto
  PERFORM 1 FROM socios
  WHERE id IN (SELECT socio_id FROM registro_ventas WHERE socio_id IS NOT NULL)
  FOR UPDATE;
END $$;

-- ══ Cálculo ═══════════════════════════════════════════════════════════════════
CREATE TEMP TABLE ajuste ON COMMIT DROP AS
WITH ventas AS (
  SELECT socio_id, count(*) AS cantidad_ventas, COALESCE(sum(importe), 0) AS total_ventas
  FROM registro_ventas
  WHERE socio_id IS NOT NULL
  GROUP BY socio_id
),
otorgado AS (
  SELECT m.socio_id, sum(m.puntos) AS puntos
  FROM movimientos_puntos m CROSS JOIN params p
  WHERE m.tipo IN ('ACUMULACION', 'REVERSO_COMPRA')
     OR (m.tipo = 'MIGRACION' AND m.creado_por = p.marca)
  GROUP BY m.socio_id
)
SELECT v.socio_id,
       v.cantidad_ventas,
       v.total_ventas,
       GREATEST(floor(v.total_ventas / p.monto_por_punto), 0)::int                          AS corresponde,
       COALESCE(o.puntos, 0)::int                                                           AS ya_otorgado,
       GREATEST(floor(v.total_ventas / p.monto_por_punto), 0)::int - COALESCE(o.puntos, 0)  AS diferencia
FROM ventas v
CROSS JOIN params p
LEFT JOIN otorgado o ON o.socio_id = v.socio_id;

-- ══ Ledger ════════════════════════════════════════════════════════════════════
INSERT INTO movimientos_puntos (socio_id, tipo, puntos, descripcion, creado_por, creado_en)
SELECT a.socio_id, 'MIGRACION', a.diferencia, p.descripcion, p.marca, now() AT TIME ZONE 'UTC'
FROM ajuste a CROSS JOIN params p
WHERE a.diferencia > 0;

-- ══ Saldo cacheado ════════════════════════════════════════════════════════════
UPDATE socios s
SET saldo_puntos = COALESCE(s.saldo_puntos, 0) + a.diferencia
FROM ajuste a
WHERE s.id = a.socio_id AND a.diferencia > 0;

-- ══ Detalle por socio ═════════════════════════════════════════════════════════
SELECT a.socio_id,
       s.nombre_apellido,
       a.cantidad_ventas,
       a.total_ventas,
       a.corresponde,
       a.ya_otorgado,
       GREATEST(a.diferencia, 0) AS puntos_agregados,
       s.saldo_puntos            AS saldo_final
FROM ajuste a
JOIN socios s ON s.id = a.socio_id
ORDER BY a.diferencia DESC, a.socio_id;

-- ══ Resumen ═══════════════════════════════════════════════════════════════════
SELECT count(*)                                              AS socios_con_ventas,
       count(*) FILTER (WHERE diferencia > 0)                AS socios_ajustados,
       count(*) FILTER (WHERE diferencia = 0)                AS ya_al_dia,
       count(*) FILTER (WHERE diferencia < 0)                AS con_exceso,
       COALESCE(sum(diferencia) FILTER (WHERE diferencia > 0), 0) AS puntos_agregados
FROM ajuste;

-- ══ Confirmar o revertir ══════════════════════════════════════════════════════
-- ROLLBACK = simulación (no se guarda nada). Cambiar por COMMIT para aplicar.
ROLLBACK;
