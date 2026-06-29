# db.py
import os
import psycopg2
from urllib.parse import urlparse
from psycopg2.extras import RealDictCursor
import datetime
from typing import List, Dict, Any

from config import DB_PATH, SIGNO_MONEDA, FORMATO_MILES

# ----------------------------------------------------------------------
#  Helper to format monetary values according to the global flag
# ----------------------------------------------------------------------
def _fmt_money(value: float) -> str:
    if FORMATO_MILES:
        integer_part = int(value)
        return f"{SIGNO_MONEDA}{integer_part:,}".replace(",", ".")
    return f"{SIGNO_MONEDA}{value:.2f}"

# ----------------------------------------------------------------------
#  Database connection (simple synchronous wrapper)
# ----------------------------------------------------------------------
def _connect():
    """Create a psycopg2 connection using the DATABASE_URL environment variable.
    Returns a connection object that can be used as a context manager.
    """
    url = os.getenv('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL no está configurada')
    result = urlparse(url)
    conn = psycopg2.connect(
        dbname=result.path.lstrip('/'),
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
    )
    # Autocommit disabled so we can manage transactions manually (like SQLite)
    conn.autocommit = False
    return conn

# ----------------------------------------------------------------------
#  Initialise all tables (called once at startup)
# ----------------------------------------------------------------------
def init_db() -> None:
    """Inicialización de la base de datos.
    En entornos PostgreSQL la estructura se crea fuera del código (por ejemplo, en Supabase).
    Esta función se mantiene por compatibilidad, pero no ejecuta ninguna sentencia.
    """
    # No se necesita crear tablas en PostgreSQL si ya existen.
    return

# ----------------------------------------------------------------------
#  USER functions
# ----------------------------------------------------------------------
def get_user(id_telegram: int) -> Dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id_telegram, nombre, rol FROM usuarios WHERE id_telegram = %s",
                (id_telegram,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def create_user(id_telegram: int, nombre: str, rol: str) -> None:
    """Insert a new user or update the role if it already exists.

    PostgreSQL supports ``ON CONFLICT``; we use it to avoid duplicate‑key errors when a user
    re‑logs with the same Telegram ID.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO usuarios (id_telegram, nombre, rol)
                VALUES (%s, %s, %s)
                ON CONFLICT (id_telegram) DO UPDATE SET nombre = EXCLUDED.nombre, rol = EXCLUDED.rol
                """,
                (id_telegram, nombre, rol),
            )
        conn.commit()


def delete_user(id_telegram: int) -> None:
    """Remove any existing user record – used when switching roles or resetting."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuarios WHERE id_telegram = %s", (id_telegram,))
        conn.commit()

# ----------------------------------------------------------------------
#  INVENTORY functions
# ----------------------------------------------------------------------
def add_product(
    nombre_producto: str,
    cantidad: int,
    precio_base: float,
    precio_minimo_venta: float,
) -> None:
    valor_total = cantidad * precio_base
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inventario (nombre_producto, cantidad, precio_base,
                                       precio_minimo_venta, valor_total_stock)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (nombre_producto, cantidad, precio_base, precio_minimo_venta, valor_total),
            )
        conn.commit()


def remove_product(nombre_producto: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM inventario WHERE nombre_producto = %s",
                (nombre_producto,)
            )
        conn.commit()


def get_product(nombre_producto: str) -> Dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM inventario WHERE nombre_producto = %s",
                (nombre_producto,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_stock(nombre_producto: str, delta: int) -> None:
    """Increase (+) or decrease (-) stock and recalc valor_total_stock."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT cantidad, precio_base FROM inventario WHERE nombre_producto = %s",
                (nombre_producto,)
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Producto '{nombre_producto}' no encontrado.")
            nueva_cantidad = row["cantidad"] + delta
            if nueva_cantidad < 0:
                raise ValueError(
                    f"No hay suficiente stock de '{nombre_producto}'. Disponible: {row['cantidad']}"
                )
            nuevo_valor = nueva_cantidad * row["precio_base"]
            # Update row
            cur.execute(
                """
                UPDATE inventario
                SET cantidad = %s, valor_total_stock = %s
                WHERE nombre_producto = %s
                """,
                (nueva_cantidad, nuevo_valor, nombre_producto)
            )
        conn.commit()


