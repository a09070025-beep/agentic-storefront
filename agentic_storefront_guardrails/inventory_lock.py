"""
inventory_lock.py
------------------
Fixes: "Scarcity Engine says 'Only 2 left' while multiple concurrent
negotiations can all agree to buy that same unit" -> overselling.

Approach: a short-TTL reservation. When a negotiation reaches "accept"
and is about to generate a payment link, it must first reserve a unit.
Reservations expire automatically if the payment isn't completed in
time, releasing stock back. This is intentionally simple (in-memory +
lock) — for production, back it with Redis (SETNX + TTL) instead, but
the semantics below are exactly what you want.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Reservation:
    sku: str
    negotiation_id: str
    expires_at: float


class InventoryManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._stock: Dict[str, int] = {}
        self._reservations: Dict[str, Reservation] = {}  # key: reservation_id

    def set_stock(self, sku: str, quantity: int) -> None:
        with self._lock:
            self._stock[sku] = quantity

    def available(self, sku: str) -> int:
        """Real available count = raw stock minus active (non-expired)
        reservations. This is what your scarcity-messaging logic should
        read from, not raw stock."""
        with self._lock:
            self._expire_locked()
            reserved = sum(1 for r in self._reservations.values() if r.sku == sku)
            return max(0, self._stock.get(sku, 0) - reserved)

    def reserve(self, sku: str, negotiation_id: str, ttl_seconds: int = 180) -> str:
        """
        Call this the moment a negotiation reaches 'accept', BEFORE
        calling the payment-link tool. Raises if nothing is available.
        Returns a reservation_id to release/confirm later.
        """
        with self._lock:
            self._expire_locked()
            reserved = sum(1 for r in self._reservations.values() if r.sku == sku)
            if self._stock.get(sku, 0) - reserved <= 0:
                raise RuntimeError(f"No stock available to reserve for {sku}")
            reservation_id = f"{sku}:{negotiation_id}:{time.time()}"
            self._reservations[reservation_id] = Reservation(
                sku=sku, negotiation_id=negotiation_id,
                expires_at=time.time() + ttl_seconds,
            )
            return reservation_id

    def confirm(self, reservation_id: str) -> None:
        """Call after payment succeeds — permanently decrements stock
        and removes the reservation."""
        with self._lock:
            res = self._reservations.pop(reservation_id, None)
            if res is not None:
                self._stock[res.sku] = max(0, self._stock.get(res.sku, 0) - 1)

    def release(self, reservation_id: str) -> None:
        """Call on payment failure/timeout/buyer abandonment."""
        with self._lock:
            self._reservations.pop(reservation_id, None)

    def _expire_locked(self) -> None:
        now = time.time()
        expired = [rid for rid, r in self._reservations.items() if r.expires_at < now]
        for rid in expired:
            self._reservations.pop(rid, None)
