# db.py
import sqlite3
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
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------------------------------------------------------------
#  Initialise all tables (called once at startup)
# ----------------------------------------------------------------------
def init_db() -> None:
    with _connect() as conn:
        cur = conn.cursor()
        # usuarios
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id_telegram INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL CHECK (rol IN ('admin','empleado'))
            )
            """
        )
        # inventario
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_producto TEXT NOT NULL UNIQUE,
                cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
                precio_base REAL NOT NULL CHECK (precio_base >= 0),
                precio_minimo_venta REAL NOT NULL CHECK (precio_minimo_venta >= 0),
                valor_total_stock REAL NOT NULL
            )
            """
        )
        # ventas_pedidos
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ventas_pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente TEXT NOT NULL,
                producto TEXT NOT NULL,
                cantidad INTEGER NOT NULL CHECK (cantidad > 0),
                precio_vendido REAL NOT NULL CHECK (precio_vendido >= 0),
                subtotal REAL NOT NULL,
                estado_pago TEXT NOT NULL CHECK (estado_pago IN ('DEBE','PAGO','PARCIAL')),
                saldo_pendiente REAL NOT NULL,
                fecha TIMESTAMP NOT NULL
            )
            """
        )
        # Añadir columna metodo_pago si no existe
        try:
            cur.execute("ALTER TABLE ventas_pedidos ADD COLUMN metodo_pago TEXT NOT NULL DEFAULT 'Desconocido'")
        except Exception:
            pass
        # gastos
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gastos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL CHECK (tipo IN ('operativo_bar','nomina','servicios','externo')),
                descripcion TEXT NOT NULL,
                monto REAL NOT NULL CHECK (monto >= 0),
                fecha TIMESTAMP NOT NULL
            )
            """
        )
        conn.commit()

# ----------------------------------------------------------------------
#  USER functions
# ----------------------------------------------------------------------
def get_user(id_telegram: int) -> Dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id_telegram, nombre, rol FROM usuarios WHERE id_telegram = ?",
            (id_telegram,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_user(id_telegram: int, nombre: str, rol: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usuarios (id_telegram, nombre, rol) VALUES (?,?,?)",
            (id_telegram, nombre, rol),
        )
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
        conn.execute(
            """
            INSERT INTO inventario (nombre_producto, cantidad, precio_base,
                                   precio_minimo_venta, valor_total_stock)
            VALUES (?,?,?,?,?)
            """,
            (nombre_producto, cantidad, precio_base, precio_minimo_venta, valor_total),
        )
        conn.commit()


def remove_product(nombre_producto: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM inventario WHERE nombre_producto = ?",
            (nombre_producto,),
        )
        conn.commit()


def get_product(nombre_producto: str) -> Dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM inventario WHERE nombre_producto = ?",
            (nombre_producto,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_stock(nombre_producto: str, delta: int) -> None:
    """Increase (+) or decrease (-) stock and recalc valor_total_stock."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT cantidad, precio_base FROM inventario WHERE nombre_producto = ?",
            (nombre_producto,),
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
        conn.execute(
            """
            UPDATE inventario
            SET cantidad = ?, valor_total_stock = ?
            WHERE nombre_producto = ?
            """,
            (nueva_cantidad, nuevo_valor, nombre_producto),
        )
        conn.commit()


def list_inventory() -> List[Dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(
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
    Evita abrir conexiones SQLite anidadas que provocan el error
    "database is locked".
    """
    with _connect() as conn:
        # Obtener datos del producto dentro de la misma conexión
        cur = conn.execute(
            "SELECT cantidad, precio_base, precio_minimo_venta FROM inventario WHERE nombre_producto = ?",
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
            abono_val = 0.0
        elif estado_pago == "PAGO":
            saldo = 0.0
            abono_val = subtotal
        else:  # PARCIAL
            if not (0 < abono < subtotal):
                raise ValueError("El abono debe ser >0 y < subtotal.")
            saldo = subtotal - abono
            abono_val = abono
        # Insertar venta
        conn.execute(
            """
            INSERT INTO ventas_pedidos
            (cliente, producto, cantidad, precio_vendido, subtotal,
             estado_pago, saldo_pendiente, fecha)
            VALUES (?,?,?,?,?,?,?,?)
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
            ),
        )
        # Guardar método de pago
        conn.execute(
            "UPDATE ventas_pedidos SET metodo_pago = ? WHERE id = last_insert_rowid()",
            (metodo_pago,),
        )
        # Actualizar inventario en la misma conexión
        nuevo_stock = stock_actual - cantidad
        nuevo_valor = nuevo_stock * precio_base
        conn.execute(
            """
            UPDATE inventario
            SET cantidad = ?, valor_total_stock = ?
            WHERE nombre_producto = ?
            """,
            (nuevo_stock, nuevo_valor, producto),
        )
        conn.commit()


def query_pending_payments() -> List[Dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(
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
        conn.execute(
            """
            UPDATE ventas_pedidos
            SET saldo_pendiente = 0,
                estado_pago = 'PAGO'
            WHERE id = ?
            """,
            (sale_id,),
        )
        conn.commit()


def register_partial_payment(sale_id: int, abono: float) -> None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT saldo_pendiente, subtotal FROM ventas_pedidos WHERE id = ?",
            (sale_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Venta no encontrada.")
        if not (0 < abono <= row["saldo_pendiente"]):
            raise ValueError("Abono inválido.")
        nuevo_saldo = row["saldo_pendiente"] - abono
        nuevo_estado = "PAGO" if nuevo_saldo == 0 else "PARCIAL"
        conn.execute(
            """
            UPDATE ventas_pedidos
            SET saldo_pendiente = ?, estado_pago = ?
            WHERE id = ?
            """,
            (nuevo_saldo, nuevo_estado, sale_id),
        )
        conn.commit()

# ----------------------------------------------------------------------
#  EXPENSE functions
# ----------------------------------------------------------------------
def record_expense(tipo: str, descripcion: str, monto: float) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO gastos (tipo, descripcion, monto, fecha)
            VALUES (?,?,?,?)
            """,
            (tipo, descripcion, monto, datetime.datetime.now()),
        )
        conn.commit()

def list_expenses() -> List[Dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(
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