def list_inventory() -> List[Dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT nombre_producto, cantidad, precio_base,
                       precio_minimo_venta, valor_total_stock
                FROM inventario
                ORDER BY nombre_producto
                """
            )
            return [dict(r) for r in cur.fetchall()]

# ----------------------------------------------------------------------
#  SALES functions
# ----------------------------------------------------------------------
def record_sale(
    cliente: str,
    producto: str,
    cantidad: int,
    precio_vendido: float,
    estado_pago: str,
    metodo_pago: str = "Desconocido",
    abono: float = 0.0,
) -> None:
    """Registra una venta y actualiza el stock en una única transacción.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Obtener datos del producto dentro de la misma conexión
            cur.execute(
                "SELECT cantidad, precio_base, precio_minimo_venta FROM inventario WHERE nombre_producto = %s",
                (producto,)
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Producto '{producto}' no existe.")
            stock_actual, precio_base, precio_minimo = row["cantidad"], row["precio_base"], row["precio_minimo_venta"]
            if cantidad > stock_actual:
                raise ValueError(
                    f"Stock insuficiente: {stock_actual} disponible, se solicitaron {cantidad}."
                )
            if precio_vendido < precio_minimo:
                raise ValueError(
                    f"Precio de venta menor al mínimo permitido ({_fmt_money(precio_minimo)})."
                )
            subtotal = precio_vendido * cantidad
            if estado_pago == "DEBE":
                saldo = subtotal
            elif estado_pago == "PAGO":
                saldo = 0.0
            else:  # PARCIAL
                if not (0 < abono < subtotal):
                    raise ValueError("El abono debe ser >0 y < subtotal.")
                saldo = subtotal - abono
            # Insertar venta (incluyendo método de pago)
            cur.execute(
                """
                INSERT INTO ventas_pedidos
                (cliente, producto, cantidad, precio_vendido, subtotal,
                 estado_pago, saldo_pendiente, fecha, metodo_pago)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    cliente,
                    producto,
                    cantidad,
                    precio_vendido,
                    subtotal,
                    estado_pago,
                    saldo,
                    datetime.datetime.now(),
                    metodo_pago,
                ),
            )
            # Actualizar inventario en la misma conexión
            nuevo_stock = stock_actual - cantidad
            nuevo_valor = nuevo_stock * precio_base
            cur.execute(
                """
                UPDATE inventario
                SET cantidad = %s, valor_total_stock = %s
                WHERE nombre_producto = %s
                """,
                (nuevo_stock, nuevo_valor, producto)
            )
        conn.commit()


def query_pending_payments() -> List[Dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, cliente, producto, cantidad, subtotal, saldo_pendiente
                FROM ventas_pedidos
                WHERE saldo_pendiente > 0
                ORDER BY fecha ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def mark_payment_full(sale_id: int) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ventas_pedidos
                SET saldo_pendiente = 0,
                    estado_pago = 'PAGO'
                WHERE id = %s
                """,
                (sale_id,)
            )
        conn.commit()


def register_partial_payment(sale_id: int, abono: float) -> None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT saldo_pendiente, subtotal FROM ventas_pedidos WHERE id = %s",
                (sale_id,)
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Venta no encontrada.")
            if not (0 < abono <= row["saldo_pendiente"]):
                raise ValueError("Abono inválido.")
            nuevo_saldo = row["saldo_pendiente"] - abono
            nuevo_estado = "PAGO" if nuevo_saldo == 0 else "PARCIAL"
            cur.execute(
                """
                UPDATE ventas_pedidos
                SET saldo_pendiente = %s, estado_pago = %s
                WHERE id = %s
                """,
                (nuevo_saldo, nuevo_estado, sale_id)
            )
        conn.commit()

# ----------------------------------------------------------------------
#  EXPENSE functions
# ----------------------------------------------------------------------
def record_expense(tipo: str, descripcion: str, monto: float) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gastos (tipo, descripcion, monto, fecha)
                VALUES (%s,%s,%s,%s)
                """,
                (tipo, descripcion, monto, datetime.datetime.now()),
            )
        conn.commit()

def list_expenses() -> List[Dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, tipo, descripcion, monto, fecha FROM gastos ORDER BY fecha DESC"
            )
            return [dict(r) for r in cur.fetchall()]

# ----------------------------------------------------------------------
#  REPORT helper – used by reports.py
# ----------------------------------------------------------------------
def weekly_summary(month: int, weeks: List[int]) -> Dict[str, Any]:
    """Return a dict with pandas DataFrames for sales and expenses and totals.
    month: integer (1-12)
    weeks: list of ISO week numbers (e.g., [1,2,3])
    """
    import pandas as pd

    def week_range(week_no: int) -> tuple[datetime.date, datetime.date]:
        monday = datetime.date.fromisocalendar(datetime.datetime.now().year, week_no, 1)
        sunday = monday + datetime.timedelta(days=6)
        return monday, sunday

    with _connect() as conn:
        sales_df = pd.read_sql_query(
            "SELECT fecha, subtotal FROM ventas_pedidos", conn, parse_dates=["fecha"]
        )
        gastos_df = pd.read_sql_query(
            "SELECT fecha, tipo, descripcion, monto FROM gastos", conn, parse_dates=["fecha"]
        )

    # Filter by month
    sales_month = sales_df[sales_df["fecha"].dt.month == month]
    gastos_month = gastos_df[gastos_df["fecha"].dt.month == month]

    # Filter by weeks (if any provided)
    if weeks:
        week_masks = []
        for w in weeks:
            start, end = week_range(w)
            week_masks.append(
                (sales_month["fecha"].dt.date >= start) & (sales_month["fecha"].dt.date <= end)
            )
        sales_filtered = sales_month[pd.concat(week_masks, axis=1).any(axis=1)]

        week_masks_g = []
        for w in weeks:
            start, end = week_range(w)
            week_masks_g.append(
                (gastos_month["fecha"].dt.date >= start) & (gastos_month["fecha"].dt.date <= end)
            )
        gastos_filtered = gastos_month[pd.concat(week_masks_g, axis=1).any(axis=1)]
    else:
        sales_filtered = sales_month
        gastos_filtered = gastos_month

    total_ventas = float(sales_filtered["subtotal"].sum())
    total_gastos = float(gastos_filtered["monto"].sum())
    neto = total_ventas - total_gastos
    return {
        "ventas": sales_filtered,
        "gastos": gastos_filtered,
        "totales": {"ventas": total_ventas, "gastos": total_gastos, "neto": neto},
    }
